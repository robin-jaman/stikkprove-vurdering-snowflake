from __future__ import annotations

import os
import re
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from src.config import DB_PATH
from src.schema import snowflake_create_sql

_PREFIX_DEFAULT = "STIKKPROVE_"

# Hvor mange rader eller verdier som sendes i en og samme setning.
_BIT = 400

# Schemaet appens egne tabeller skal ligge i. Tomt betyr samme schema som
# appen kjorer i. Fullt navn gjor at appen kan ligge et annet sted enn
# tabellene sine, for eksempel i samme schema som kildetabellen.
_SCHEMA_DEFAULT = "TEST.DATAFORVALTNING_STAGING"

_backend_cache: str | None = None
_sf_conn: Any = None
_sqlite_conns: dict[tuple[int, str], sqlite3.Connection] = {}


def _sqlite_conn(path: Path) -> sqlite3.Connection:
    """Gjenbruker tilkoblingen, en per trad og fil.

    Streamlit kjorer hver okt i sin egen trad, og sqlite-tilkoblinger kan ikke
    deles mellom trader.
    """
    key = (threading.get_ident(), str(path))
    conn = _sqlite_conns.get(key)
    if conn is not None:
        return conn
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    _sqlite_conns[key] = conn
    return conn


def close_sqlite_connections() -> None:
    """Lukker alle bufrede tilkoblinger, slik at filen kan slettes."""
    for conn in list(_sqlite_conns.values()):
        try:
            conn.close()
        except Exception:
            pass
    _sqlite_conns.clear()


def table_prefix() -> str:
    raw = os.getenv("STIKKPROVE_TABLE_PREFIX", _PREFIX_DEFAULT)
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    if not cleaned:
        cleaned = _PREFIX_DEFAULT
    if not cleaned.endswith("_"):
        cleaned += "_"
    return cleaned.upper()


def table_schema() -> str:
    raw = os.getenv("STIKKPROVE_TABLE_SCHEMA", _SCHEMA_DEFAULT)
    cleaned = "".join(ch for ch in str(raw) if ch.isalnum() or ch in "_.")
    return cleaned.strip(".").upper()


def qualified(name: str) -> str:
    """Fullt tabellnavn, med schema foran hvis det er satt."""
    schema = table_schema()
    navn = table_prefix() + name.upper()
    return schema + "." + navn if schema else navn


def _active_session() -> Any | None:
    try:
        from snowflake.snowpark.context import get_active_session
    except Exception:
        return None
    try:
        return get_active_session()
    except Exception:
        return None


def backend_name() -> str:
    global _backend_cache
    if _backend_cache:
        return _backend_cache
    choice = os.getenv("STIKKPROVE_BACKEND", "auto").strip().lower()
    if choice in {"sqlite", "snowflake"}:
        _backend_cache = choice
        return choice
    if _active_session() is not None:
        _backend_cache = "snowflake"
        return _backend_cache
    _backend_cache = "sqlite"
    return _backend_cache


def uses_snowflake_storage(db_path: Path | None = None) -> bool:
    return get_db(db_path).kind == "snowflake"


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _rows_frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


