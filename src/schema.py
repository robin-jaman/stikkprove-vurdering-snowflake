from __future__ import annotations

ASSESSMENT_FIELDS = (
    "kilde_id",
    "stikkprove_nr",
    "saksbehandler",
    "varselkode",
    "handling",
    "handling_annet",
    "begrunnelse",
    "vanlighet",
    "unntak_forklaring",
    "periode_spesielt",
    "historisk_korrekt",
    "kommentar",
    "updated_at",
    "kilde",
)

ASSESSMENT_KEY_FIELDS = ("kilde_id", "stikkprove_nr", "saksbehandler")
ASSESSMENT_NOT_NULL = frozenset(
    {"kilde_id", "stikkprove_nr", "saksbehandler", "updated_at"}
)
LEFTOVER_ASSESSMENT_FIELDS = (
    "sikkerhet",
    "kan_automatiseres",
    "signaler",
    "regelverk_ref",
)


def snowflake_column(field: str) -> str:
    return field.upper()


def sqlite_column_sql(field: str) -> str:
    if field == "kilde_id":
        return "kilde_id TEXT NOT NULL DEFAULT ''"
    if field in ASSESSMENT_NOT_NULL:
        return field + " TEXT NOT NULL"
    return field + " TEXT"


def sqlite_assessments_create_sql() -> str:
    lines = [sqlite_column_sql(field) for field in ASSESSMENT_FIELDS]
    lines.append(
        "PRIMARY KEY (" + ", ".join(ASSESSMENT_KEY_FIELDS) + ")"
    )
    return (
        "CREATE TABLE assessments (\n                "
        + ",\n                ".join(lines)
        + "\n            )"
    )


def sqlite_assessments_copy_sql(*, kilde_id_expr: str | None = None) -> str:
    insert_cols = ", ".join(ASSESSMENT_FIELDS)
    select_cols = ", ".join(
        kilde_id_expr
        if field == "kilde_id" and kilde_id_expr is not None
        else field
        for field in ASSESSMENT_FIELDS
    )
    return (
        "INSERT INTO assessments (\n                "
        + insert_cols
        + "\n            )\n            SELECT\n                "
        + select_cols
        + "\n            FROM assessments"
    )


def snowflake_column_sql(field: str) -> str:
    col = snowflake_column(field)
    if field == "kilde_id":
        return col + " VARCHAR NOT NULL DEFAULT ''"
    if field in ASSESSMENT_NOT_NULL:
        return col + " VARCHAR NOT NULL"
    return col + " VARCHAR"


def snowflake_create_sql(table: str) -> str:
    lines = [snowflake_column_sql(field) for field in ASSESSMENT_FIELDS]
    lines.append(
        "PRIMARY KEY ("
        + ", ".join(snowflake_column(field) for field in ASSESSMENT_KEY_FIELDS)
        + ")"
    )
    return (
        "CREATE TABLE IF NOT EXISTS "
        + table
        + " (\n  "
        + ",\n  ".join(lines)
        + "\n)"
    )


def snowflake_add_column_sql(table: str, field: str) -> str:
    col = snowflake_column(field)
    if field in ASSESSMENT_NOT_NULL:
        return (
            "ALTER TABLE "
            + table
            + " ADD COLUMN IF NOT EXISTS "
            + col
            + " VARCHAR NOT NULL DEFAULT ''"
        )
    return (
        "ALTER TABLE "
        + table
        + " ADD COLUMN IF NOT EXISTS "
        + col
        + " VARCHAR"
    )


def plan_table_sync(existing_columns: list[str] | tuple[str, ...]) -> tuple[list[str], list[str]]:
    have = {str(name).strip().strip('"').upper() for name in existing_columns}
    add = [
        field
        for field in ASSESSMENT_FIELDS
        if snowflake_column(field) not in have
    ]
    drop = [
        field
        for field in LEFTOVER_ASSESSMENT_FIELDS
        if snowflake_column(field) in have
    ]
    return add, drop
