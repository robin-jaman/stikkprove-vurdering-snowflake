from __future__ import annotations

import os
from typing import Any

import pandas as pd

from src.schema import (
    ASSESSMENT_FIELDS,
    ASSESSMENT_KEY_FIELDS,
    plan_table_sync,
    snowflake_add_column_sql,
    snowflake_column,
    snowflake_create_sql,
)


_ensured_tables: set[str] = set()


def snowflake_configured() -> bool:
    from src.db import _active_session

    if _active_session() is not None:
        return True
    required = [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
    ]
    return all(os.getenv(name) for name in required)


def _table_name() -> str:
    return os.getenv("STIKKPROVE_VURDERING_TABLE", "STIKKPROVE_VURDERINGER")


def _connect():
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError(
            "snowflake-connector-python er ikke installert. "
            "Kj\u00f8r: pip install snowflake-connector-python"
        ) from exc

    if not snowflake_configured():
        raise RuntimeError(
            "Mangler Snowflake-variabler: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
            "SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE"
        )

    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "snowflake"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


def _align_columns(frame: pd.DataFrame) -> pd.DataFrame:
    from src.kolonner import oversett

    return oversett(frame)


DEFAULT_QUERY = "SELECT * FROM STIKKPROVER"
QUERY_SETTING = "snowflake_query"
TABLE_SETTING = "snowflake_tabell"
WRITEBACK_SETTING = "snowflake_tilbakeskriving"

# Tabellen stikkpr\u00f8vene ligger i hos SPK. Kan endres under Administrasjon.
DEFAULT_TABLE = (
    "TEST.DATAFORVALTNING_RAPPORTERING."
    "BT_STIKKPROEVER_PAA_VARSLER_FOR_KI_LOENNSFILMOTTAK"
)


def source_table() -> str:
    """Tabellen stikkpr\u00f8vene hentes fra. Settes i appen, siden Streamlit i
    Snowflake ikke har milj\u00f8variabler \u00e5 sette den med."""
    from src.store import get_setting

    fallback = os.getenv("STIKKPROVE_KILDETABELL", DEFAULT_TABLE)
    return get_setting(TABLE_SETTING, fallback).strip()


def set_source_table(navn: str) -> None:
    from src.store import set_setting

    set_setting(TABLE_SETTING, str(navn or "").strip())


def writeback_enabled() -> bool:
    from src.store import get_setting

    return get_setting(WRITEBACK_SETTING, "") == "ja"


def set_writeback(paa: bool) -> None:
    from src.store import set_setting

    set_setting(WRITEBACK_SETTING, "ja" if paa else "nei")


def sample_query() -> str:
    """SQL-en som henter stikkpr\u00f8vene. Tabellnavnet alene holder; en egen
    sp\u00f8rring overstyrer det for den som trenger filtrering eller join."""
    from src.store import get_setting

    lagret = get_setting(QUERY_SETTING, "").strip()
    if lagret:
        return lagret
    tabell = source_table()
    if tabell:
        return "SELECT * FROM " + tabell
    return os.getenv("STIKKPROVE_QUERY", DEFAULT_QUERY)


def load_samples() -> pd.DataFrame:
    from src.db import query_snowflake_frame

    return _align_columns(query_snowflake_frame(sample_query()))


def table_columns(tabell: str = "") -> list[str]:
    """Kolonnenavnene i kildetabellen, slik de faktisk staar i Snowflake.

    Navnene skal rett inn i _sitert og videre inn i en UPDATE, saa her maa store
    og sma bokstaver vaere nettopp slik tabellen har dem.
    """
    from src.db import snowflake_column_names

    navn = (tabell or source_table()).strip()
    if not navn:
        raise RuntimeError("Ingen kildetabell er satt.")
    return snowflake_column_names("SELECT * FROM " + navn + " LIMIT 0")


def _sitert(navn: str) -> str:
    """Kolonnenavn med norske bokstaver og punktum maa i hermetegn."""
    return '"' + str(navn).replace('"', '""') + '"'


def _raden_finnes(tabell: str, id_kolonne: str, nummer: str) -> bool:
    """Sant hvis stikkproeven faktisk har en rad i kildetabellen.

    Uten denne sjekken ville en UPDATE mot et nummer som ikke finnes truffet
    null rader, og svaret ville forsvunnet ut av tabellen uten et ord.
    """
    from src.db import get_db

    rad = get_db().fetchone(
        "SELECT 1 AS funnet FROM "
        + tabell
        + " WHERE "
        + _sitert(id_kolonne)
        + " = ? LIMIT 1",
        (nummer,),
    )
    return rad is not None