class SqliteDb:
    kind = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def table(self, name: str) -> str:
        return name

    def _connect(self) -> sqlite3.Connection:
        return _sqlite_conn(self.path)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(sql, tuple(params or ()))
            conn.commit()
            return int(cur.rowcount or 0)
        except Exception:
            conn.rollback()
            raise

    def insert_many(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        if not rows:
            return
        conn = self._connect()
        sql = (
            "INSERT INTO "
            + table
            + " ("
            + ", ".join(columns)
            + ") VALUES ("
            + ", ".join(["?"] * len(columns))
            + ")"
        )
        try:
            conn.executemany(sql, [tuple(row) for row in rows])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _fetch(
        self, sql: str, params: Sequence[Any] | None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        conn = self._connect()
        cur = conn.execute(sql, tuple(params or ()))
        columns = [str(item[0]) for item in cur.description or []]
        rows = [{col: _plain(row[col]) for col in columns} for row in cur.fetchall()]
        return columns, rows

    def fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        _columns, rows = self._fetch(sql, params)
        return rows

    def fetchone(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        rows = self.fetchall(sql, params)
        return rows[0] if rows else None

    def frame(self, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
        columns, rows = self._fetch(sql, params)
        return _rows_frame(rows, columns)

    def ensure_schema(self) -> None:
        return None


class SnowflakeDb:
    kind = "snowflake"
    _ready = False

    def table(self, name: str) -> str:
        return qualified(name)

    def ensure_schema(self) -> None:
        """Oppretter tabellene appen trenger.

        Mangler rollen CREATE TABLE, gaar det likevel bra saa lenge noen andre
        har opprettet dem, for eksempel med snowflake_tabeller.sql.
        """
        if SnowflakeDb._ready:
            return
        mangler: list[str] = []
        for statement in snowflake_schema_sql():
            treff = re.search(r"IF NOT EXISTS ([\w.]+)", statement)
            navn = treff.group(1) if treff else ""
            try:
                self.execute(statement)
            except Exception:
                if not navn or not self._kan_brukes(navn):
                    mangler.append(navn or "ukjent tabell")
        if mangler:
            raise RuntimeError(
                "Appen mangler disse tabellene og fikk ikke opprettet dem: "
                + ", ".join(mangler)
                + ". Sjekk at schemaet "
                + (table_schema() or "appen kj\u00f8rer i")
                + " finnes, og at rollen appen kj\u00f8rer som har CREATE TABLE der. "
                + "Alternativt m\u00e5 noen med rettigheter kj\u00f8re snowflake_tabeller.sql "
                + "og gi rollen lese- og skrivetilgang til tabellene."
            )
        SnowflakeDb._ready = True

    def _kan_brukes(self, navn: str) -> bool:
        """Sant hvis tabellen finnes og appen faktisk faar lese fra den."""
        try:
            self._run("SELECT * FROM " + navn + " LIMIT 0", None, fetch=True)
        except Exception:
            return False
        return True

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        self._run(sql, params, fetch=False)
        return -1

    def insert_many(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        """Setter inn mange rader med faa sporringer.

        Hver sporring er en runde mot warehouset, saa her teller antallet mer enn
        lengden paa setningen.
        """
        if not rows:
            return
        en_rad = "(" + ", ".join(["?"] * len(columns)) + ")"
        start = "INSERT INTO " + table + " (" + ", ".join(columns) + ") VALUES "
        for i in range(0, len(rows), _BIT):
            bit = rows[i : i + _BIT]
            params = [verdi for rad in bit for verdi in rad]
            self.execute(start + ", ".join([en_rad] * len(bit)), params)

    def fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        _columns, rows = self._run(sql, params, fetch=True)
        return rows

    def fetchone(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        rows = self.fetchall(sql, params)
        return rows[0] if rows else None

    def frame(self, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
        columns, rows = self._run(sql, params, fetch=True)
        return _rows_frame(rows, columns)

    def _run(
        self, sql: str, params: Sequence[Any] | None, fetch: bool
    ) -> tuple[list[str], list[dict[str, Any]]]:
        session = _active_session()
        if session is not None:
            return _run_snowpark(session, sql, params, fetch)
        return _run_connector(sql, params, fetch)


def snowflake_schema_sql() -> list[str]:
    schema = table_schema()
    prefix = (schema + "." if schema else "") + table_prefix()
    statements = [snowflake_create_sql(prefix + "ASSESSMENTS")]
    statements.extend(
        [
            (
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "REVIEWERS (\n"
                "  NAVN VARCHAR NOT NULL,\n"
                "  CREATED_AT VARCHAR NOT NULL,\n"
                "  SNOWFLAKE_BRUKER VARCHAR\n"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "CLAIMS (\n"
                "  KILDE_ID VARCHAR NOT NULL DEFAULT '',\n"
                "  STIKKPROVE_NR VARCHAR NOT NULL,\n"
                "  SAKSBEHANDLER VARCHAR NOT NULL,\n"
                "  CLAIMED_AT VARCHAR NOT NULL,\n"
                "  OPENED_AT VARCHAR\n"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "ASSIGNMENTS (\n"
                "  KILDE_ID VARCHAR NOT NULL DEFAULT '',\n"
                "  STIKKPROVE_NR VARCHAR NOT NULL,\n"
                "  SAKSBEHANDLER VARCHAR NOT NULL,\n"
                "  ASSIGNED_AT VARCHAR NOT NULL\n"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "SOURCES (\n"
                "  SOURCE_ID VARCHAR NOT NULL,\n"
                "  NAME VARCHAR NOT NULL,\n"
                "  KIND VARCHAR NOT NULL,\n"
                "  PATH VARCHAR,\n"
                "  ORIGINAL_NAME VARCHAR,\n"
                "  ACTIVE NUMBER NOT NULL DEFAULT 1,\n"
                "  CREATED_AT VARCHAR NOT NULL,\n"
                "  URL VARCHAR,\n"
                "  FILE_UPDATED_AT VARCHAR\n"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "SOURCE_FILES (\n"
                "  SOURCE_ID VARCHAR NOT NULL,\n"
                "  FILENAME VARCHAR,\n"
                "  CONTENT_B64 VARCHAR NOT NULL,\n"
                "  UPDATED_AT VARCHAR NOT NULL\n"
                ")"
            ),
            (
                # Rommer ogsaa administratorer og endringslogg, som egne navn.
                "CREATE TABLE IF NOT EXISTS "
                + prefix
                + "SETTINGS (\n"
                "  NAVN VARCHAR NOT NULL,\n"
                "  VERDI VARCHAR,\n"
                "  UPDATED_AT VARCHAR NOT NULL\n"
                ")"
            ),
        ]
    )
    return statements


def _run_snowpark(
    session: Any, sql: str, params: Sequence[Any] | None, fetch: bool
) -> tuple[list[str], list[dict[str, Any]]]:
    bound = list(params or [])
    if bound:
        df = session.sql(sql, params=bound)
    else:
        df = session.sql(sql)
    if not fetch:
        df.collect()
        return [], []
    fields = [str(field.name) for field in df.schema.fields]
    collected = df.collect()
    columns = [name.lower() for name in fields] or []
    rows: list[dict[str, Any]] = []
    for item in collected:
        values = list(item)
        if not columns:
            columns = [str(key).lower() for key in item.as_dict().keys()]
            values = list(item.as_dict().values())
        rows.append({col: _plain(val) for col, val in zip(columns, values)})
    return columns, rows


def _env_ready() -> bool:
    required = [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
    ]
    return all(os.getenv(name) for name in required)


def _connector_conn() -> Any:
    global _sf_conn
    if _sf_conn is not None:
        return _sf_conn
    if not _env_ready():
        raise RuntimeError(
            "Mangler Snowflake-variabler: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
            "SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE"
        )
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError(
            "snowflake-connector-python er ikke installert. "
            "Kj\u00f8r: pip install snowflake-connector-python"
        ) from exc
    _sf_conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "snowflake"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )
    return _sf_conn


def _run_connector(
    sql: str, params: Sequence[Any] | None, fetch: bool
) -> tuple[list[str], list[dict[str, Any]]]:
    conn = _connector_conn()
    cur = conn.cursor()
    try:
        bound = tuple(params or ())
        statement = sql.replace("?", "%s") if bound else sql
        if bound:
            cur.execute(statement, bound)
        else:
            cur.execute(statement)
        if not fetch:
            conn.commit()
            return [], []
        columns = [str(item[0]).lower() for item in cur.description or []]
        rows = [
            {col: _plain(val) for col, val in zip(columns, row)}
            for row in cur.fetchall()
        ]
        conn.commit()
        return columns, rows
    finally:
        cur.close()


def get_db(db_path: Path | None = None) -> SqliteDb | SnowflakeDb:
    path = Path(db_path) if db_path is not None else DB_PATH
    if path != Path(DB_PATH):
        return SqliteDb(path)
    if backend_name() == "snowflake":
        return SnowflakeDb()
    return SqliteDb(path)


def exec_snowflake(sql: str, params: Sequence[Any] | None = None) -> None:
    """Kj\u00f8rer en setning mot Snowflake, uavhengig av hvilken lagring appen bruker."""
    session = _active_session()
    if session is not None:
        _run_snowpark(session, sql, params, False)
        return
    _run_connector(sql, params, False)


def _uten_hermetegn(navn: str) -> str:
    tekst = str(navn)
    if len(tekst) > 1 and tekst.startswith('"') and tekst.endswith('"'):
        return tekst[1:-1].replace('""', '"')
    return tekst


def snowflake_column_names(sql: str) -> list[str]:
    """Kolonnenavnene i en sporring, slik de faktisk heter i Snowflake.

    query_snowflake_frame gjor navnene om til sma bokstaver, og Snowpark legger
    hermetegn rundt navn som ikke er rent store. Et navn som har vaert igjennom
    noen av delene duger ikke i en UPDATE, saa det maa hentes uroert her.
    """
    session = _active_session()
    if session is not None:
        return [
            _uten_hermetegn(field.name) for field in session.sql(sql).schema.fields
        ]
    conn = _connector_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return [str(item[0]) for item in cur.description or []]
    finally:
        cur.close()


def query_snowflake_frame(sql: str) -> pd.DataFrame:
    session = _active_session()
    if session is not None:
        columns, rows = _run_snowpark(session, sql, None, True)
        return _rows_frame(rows, columns)
    columns, rows = _run_connector(sql, None, True)
    return _rows_frame(rows, columns)
