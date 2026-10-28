from __future__ import annotations

import base64
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import DB_PATH, EXPORT_DIR, SOURCES_DIR
from src.db import close_sqlite_connections, get_db
from src.schema import (
    ASSESSMENT_FIELDS,
    ASSESSMENT_KEY_FIELDS,
    LEFTOVER_ASSESSMENT_FIELDS,
    sqlite_assessments_copy_sql,
    sqlite_assessments_create_sql,
)

CLAIM_TTL = timedelta(minutes=20)
ASSIGN_ALL = "*"
SampleKey = tuple[str, str]

# Filer init_db allerede har gaatt gjennom i denne prosessen.
_klargjort: set[str] = set()
# Naar gamle laser sist ble ryddet bort, per fil.
_sist_ryddet: dict[str, datetime] = {}
RYDD_HVERT = timedelta(minutes=1)


def glem_database(db_path: Path = DB_PATH) -> None:
    """Nullstiller det appen husker om databasen. Brukes av testene."""
    _klargjort.discard(str(Path(db_path)))
    _sist_ryddet.pop(str(Path(db_path)), None)
    _memo.clear()
    close_sqlite_connections()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_oslo(iso_text: str | None) -> str:
    if not iso_text or str(iso_text) in {"None", "nan", "NaT"}:
        return ""
    try:
        parsed = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        oslo = ZoneInfo("Europe/Oslo")
    except Exception:
        oslo = timezone(timedelta(hours=1))
    return parsed.astimezone(oslo).strftime("%d.%m.%Y %H:%M")


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


class _ClosingConn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute("PRAGMA table_info(" + table + ")")]


def _add_column(conn: sqlite3.Connection, table: str, column: str, typedef: str) -> None:
    if column in _columns(conn, table):
        return
    conn.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + typedef)


def _db(db_path: Path = DB_PATH):
    init_db(db_path)
    return get_db(db_path)


# Lesinger som gjentas i samme kjoring av appen. En sporring mot Snowflake
# koster noen hundre millisekunder uansett hvor lite den henter, saa det monner
# aa lese en gang. Memoet toemmes ved starten av hver kjoring og ved hver
# skriving, slik at appen fortsatt ser det kolleger gjor.
_memo: dict[str, Any] = {}


def nullstill_lesinger() -> None:
    _memo.clear()


def _husk(nokkel: str, les):
    if nokkel not in _memo:
        _memo[nokkel] = les()
    return _memo[nokkel]


def _skriv(db, sql: str, params=None) -> int:
    _memo.clear()
    return db.execute(sql, params)


def _skriv_mange(db, table: str, columns, rows) -> None:
    _memo.clear()
    db.insert_many(table, columns, rows)


def _sort_sample_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "stikkprove_nr" not in frame.columns:
        return frame
    work = frame.copy()
    work["_nr"] = pd.to_numeric(work["stikkprove_nr"], errors="coerce")
    sort_cols = [col for col in ("kilde_id", "_nr", "stikkprove_nr", "saksbehandler") if col in work.columns or col == "_nr"]
    work = work.sort_values(sort_cols, kind="mergesort")
    return work.drop(columns=["_nr"]).reset_index(drop=True)


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    create_sql: str,
    copy_sql: str,
) -> None:
    new_table = table + "_new"
    conn.execute(create_sql.replace("CREATE TABLE " + table, "CREATE TABLE " + new_table, 1))
    conn.execute(copy_sql.replace("INTO " + table, "INTO " + new_table, 1))
    conn.execute("DROP TABLE " + table)
    conn.execute("ALTER TABLE " + new_table + " RENAME TO " + table)


def _rebuild_with_kilde_id(
    conn: sqlite3.Connection,
    table: str,
    create_sql: str,
    copy_sql: str,
) -> None:
    if "kilde_id" in _columns(conn, table):
        return
    _rebuild_table(conn, table, create_sql, copy_sql)


_ASSESSMENTS_CREATE_SQL = sqlite_assessments_create_sql()
_ASSESSMENTS_COPY_CURRENT_SQL = sqlite_assessments_copy_sql()


def _drop_unused_assessment_fields(conn: sqlite3.Connection) -> None:
    leftover = set(LEFTOVER_ASSESSMENT_FIELDS)
    if not leftover.intersection(_columns(conn, "assessments")):
        return
    _rebuild_table(conn, "assessments", _ASSESSMENTS_CREATE_SQL, _ASSESSMENTS_COPY_CURRENT_SQL)


# Innstillingstabellen rommer ogsaa administratorer og endringslogg, slik at
# appen klarer seg med faerre tabeller i Snowflake. Kroellalfa gjor at navnene
# aldri kolliderer med en vanlig innstilling.
ADMIN_NAVN = "@admin"
LOGG_NAVN = "@logg"


def _flytt_inn_i_settings(conn: sqlite3.Connection) -> None:
    """Flytter gamle admins- og admin_log-tabeller inn i settings."""
    if _har_navn_som_primaernokkel(conn):
        _rebuild_table(
            conn,
            "settings",
            "CREATE TABLE settings (navn TEXT NOT NULL, verdi TEXT, updated_at TEXT NOT NULL)",
            "INSERT INTO settings (navn, verdi, updated_at) "
            "SELECT navn, verdi, updated_at FROM settings",
        )
    for tabell, navn, kolonne, tid in (
        ("admins", ADMIN_NAVN, "snowflake_bruker", "created_at"),
        ("admin_log", LOGG_NAVN, "tekst", "happened_at"),
    ):
        if not _tabell_finnes(conn, tabell):
            continue
        conn.execute(
            "INSERT INTO settings (navn, verdi, updated_at) SELECT ?, "
            + kolonne
            + ", "
            + tid
            + " FROM "
            + tabell,
            (navn,),
        )
        conn.execute("DROP TABLE " + tabell)