def _innsettingsverdi(verdi: Any) -> Any:
    """Gjoer en celle fra et regneark klar for Snowflake."""
    if verdi is None:
        return None
    try:
        if pd.isna(verdi):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(verdi, pd.Timestamp):
        return verdi.isoformat()
    if isinstance(verdi, (str, int, float, bool)):
        return verdi
    return str(verdi)


def _ny_rad(
    tabell: str,
    kolonner: list[str],
    id_kolonne: str,
    nummer: str,
    svar: dict[str, Any],
    kilderad: object,
) -> str:
    """Lager raden i kildetabellen naar stikkproeven ikke finnes der fra for.

    Stikkproevedataene hentes fra grunnlaget stikkproeven kom fra, slik at den
    nye raden ser ut som de andre. Svarene vinner over eventuelle svar som
    allerede laa i regnearket.
    """
    from src.db import exec_snowflake
    from src.kolonner import finn_navn

    felter: dict[str, Any] = {id_kolonne: nummer}
    data = _som_oppslag(kilderad)
    for navn, verdi in data.items():
        if str(navn).startswith("_"):
            continue
        treff = finn_navn(kolonner, str(navn))
        if treff and treff != id_kolonne:
            felter[treff] = _innsettingsverdi(verdi)
    for felt, kolonne in writeback_plan(kolonner).items():
        if felt in svar:
            felter[kolonne] = svar.get(felt)

    navn_liste = list(felter)
    exec_snowflake(
        "INSERT INTO "
        + tabell
        + " ("
        + ", ".join(_sitert(navn) for navn in navn_liste)
        + ") VALUES ("
        + ", ".join(["?"] * len(navn_liste))
        + ")",
        [felter[navn] for navn in navn_liste],
    )
    return (
        "Stikkpr\u00f8ve "
        + nummer
        + " fantes ikke i "
        + tabell
        + ", s\u00e5 den ble lagt inn som en ny rad."
    )


def _som_oppslag(kilderad: object) -> dict[str, Any]:
    """Raden som en vanlig dict, enten den er en Series eller allerede en dict."""
    if kilderad is None:
        return {}
    if isinstance(kilderad, pd.Series):
        return {str(navn): verdi for navn, verdi in kilderad.items()}
    if isinstance(kilderad, dict):
        return {str(navn): verdi for navn, verdi in kilderad.items()}
    return {}


def writeback_plan(kolonner: list[str]) -> dict[str, str]:
    """Hvilke kolonner i kildetabellen svarene kan skrives til."""
    from src.kolonner import SVAR_TIL_KOLONNE, finn_navn

    plan: dict[str, str] = {}
    for felt, kolonnenavn in SVAR_TIL_KOLONNE.items():
        treff = finn_navn(kolonner, kolonnenavn)
        if treff:
            plan[felt] = treff
    for felt, kandidater in (
        ("saksbehandler", ("vurdert_av", "saksbehandler", "vurdert_av_bruker")),
        ("updated_at", ("vurdert_dt", "vurdert_tidspunkt", "updated_at")),
    ):
        for kandidat in kandidater:
            treff = finn_navn(kolonner, kandidat)
            if treff:
                plan[felt] = treff
                break
    return plan


def _writeback_values(record: dict[str, Any]) -> dict[str, Any]:
    """Slaar de to fritekstfeltene sammen med svaret de hoerer til.

    Skjemaet har atte felter og tabellen seks kolonner. Forskjellen er de to
    utdypningene, som her legges bak svaret sitt skilt med kolon.
    """
    svar = dict(record)
    handling = str(record.get("handling") or "").strip()
    annet = str(record.get("handling_annet") or "").strip()
    if handling.lower() == "annet" and annet:
        svar["handling"] = handling + ": " + annet
    vanlighet = str(record.get("vanlighet") or "").strip()
    unntak = str(record.get("unntak_forklaring") or "").strip()
    if vanlighet and unntak:
        svar["vanlighet"] = vanlighet + ": " + unntak
    return svar


def write_back_assessment(record: dict[str, Any], kilderad: object = None) -> str:
    """Skriver svaret inn i raden stikkpr\u00f8ven kom fra.

    Finnes ikke raden, lages den av stikkpr\u00f8vedataene i ``kilderad``. Det
    skjer bare for opplastede regneark; en stikkpr\u00f8ve fra tabellen selv har
    alltid en rad.

    Returnerer en melding hvis noe ble hoppet over, ellers tom streng.
    """
    from src.config import SAMPLE_ID_COL
    from src.db import exec_snowflake
    from src.kolonner import finn_navn

    tabell = source_table()
    if not tabell:
        raise RuntimeError("Ingen kildetabell er satt under Administrasjon.")
    kolonner = table_columns(tabell)
    id_kolonne = finn_navn(kolonner, SAMPLE_ID_COL)
    if not id_kolonne:
        raise RuntimeError(
            "Fant ingen kolonne for " + SAMPLE_ID_COL + " i " + tabell + "."
        )

    nummer = str(record.get("stikkprove_nr") or "")
    plan = writeback_plan(kolonner)
    svar = _writeback_values(record)
    if not _raden_finnes(tabell, id_kolonne, nummer):
        return _ny_rad(tabell, kolonner, id_kolonne, nummer, svar, kilderad)

    settes: list[str] = []
    verdier: list[Any] = []
    for felt, kolonne in plan.items():
        settes.append(_sitert(kolonne) + " = ?")
        verdier.append(svar.get(felt))
    if not settes:
        raise RuntimeError(
            "Fant ingen svarkolonner i " + tabell + " \u00e5 skrive til."
        )

    verdier.append(str(record.get("stikkprove_nr") or ""))
    exec_snowflake(
        "UPDATE "
        + tabell
        + " SET "
        + ", ".join(settes)
        + " WHERE "
        + _sitert(id_kolonne)
        + " = ?",
        verdier,
    )

    from src.kolonner import SVAR_TIL_KOLONNE

    mangler = [felt for felt in SVAR_TIL_KOLONNE if felt not in plan]
    if mangler:
        return "Disse svarene har ingen kolonne i " + tabell + ": " + ", ".join(mangler)
    return ""


def _listed_columns(cur: Any, table: str) -> list[str]:
    cur.execute("DESCRIBE TABLE " + table)
    names: list[str] = []
    for row in cur.fetchall():
        if not row:
            continue
        names.append(str(row[0]))
    return names


def _drop_column_sql(table: str, field: str) -> str:
    return (
        "ALTER TABLE "
        + table
        + " DROP COLUMN IF EXISTS "
        + snowflake_column(field)
    )


def _drop_not_null_sql(table: str, field: str) -> str:
    return (
        "ALTER TABLE "
        + table
        + " ALTER COLUMN "
        + snowflake_column(field)
        + " DROP NOT NULL"
    )


def ensure_assessment_table(cur: Any, table: str) -> None:
    if table in _ensured_tables:
        return
    cur.execute(snowflake_create_sql(table))
    existing = _listed_columns(cur, table)
    add, drop = plan_table_sync(existing)
    for field in add:
        cur.execute(snowflake_add_column_sql(table, field))
    for field in drop:
        dropped = False
        drop_sql = _drop_column_sql(table, field)
        for sql in (drop_sql, drop_sql.replace(" IF EXISTS", "")):
            try:
                cur.execute(sql)
                dropped = True
                break
            except Exception:
                continue
        if not dropped:
            cur.execute(_drop_not_null_sql(table, field))
    _ensured_tables.add(table)


def _record_value(record: dict[str, Any], field: str) -> Any:
    value = record.get(field)
    if field in {"kilde_id", "kilde"}:
        return str(value or "")
    return value


def save_assessment(record: dict[str, Any]) -> None:
    table = _table_name()
    columns = [snowflake_column(field) for field in ASSESSMENT_FIELDS]
    placeholders = ", ".join(["%s"] * len(columns))
    values = [_record_value(record, field) for field in ASSESSMENT_FIELDS]
    insert_sql = (
        "INSERT INTO "
        + table
        + " ("
        + ", ".join(columns)
        + ") VALUES ("
        + placeholders
        + ")"
    )
    delete_sql = (
        "DELETE FROM "
        + table
        + " WHERE "
        + " AND ".join(snowflake_column(field) + " = %s" for field in ASSESSMENT_KEY_FIELDS)
    )
    delete_values = [_record_value(record, field) for field in ASSESSMENT_KEY_FIELDS]
    with _connect() as conn:
        with conn.cursor() as cur:
            ensure_assessment_table(cur, table)
            cur.execute(delete_sql, delete_values)
            cur.execute(insert_sql, values)
        conn.commit()