def _tabell_finnes(conn: sqlite3.Connection, tabell: str) -> bool:
    rad = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (tabell,),
    ).fetchone()
    return rad is not None


def _har_navn_som_primaernokkel(conn: sqlite3.Connection) -> bool:
    for rad in conn.execute("PRAGMA table_info(settings)").fetchall():
        if str(rad[1]) == "navn" and int(rad[5] or 0) > 0:
            return True
    return False


def init_db(db_path: Path = DB_PATH) -> None:
    """Oppretter og oppdaterer tabellene. Gjores en gang per fil per prosess.

    Uten sperren kjorer hele denne gjennomgangen foran hver eneste sporring, og
    det er merkbart i appen.
    """
    db = get_db(db_path)
    if db.kind == "snowflake":
        db.ensure_schema()
        return
    merke = str(Path(db_path))
    if merke in _klargjort:
        return
    with _ClosingConn(_connect(db_path)) as conn:
        conn.execute(
            _ASSESSMENTS_CREATE_SQL.replace(
                "CREATE TABLE assessments",
                "CREATE TABLE IF NOT EXISTS assessments",
                1,
            )
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewers (
                navn TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                stikkprove_nr TEXT PRIMARY KEY,
                saksbehandler TEXT NOT NULL,
                claimed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                stikkprove_nr TEXT NOT NULL,
                saksbehandler TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (stikkprove_nr, saksbehandler)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT,
                original_name TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        source_cols = _columns(conn, "sources")
        if "url" not in source_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN url TEXT")
        cols = _columns(conn, "assessments")
        if "kilde" not in cols:
            conn.execute("ALTER TABLE assessments ADD COLUMN kilde TEXT")
        _rebuild_with_kilde_id(
            conn,
            "assessments",
            _ASSESSMENTS_CREATE_SQL,
            sqlite_assessments_copy_sql(kilde_id_expr="''"),
        )
        _rebuild_with_kilde_id(
            conn,
            "claims",
            """
            CREATE TABLE claims (
                kilde_id TEXT NOT NULL DEFAULT '',
                stikkprove_nr TEXT NOT NULL,
                saksbehandler TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (kilde_id, stikkprove_nr)
            )
            """,
            """
            INSERT INTO claims (kilde_id, stikkprove_nr, saksbehandler, claimed_at)
            SELECT '', stikkprove_nr, saksbehandler, claimed_at FROM claims
            """,
        )
        _rebuild_with_kilde_id(
            conn,
            "assignments",
            """
            CREATE TABLE assignments (
                kilde_id TEXT NOT NULL DEFAULT '',
                stikkprove_nr TEXT NOT NULL,
                saksbehandler TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (kilde_id, stikkprove_nr, saksbehandler)
            )
            """,
            """
            INSERT INTO assignments (kilde_id, stikkprove_nr, saksbehandler, assigned_at)
            SELECT '', stikkprove_nr, saksbehandler, assigned_at FROM assignments
            """,
        )
        _drop_unused_assessment_fields(conn)
        _add_column(conn, "reviewers", "snowflake_bruker", "TEXT")
        _add_column(conn, "claims", "opened_at", "TEXT")
        _add_column(conn, "sources", "file_updated_at", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_files (
                source_id TEXT PRIMARY KEY,
                filename TEXT,
                content_b64 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                navn TEXT NOT NULL,
                verdi TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        _flytt_inn_i_settings(conn)
        conn.execute(
            """
            UPDATE claims
            SET opened_at = claimed_at
            WHERE opened_at IS NULL OR opened_at = ''
            """
        )
        conn.commit()
    _klargjort.add(merke)


def _as_key(kilde_id: str | None, stikkprove_nr: str | None) -> SampleKey:
    return (str(kilde_id or ""), str(stikkprove_nr or ""))


def _normalize_key(item: SampleKey | str | None) -> SampleKey:
    if item is None:
        return ("", "")
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return _as_key(item[0], item[1])
    return _as_key("", item)


def sample_keys(samples: pd.DataFrame) -> list[SampleKey]:
    if samples is None or samples.empty:
        return []
    if "_kilde_id" not in samples.columns:
        from src.config import SAMPLE_ID_COL

        return [("", str(item)) for item in samples[SAMPLE_ID_COL].astype(str).tolist()]
    from src.config import SAMPLE_ID_COL

    return [
        _as_key(kilde_id, nr)
        for kilde_id, nr in zip(
            samples["_kilde_id"].astype(str),
            samples[SAMPLE_ID_COL].astype(str),
        )
    ]


def encode_sak(key: SampleKey | None) -> str:
    if not key:
        return ""
    return key[0] + "|" + key[1]


def decode_sak(text: str | None) -> SampleKey | None:
    value = str(text or "").strip()
    if not value:
        return None
    if "|" in value:
        kilde_id, nr = value.split("|", 1)
        return _as_key(kilde_id, nr)
    return _as_key("", value)


def save_assessment(record: dict[str, Any], db_path: Path = DB_PATH) -> None:
    payload = dict(record)
    payload["updated_at"] = _now_iso()
    payload["kilde"] = payload.get("kilde") or ""
    payload["kilde_id"] = str(payload.get("kilde_id") or "")
    db = _db(db_path)
    table = db.table("assessments")
    insert_cols = ", ".join(ASSESSMENT_FIELDS)
    values = [payload.get(field) for field in ASSESSMENT_FIELDS]
    placeholders = ", ".join(["?"] * len(ASSESSMENT_FIELDS))
    if db.kind == "sqlite":
        update_set = ", ".join(
            field + "=excluded." + field
            for field in ASSESSMENT_FIELDS
            if field not in ASSESSMENT_KEY_FIELDS
        )
        conflict = ", ".join(ASSESSMENT_KEY_FIELDS)
        _skriv(db,
            "INSERT INTO "
            + table
            + " ("
            + insert_cols
            + ") VALUES ("
            + placeholders
            + ") ON CONFLICT("
            + conflict
            + ") DO UPDATE SET "
            + update_set,
            values,
        )
        return
    key_sql = " AND ".join(field + " = ?" for field in ASSESSMENT_KEY_FIELDS)
    key_values = [payload.get(field) for field in ASSESSMENT_KEY_FIELDS]
    _skriv(db, "DELETE FROM " + table + " WHERE " + key_sql, key_values)
    _skriv(db,
        "INSERT INTO " + table + " (" + insert_cols + ") VALUES (" + placeholders + ")",
        values,
    )


def get_assessment(
    stikkprove_nr: str,
    saksbehandler: str,
    kilde_id: str = "",
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    db = _db(db_path)
    return db.fetchone(
        "SELECT * FROM "
        + db.table("assessments")
        + " WHERE kilde_id = ? AND stikkprove_nr = ? AND saksbehandler = ?",
        (str(kilde_id or ""), str(stikkprove_nr), saksbehandler),
    )


def list_assessments(
    saksbehandler: str | None = None, db_path: Path = DB_PATH
) -> pd.DataFrame:
    def les() -> pd.DataFrame:
        db = _db(db_path)
        query = "SELECT * FROM " + db.table("assessments")
        params: list[str] = []
        if saksbehandler:
            query += " WHERE saksbehandler = ?"
            params.append(saksbehandler)
        return _sort_sample_frame(db.frame(query, params))

    return _husk("svar:" + str(saksbehandler or "") + ":" + str(db_path), les).copy()


def _frame_keys(frame: pd.DataFrame) -> set[SampleKey]:
    if frame is None or frame.empty:
        return set()
    if "kilde_id" in frame.columns:
        return {
            _as_key(kilde_id, nr)
            for kilde_id, nr in zip(frame["kilde_id"], frame["stikkprove_nr"])
        }
    return {("", str(item)) for item in frame["stikkprove_nr"].astype(str)}


def assessed_ids(saksbehandler: str, db_path: Path = DB_PATH) -> set[SampleKey]:
    return _frame_keys(list_assessments(saksbehandler, db_path))


def _svarnokler(db_path: Path = DB_PATH) -> list[tuple[SampleKey, str, str]]:
    """Hvem som har svart paa hva, og naar. Leses en gang per kjoring.

    Tre tellinger trengte denne listen, og hver av dem leste tabellen selv.
    """

    def les() -> list[tuple[SampleKey, str, str]]:
        db = _db(db_path)
        rows = db.fetchall(
            "SELECT kilde_id, stikkprove_nr, saksbehandler, updated_at FROM "
            + db.table("assessments")
        )
        return [
            (
                _as_key(row["kilde_id"], row["stikkprove_nr"]),
                str(row["saksbehandler"]),
                str(row.get("updated_at") or ""),
            )
            for row in rows
        ]

    return _husk("svarnokler:" + str(db_path), les)


def completed_ids(db_path: Path = DB_PATH) -> set[SampleKey]:
    return {key for key, _navn, _tid in _svarnokler(db_path)}


def queue_stats(
    saksbehandler: str, keys: list[SampleKey], db_path: Path = DB_PATH
) -> dict[str, int]:
    """Teller ferdige svar for laget og for en person, i samme lesing."""
    wanted = {_as_key(kilde_id, nr) for kilde_id, nr in keys}
    laget: set[SampleKey] = set()
    mine: set[SampleKey] = set()
    for key, navn, _tid in _svarnokler(db_path):
        if key not in wanted:
            continue
        laget.add(key)
        if navn == saksbehandler:
            mine.add(key)
    team_done = len(laget)
    return {
        "team_done": team_done,
        "remaining": max(len(wanted) - team_done, 0),
        "mine": len(mine),
        "total": len(wanted),
    }


def _expire_claims(db_path: Path = DB_PATH) -> None:
    """Rydder bort laser som har gaatt ut paa tid.

    Dette er en skriving, og den skjedde ved hver eneste kjoring av appen.
    Lasene varer i 20 minutter, saa det holder aa rydde av og til.
    """
    merke = str(Path(db_path))
    naa = datetime.now(timezone.utc)
    sist = _sist_ryddet.get(merke)
    if sist is not None and naa - sist < RYDD_HVERT:
        return
    db = _db(db_path)
    cutoff = (naa - CLAIM_TTL).isoformat(timespec="seconds")
    _skriv(db,
        "DELETE FROM " + db.table("claims") + " WHERE claimed_at < ?",
        (cutoff,),
    )
    _sist_ryddet[merke] = naa


def release_claims(saksbehandler: str, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    _skriv(db,
        "DELETE FROM " + db.table("claims") + " WHERE saksbehandler = ?",
        (saksbehandler,),
    )


def touch_claim(
    stikkprove_nr: str,
    saksbehandler: str,
    kilde_id: str = "",
    db_path: Path = DB_PATH,
) -> None:
    if not stikkprove_nr or not saksbehandler:
        return
    db = _db(db_path)
    _skriv(db,
        "UPDATE "
        + db.table("claims")
        + " SET claimed_at = ? WHERE kilde_id = ? AND stikkprove_nr = ? AND saksbehandler = ?",
        (_now_iso(), str(kilde_id or ""), str(stikkprove_nr), saksbehandler),
    )


def _claim_holders(db, key: SampleKey) -> list[dict[str, Any]]:
    return db.fetchall(
        "SELECT saksbehandler, claimed_at, opened_at FROM "
        + db.table("claims")
        + " WHERE kilde_id = ? AND stikkprove_nr = ?",
        (key[0], key[1]),
    )


def _insert_claim(db, key: SampleKey, saksbehandler: str, now: str) -> bool:
    try:
        _skriv(db,
            "INSERT INTO "
            + db.table("claims")
            + " (kilde_id, stikkprove_nr, saksbehandler, claimed_at, opened_at) "
            + "VALUES (?, ?, ?, ?, ?)",
            (key[0], key[1], saksbehandler, now, now),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def claim_next(
    saksbehandler: str,
    sample_ids: list[SampleKey],
    prefer: SampleKey | None = None,
    db_path: Path = DB_PATH,
) -> SampleKey | None:
    db = _db(db_path)
    now = _now_iso()
    wanted = [_normalize_key(item) for item in sample_ids]
    wanted_set = set(wanted)
    _expire_claims(db_path)
    done = completed_ids(db_path)
    mine = db.fetchone(
        "SELECT kilde_id, stikkprove_nr FROM "
        + db.table("claims")
        + " WHERE saksbehandler = ?",
        (saksbehandler,),
    )
    if mine:
        current = _as_key(mine["kilde_id"], mine["stikkprove_nr"])
        if current in wanted_set:
            touch_claim(current[1], saksbehandler, kilde_id=current[0], db_path=db_path)
            return current
        release_claims(saksbehandler, db_path)
    taken = {
        _as_key(row["kilde_id"], row["stikkprove_nr"])
        for row in db.fetchall(
            "SELECT kilde_id, stikkprove_nr FROM " + db.table("claims")
        )
    }
    ordered: list[SampleKey] = []
    prefer_key = _normalize_key(prefer) if prefer else None
    if prefer_key and prefer_key[1] and prefer_key not in done and prefer_key not in taken:
        ordered.append(prefer_key)
    for key in wanted:
        if key not in ordered:
            ordered.append(key)
    for key in ordered:
        if key in done or key in taken:
            continue
        if not _insert_claim(db, key, saksbehandler, now):
            taken.add(key)
            continue
        holders = _claim_holders(db, key)
        if not holders:
            continue
        holders = sorted(
            holders,
            key=lambda row: (
                str(row.get("opened_at") or row.get("claimed_at") or ""),
                str(row.get("saksbehandler") or ""),
            ),
        )
        winner = str(holders[0].get("saksbehandler") or "")
        if winner == saksbehandler:
            _skriv(db,
                "DELETE FROM "
                + db.table("claims")
                + " WHERE kilde_id = ? AND stikkprove_nr = ? AND saksbehandler <> ?",
                (key[0], key[1], saksbehandler),
            )
            return key
        _skriv(db,
            "DELETE FROM "
            + db.table("claims")
            + " WHERE kilde_id = ? AND stikkprove_nr = ? AND saksbehandler = ?",
            (key[0], key[1], saksbehandler),
        )
        taken.add(key)
    return None


def export_assessments(saksbehandler: str | None = None, db_path: Path = DB_PATH) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    frame = list_assessments(saksbehandler, db_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    suffix = f"_{saksbehandler}" if saksbehandler else "_alle"
    path = EXPORT_DIR / f"vurderinger{suffix}_{stamp}.csv"
    frame.to_csv(path, index=False, sep=";", encoding="utf-8-sig")
    return path


def list_reviewer_records(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    def les() -> list[dict[str, Any]]:
        db = _db(db_path)
        rows = db.fetchall("SELECT navn, snowflake_bruker FROM " + db.table("reviewers"))
        return sorted(rows, key=lambda row: str(row.get("navn") or "").lower())

    return [dict(row) for row in _husk("reviewers:" + str(db_path), les)]


def list_reviewers(db_path: Path = DB_PATH) -> list[str]:
    return [str(row["navn"]) for row in list_reviewer_records(db_path)]


def add_reviewer(
    navn: str, db_path: Path = DB_PATH, snowflake_bruker: str | None = None
) -> str:
    name = " ".join(navn.split())
    if not name:
        raise ValueError("Navn kan ikke v\u00e6re tomt.")
    db = _db(db_path)
    table = db.table("reviewers")
    bruker = " ".join(str(snowflake_bruker or "").split())
    existing = db.fetchone(
        "SELECT navn FROM " + table + " WHERE navn = ?",
        (name,),
    )
    if existing:
        if snowflake_bruker is not None:
            _skriv(db,
                "UPDATE " + table + " SET snowflake_bruker = ? WHERE navn = ?",
                (bruker or None, name),
            )
        return "updated"
    _skriv(db,
        "INSERT INTO " + table + " (navn, created_at, snowflake_bruker) VALUES (?, ?, ?)",
        (name, _now_iso(), bruker or None),
    )
    return "added"


def remove_reviewer(navn: str, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    _skriv(db,
        "DELETE FROM " + db.table("reviewers") + " WHERE navn = ?",
        (navn,),
    )


def reviewer_progress(keys: list[SampleKey], db_path: Path = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    reviewers = list_reviewers(db_path)
    tildelt = _tildelt_til(db_path)
    current = set(keys)
    svart: dict[str, set[SampleKey]] = {}
    siste: dict[str, str] = {}
    for key, navn, tid in _svarnokler(db_path):
        if key in current:
            svart.setdefault(navn, set()).add(key)
        if tid > siste.get(navn, ""):
            siste[navn] = tid
    rows = []
    for name in reviewers:
        denom = len(claimable_sample_ids(name, keys, db_path, tildelt=tildelt))
        count = len(svart.get(name, set()))
        rows.append(
            {
                "saksbehandler": name,
                "tildelt": denom,
                "vurdert": count,
                "andel": (count / denom) if denom else 0,
                "siste_vurdering_fullfort": (
                    format_oslo(siste[name]) if siste.get(name) else ""
                ),
            }
        )
    return pd.DataFrame(rows)


def list_assignments(db_path: Path = DB_PATH) -> pd.DataFrame:
    def les() -> pd.DataFrame:
        db = _db(db_path)
        frame = db.frame(
            "SELECT kilde_id, stikkprove_nr, saksbehandler, assigned_at FROM "
            + db.table("assignments")
        )
        return _sort_sample_frame(frame)

    return _husk("assignments:" + str(db_path), les).copy()


def _tildelt_til(db_path: Path = DB_PATH) -> dict[SampleKey, set[str]]:
    """Hvem hver stikkproeve er tildelt. Tom betyr at ingenting er tildelt."""

    def les() -> dict[SampleKey, set[str]]:
        frame = list_assignments(db_path)
        allowed: dict[SampleKey, set[str]] = {}
        if frame.empty:
            return allowed
        for kilde_id, nr, navn in zip(
            frame["kilde_id"].astype(str),
            frame["stikkprove_nr"].astype(str),
            frame["saksbehandler"].astype(str),
        ):
            allowed.setdefault(_as_key(kilde_id, nr), set()).add(navn)
        return allowed

    return _husk("tildelt:" + str(db_path), les)


def assignment_labels(keys: list[SampleKey], db_path: Path = DB_PATH) -> dict[SampleKey, str]:
    grouped = _tildelt_til(db_path)
    labels: dict[SampleKey, str] = {}
    for key in keys:
        names = grouped.get(key, set())
        if not names:
            labels[key] = "Felles k\u00f8"
        elif ASSIGN_ALL in names:
            labels[key] = "Alle saksbehandlere"
        else:
            labels[key] = ", ".join(sorted(names))
    return labels


def claimable_sample_ids(
    saksbehandler: str,
    keys: list[SampleKey],
    db_path: Path = DB_PATH,
    tildelt: dict[SampleKey, set[str]] | None = None,
) -> list[SampleKey]:
    allowed = _tildelt_til(db_path) if tildelt is None else tildelt
    if not allowed:
        return list(keys)
    result: list[SampleKey] = []
    for key in keys:
        holders = allowed.get(key)
        if holders is None or ASSIGN_ALL in holders or saksbehandler in holders:
            result.append(key)
    return result


def remaining_breakdown(
    saksbehandler: str, keys: list[SampleKey], db_path: Path = DB_PATH
) -> tuple[int, int]:
    ferdig = completed_ids(db_path)
    allowed = _tildelt_til(db_path)
    hos_deg = 0
    felles = 0
    tom_tildeling = not allowed
    for key in keys:
        if key in ferdig:
            continue
        if tom_tildeling:
            felles += 1
            continue
        holders = allowed.get(key)
        if holders is None or ASSIGN_ALL in holders:
            felles += 1
        elif holders == {saksbehandler}:
            hos_deg += 1
        elif saksbehandler in holders:
            felles += 1
    return hos_deg, felles


def egen_kostatus(
    saksbehandler: str, keys: list[SampleKey], db_path: Path = DB_PATH
) -> dict[str, int]:
    """Fremdriften i saksbehandlerens egen ko, uten resten av tabellen.

    Koen er de stikkproevene vedkommende kan plukke: egne tildelinger, og det
    som ligger aapent for alle. Ferdige teller med uansett hvem som svarte, slik
    at maaleren naar enden akkurat naar koen er tom.
    """
    mine = set(claimable_sample_ids(saksbehandler, keys, db_path))
    ferdig = completed_ids(db_path)
    egne = {key for key, navn, _tid in _svarnokler(db_path) if navn == saksbehandler}
    return {
        "total": len(mine),
        "ferdig": len(mine & ferdig),
        "mine": len(mine & egne),
    }


def _per_kilde(items: list[SampleKey]) -> dict[str, list[str]]:
    grupper: dict[str, list[str]] = {}
    for kilde_id, sample_id in items:
        grupper.setdefault(kilde_id, []).append(sample_id)
    return grupper


def _i_biter(verdier: list[str], storrelse: int = 400):
    for i in range(0, len(verdier), storrelse):
        yield verdier[i : i + storrelse]


def set_assignments(
    keys: list[SampleKey], assignees: list[str], db_path: Path = DB_PATH
) -> None:
    """Tildeler mange stikkproever med faa sporringer.

    En setning per kilde i stedet for tre per stikkproeve. Det utgjor forskjellen
    mellom noen faa og flere hundre runder mot databasen.
    """
    items = [_normalize_key(item) for item in keys if _normalize_key(item)[1].strip()]
    names = [" ".join(str(name).split()) for name in assignees if str(name).strip()]
    if ASSIGN_ALL in names:
        names = [ASSIGN_ALL]
    if not items:
        return
    db = _db(db_path)
    table = db.table("assignments")
    claims = db.table("claims")
    now = _now_iso()
    for kilde_id, numre in _per_kilde(items).items():
        for bit in _i_biter(numre):
            hull = ", ".join(["?"] * len(bit))
            _skriv(db,
                "DELETE FROM "
                + table
                + " WHERE kilde_id = ? AND stikkprove_nr IN ("
                + hull
                + ")",
                [kilde_id] + bit,
            )
            if names and ASSIGN_ALL not in names:
                navnehull = ", ".join(["?"] * len(names))
                _skriv(db,
                    "DELETE FROM "
                    + claims
                    + " WHERE kilde_id = ? AND stikkprove_nr IN ("
                    + hull
                    + ") AND saksbehandler NOT IN ("
                    + navnehull
                    + ")",
                    [kilde_id] + bit + names,
                )
    if names:
        _skriv_mange(db,
            table,
            ("kilde_id", "stikkprove_nr", "saksbehandler", "assigned_at"),
            [
                (kilde_id, sample_id, name, now)
                for kilde_id, sample_id in items
                for name in names
            ],
        )


def list_claims(db_path: Path = DB_PATH) -> dict[SampleKey, str]:
    _expire_claims(db_path)
    db = _db(db_path)
    rows = db.fetchall(
        "SELECT kilde_id, stikkprove_nr, saksbehandler FROM " + db.table("claims")
    )
    return {
        _as_key(row["kilde_id"], row["stikkprove_nr"]): str(row["saksbehandler"])
        for row in rows
    }


def log_admin_event(tekst: str, db_path: Path = DB_PATH) -> None:
    message = " ".join(str(tekst).split())
    if not message:
        return
    _legg_til_verdi(LOGG_NAVN, message, db_path, presis_tid=True)


def list_admin_events(limit: int = 8, db_path: Path = DB_PATH) -> list[dict[str, str]]:
    db = _db(db_path)
    safe_limit = max(int(limit), 0)
    rows = db.fetchall(
        "SELECT verdi, updated_at FROM "
        + db.table("settings")
        + " WHERE navn = ? ORDER BY updated_at DESC LIMIT "
        + str(safe_limit),
        (LOGG_NAVN,),
    )
    return [
        {"happened_at": str(row["updated_at"]), "tekst": str(row["verdi"])}
        for row in rows
    ]


LOGG_TILBAKESKRIVING = "ble lagret, men ikke skrevet tilbake til kildetabellen"
SETT_TILBAKESKRIVING = "tilbakeskriving_sett"


def writeback_failures(db_path: Path = DB_PATH) -> list[dict[str, str]]:
    """Svar som ikke naadde kildetabellen, og som ingen har kvittert ut.

    Saksbehandleren faar bare beskjed om at svaret er lagret, saa uten denne
    listen blir feilen staaende i endringsloggen uten at noen leser den.
    Tidsstemplene er ISO-tekst, saa de kan sammenlignes som de er.
    """
    sett = get_setting(SETT_TILBAKESKRIVING, "", db_path)
    return [
        hendelse
        for hendelse in list_admin_events(200, db_path)
        if LOGG_TILBAKESKRIVING in hendelse["tekst"]
        and hendelse["happened_at"] > sett
    ]


def kvitter_writeback_failures(db_path: Path = DB_PATH) -> None:
    """Merker dagens feil som sett, uten aa skjule nye som kommer etterpaa."""
    hendelser = writeback_failures(db_path)
    if hendelser:
        set_setting(SETT_TILBAKESKRIVING, hendelser[0]["happened_at"], db_path)


def grunnlag_tildeling_status(keys: list[SampleKey], db_path: Path = DB_PATH) -> str:
    if not keys:
        return "Ingen stikkpr\u00f8ver i kilden"
    labels = assignment_labels(keys, db_path)
    unique = {labels[key] for key in keys}
    if unique == {"Felles k\u00f8"}:
        return "Ikke tildelt (felles k\u00f8)"
    if len(unique) == 1:
        return next(iter(unique))
    return "Blandet tildeling"


def source_queue_status(
    keys: list[SampleKey], db_path: Path = DB_PATH
) -> dict[str, Any]:
    items = list(keys)
    ferdig_set = completed_ids(db_path) & set(items)
    claims = list_claims(db_path)
    last_counts: dict[str, int] = {}
    last_n = 0
    for key in items:
        if key in ferdig_set:
            continue
        holder = claims.get(key)
        if holder:
            last_n += 1
            last_counts[holder] = last_counts.get(holder, 0) + 1
    last_hos = ", ".join(
        name + (" (" + str(n) + ")" if n > 1 else "")
        for name, n in sorted(last_counts.items())
    )
    antall = len(items)
    ferdig = len(ferdig_set)
    return {
        "tildelt": grunnlag_tildeling_status(items, db_path) if items else "\u2014",
        "antall": antall,
        "ferdig": ferdig,
        "gjenstar": max(antall - ferdig, 0),
        "andel": (ferdig / antall) if antall else 0.0,
        "last": last_n,
        "last_hos": last_hos,
    }


_SOURCE_COLUMNS = (
    "source_id, name, kind, path, original_name, active, created_at, url, file_updated_at"
)


def list_sources(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    def les() -> list[dict[str, Any]]:
        db = _db(db_path)
        rows = db.fetchall("SELECT " + _SOURCE_COLUMNS + " FROM " + db.table("sources"))
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("created_at") or ""),
                str(row.get("name") or "").lower(),
            ),
        )

    return [dict(row) for row in _husk("sources:" + str(db_path), les)]


def list_active_sources(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    return [src for src in list_sources(db_path) if int(src.get("active") or 0) == 1]


def get_source(source_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    db = _db(db_path)
    return db.fetchone(
        "SELECT "
        + _SOURCE_COLUMNS
        + " FROM "
        + db.table("sources")
        + " WHERE source_id = ?",
        (str(source_id),),
    )


def add_source(
    name: str,
    kind: str,
    path: str | None = None,
    original_name: str | None = None,
    active: bool = True,
    url: str | None = None,
    db_path: Path = DB_PATH,
) -> str:
    title = " ".join(str(name).split())
    if not title:
        raise ValueError("Navn p\u00e5 grunnlaget kan ikke v\u00e6re tomt.")
    kind_key = str(kind).strip().lower()
    if kind_key not in {"file", "snowflake"}:
        raise ValueError("Ukjent kildetype.")
    db = _db(db_path)
    if kind_key == "snowflake":
        for src in list_sources(db_path):
            if src["kind"] == "snowflake":
                raise ValueError("Snowflake er allerede lagt til som grunnlag.")
    source_id = uuid.uuid4().hex
    _skriv(db,
        "INSERT INTO "
        + db.table("sources")
        + " (source_id, name, kind, path, original_name, active, created_at, url) "
        + "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id,
            title,
            kind_key,
            str(path) if path else None,
            original_name or "",
            1 if active else 0,
            _now_iso(),
            (str(url).strip() or None) if url else None,
        ),
    )
    return source_id


def set_source_active(source_id: str, active: bool, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    _skriv(db,
        "UPDATE " + db.table("sources") + " SET active = ? WHERE source_id = ?",
        (1 if active else 0, str(source_id)),
    )


def update_source_file(
    source_id: str,
    path: str,
    original_name: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    db = _db(db_path)
    _skriv(db,
        "UPDATE "
        + db.table("sources")
        + " SET path = ?, original_name = COALESCE(?, original_name), file_updated_at = ? "
        + "WHERE source_id = ?",
        (str(path) if path else None, original_name, _now_iso(), str(source_id)),
    )


def count_source_assessments(source_id: str, db_path: Path = DB_PATH) -> int:
    db = _db(db_path)
    row = db.fetchone(
        "SELECT COUNT(*) AS n FROM "
        + db.table("assessments")
        + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    return int(row["n"] if row else 0)


def clear_source_claims(source_id: str, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    _skriv(db,
        "DELETE FROM " + db.table("claims") + " WHERE kilde_id = ?",
        (str(source_id),),
    )


def clear_source_assessments(source_id: str, db_path: Path = DB_PATH) -> int:
    db = _db(db_path)
    row = db.fetchone(
        "SELECT COUNT(*) AS n FROM "
        + db.table("assessments")
        + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    n = int(row["n"] if row else 0)
    _skriv(db,
        "DELETE FROM " + db.table("assessments") + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    _skriv(db,
        "DELETE FROM " + db.table("claims") + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    return n


def update_source_url(source_id: str, url: str | None, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    text = " ".join(str(url or "").split())
    _skriv(db,
        "UPDATE " + db.table("sources") + " SET url = ? WHERE source_id = ?",
        (text or None, str(source_id)),
    )


def rename_source(source_id: str, name: str, db_path: Path = DB_PATH) -> None:
    title = " ".join(str(name).split())
    if not title:
        raise ValueError("Navn p\u00e5 grunnlaget kan ikke v\u00e6re tomt.")
    db = _db(db_path)
    _skriv(db,
        "UPDATE " + db.table("sources") + " SET name = ? WHERE source_id = ?",
        (title, str(source_id)),
    )


def remove_source(source_id: str, db_path: Path = DB_PATH) -> None:
    src = get_source(source_id, db_path)
    if src is None:
        return
    db = _db(db_path)
    _skriv(db,
        "DELETE FROM " + db.table("source_files") + " WHERE source_id = ?",
        (str(source_id),),
    )
    _skriv(db,
        "DELETE FROM " + db.table("sources") + " WHERE source_id = ?",
        (str(source_id),),
    )
    _skriv(db,
        "DELETE FROM " + db.table("assignments") + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    _skriv(db,
        "DELETE FROM " + db.table("claims") + " WHERE kilde_id = ?",
        (str(source_id),),
    )
    path_text = src.get("path") or ""
    if path_text:
        path = Path(path_text)
        try:
            if path.exists() and SOURCES_DIR.resolve() in path.resolve().parents:
                path.unlink()
        except OSError:
            pass


def reattach_empty_kilde(source_id: str, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    target = str(source_id)
    for table in ("assessments", "claims", "assignments"):
        _skriv(db,
            "UPDATE "
            + db.table(table)
            + " SET kilde_id = ? WHERE kilde_id = '' OR kilde_id IS NULL",
            (target,),
        )


def save_source_file(
    source_id: str, filename: str, data: bytes, db_path: Path = DB_PATH
) -> str:
    if not data:
        raise ValueError("Filen er tom.")
    if len(data) > 12_000_000:
        raise ValueError("Filen er for stor til \u00e5 lagres (maks 12 MB).")
    db = _db(db_path)
    encoded = base64.b64encode(data).decode("ascii")
    now = _now_iso()
    files = db.table("source_files")
    _skriv(db, "DELETE FROM " + files + " WHERE source_id = ?", (str(source_id),))
    _skriv(db,
        "INSERT INTO "
        + files
        + " (source_id, filename, content_b64, updated_at) VALUES (?, ?, ?, ?)",
        (str(source_id), filename, encoded, now),
    )
    stored_path = ""
    if db.kind == "sqlite" and Path(db_path) == Path(DB_PATH):
        SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            suffix = ".csv"
        dest = SOURCES_DIR / (str(source_id) + suffix)
        dest.write_bytes(data)
        stored_path = str(dest)
    update_source_file(source_id, stored_path, filename, db_path=db_path)
    return stored_path


def read_source_bytes(source: dict[str, Any], db_path: Path = DB_PATH) -> tuple[bytes, str]:
    source_id = str(source.get("source_id") or "")
    db = _db(db_path)
    row = db.fetchone(
        "SELECT filename, content_b64 FROM "
        + db.table("source_files")
        + " WHERE source_id = ?",
        (source_id,),
    )
    if row and row.get("content_b64"):
        name = str(row.get("filename") or source.get("original_name") or "grunnlag.csv")
        return base64.b64decode(str(row["content_b64"])), name
    path_text = str(source.get("path") or "")
    if path_text:
        path = Path(path_text)
        if path.exists() and path.is_file():
            return path.read_bytes(), path.name
    raise FileNotFoundError(
        "Fant ikke filen for " + str(source.get("name") or "grunnlaget") + "."
    )


def _legg_til_verdi(
    navn: str, verdi: str, db_path: Path = DB_PATH, presis_tid: bool = False
) -> None:
    db = _db(db_path)
    tid = (
        datetime.now(timezone.utc).isoformat()
        if presis_tid
        else _now_iso()
    )
    _skriv(db,
        "INSERT INTO " + db.table("settings") + " (navn, verdi, updated_at) VALUES (?, ?, ?)",
        (navn, verdi, tid),
    )


def _verdier(navn: str, db_path: Path = DB_PATH) -> list[str]:
    def les() -> list[str]:
        db = _db(db_path)
        rows = db.fetchall(
            "SELECT verdi FROM " + db.table("settings") + " WHERE navn = ? ORDER BY verdi",
            (navn,),
        )
        return [str(row["verdi"]) for row in rows if row.get("verdi")]

    return list(_husk("verdier:" + str(navn) + ":" + str(db_path), les))


def list_admin_logins(db_path: Path = DB_PATH) -> list[str]:
    return _verdier(ADMIN_NAVN, db_path)


def add_admin(login: str, db_path: Path = DB_PATH) -> None:
    name = " ".join(str(login).split())
    if not name:
        return
    if any(item.lower() == name.lower() for item in list_admin_logins(db_path)):
        return
    _legg_til_verdi(ADMIN_NAVN, name, db_path)


def get_setting(navn: str, default: str = "", db_path: Path = DB_PATH) -> str:
    def les() -> str:
        db = _db(db_path)
        row = db.fetchone(
            "SELECT verdi FROM " + db.table("settings") + " WHERE navn = ?",
            (str(navn),),
        )
        if row is None:
            return ""
        return str(row.get("verdi") or "").strip()

    return _husk("setting:" + str(navn) + ":" + str(db_path), les) or default


def set_setting(navn: str, verdi: str, db_path: Path = DB_PATH) -> None:
    db = _db(db_path)
    table = db.table("settings")
    text = str(verdi or "").strip()
    _skriv(db, "DELETE FROM " + table + " WHERE navn = ?", (str(navn),))
    if not text:
        return
    _skriv(db,
        "INSERT INTO " + table + " (navn, verdi, updated_at) VALUES (?, ?, ?)",
        (str(navn), text, _now_iso()),
    )


def sources_cache_key(db_path: Path = DB_PATH) -> str:
    parts = []
    for src in list_sources(db_path):
        stamp = str(src.get("file_updated_at") or "")
        path_text = src.get("path") or ""
        if not stamp and path_text:
            path = Path(str(path_text))
            if path.exists():
                stamp = str(int(path.stat().st_mtime))
        parts.append(
            str(src["source_id"])
            + ":"
            + str(src.get("active"))
            + ":"
            + str(src.get("kind"))
            + ":"
            + (stamp or "0")
        )
    return ";".join(parts) or "empty"


def counted_in_keys(answers: pd.DataFrame, keys: list[SampleKey]) -> int:
    if answers is None or answers.empty or not keys:
        return 0
    wanted = set(keys)
    return len(_frame_keys(answers) & wanted)
