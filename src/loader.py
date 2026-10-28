from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import pandas as pd

from src.config import (
    DEFAULT_FILE_CANDIDATES,
    QUESTION_COLUMNS,
    SAMPLE_ID_COL,
)
from src.formatting import is_empty


def resolve_sample_file(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(path for path in DEFAULT_FILE_CANDIDATES if str(path).strip())

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    searched = "\n".join(f"  - {path}" for path in candidates if str(path).strip())
    raise FileNotFoundError(
        "Fant ingen stikkpr\u00f8vefil. Last opp CSV/Excel under Administrasjon, "
        "eller legg en fil i data/.\nS\u00f8kte i:\n" + searched
    )


CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(
                path,
                sep=";",
                decimal=",",
                dtype=object,
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Klarte ikke \u00e5 lese {path} som tekstfil.") from last_error


def _read_tabular(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, dtype=object)
    return _read_csv(path)


def _read_tabular_bytes(data: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    buffer = BytesIO(data)
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(buffer, dtype=object)
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            buffer.seek(0)
            return pd.read_csv(
                buffer,
                sep=";",
                decimal=",",
                dtype=object,
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError("Klarte ikke \u00e5 lese " + filename + " som tekstfil.") from last_error


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    from src.kolonner import oversett

    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    return oversett(df)


def _question_column_names(df: pd.DataFrame) -> list[str]:
    """Svarkolonnene i grunnlaget, uansett om de heter SAERLIGE_FORHOLD
    eller baerer selve sporsmaalsteksten slik gamle regneark gjorde."""
    from src.kolonner import SVAR_TIL_KOLONNE, forenkle

    kjent = {forenkle(navn) for navn in SVAR_TIL_KOLONNE.values()}
    kjent.update(forenkle(navn) for navn in QUESTION_COLUMNS.values())
    names: list[str] = []
    for col in df.columns:
        if forenkle(col) in kjent or str(col).startswith(
            tuple(f"{i}." for i in range(1, 10))
        ):
            names.append(str(col))
    return names


def has_reference_answer(row: pd.Series, question_cols: list[str]) -> bool:
    return any(not is_empty(row.get(col)) for col in question_cols)


def prepare_samples(df: pd.DataFrame) -> pd.DataFrame:
    df = _normalize_columns(df)
    if SAMPLE_ID_COL not in df.columns:
        funnet = ", ".join(str(col) for col in list(df.columns)[:15])
        raise ValueError(
            "Grunnlaget mangler kolonnen '"
            + SAMPLE_ID_COL
            + "'. Appen fant disse kolonnene: "
            + (funnet or "ingen")
        )

    question_cols = _question_column_names(df)
    df[SAMPLE_ID_COL] = df[SAMPLE_ID_COL].astype(str).str.strip()
    df = df[df[SAMPLE_ID_COL].ne("") & df[SAMPLE_ID_COL].ne("nan")].copy()
    df["har_referansevurdering"] = df.apply(
        lambda row: has_reference_answer(row, question_cols), axis=1
    )
    if "varselkode" in df.columns:
        df["varselkode"] = df["varselkode"].astype(str).str.strip()
    if "aksjon_dt" in df.columns:
        df["aksjon_aar"] = pd.to_datetime(df["aksjon_dt"], errors="coerce").dt.year
    return df.reset_index(drop=True)


def load_samples(path: str | Path | None = None) -> tuple[pd.DataFrame, Path]:
    file_path = resolve_sample_file(path)
    df = prepare_samples(_read_tabular(file_path))
    return df, file_path


def load_active_samples() -> tuple[pd.DataFrame, str]:
    frame, warnings = load_all_active_samples()
    if warnings:
        label = "; ".join(warnings)
    elif frame.empty:
        label = ""
    else:
        names = sorted({str(item) for item in frame["_kilde_navn"].astype(str)})
        label = ", ".join(names)
    return frame, label


def ensure_default_sources() -> None:
    """Snowflake-tabellen er eneste grunnlag, og registreres ved forste oppstart."""
    from src.store import add_source, list_sources, reattach_empty_kilde

    if list_sources():
        return
    source_id = add_source("Snowflake", "snowflake")
    reattach_empty_kilde(source_id)


def load_source_frame(source: dict) -> pd.DataFrame:
    kind = str(source.get("kind") or "")
    if kind == "snowflake":
        from src.snowflake_client import load_samples as load_snowflake

        frame = prepare_samples(load_snowflake())
    else:
        from src.store import read_source_bytes

        data, filename = read_source_bytes(source)
        frame = prepare_samples(_read_tabular_bytes(data, filename))
    frame = frame.copy()
    frame["_kilde_id"] = str(source["source_id"])
    frame["_kilde_navn"] = str(source.get("name") or "")
    frame["_kilde_kind"] = kind
    return frame.drop_duplicates(subset=["_kilde_id", SAMPLE_ID_COL], keep="first")


def load_all_active_samples() -> tuple[pd.DataFrame, list[str]]:
    from src.store import list_active_sources

    ensure_default_sources()
    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    for source in list_active_sources():
        try:
            frames.append(load_source_frame(source))
        except Exception as exc:
            warnings.append(str(source.get("name") or source["source_id"]) + ": " + str(exc))
    if not frames:
        return pd.DataFrame(), warnings
    return pd.concat(frames, ignore_index=True), warnings


def reference_answers(row: pd.Series) -> dict[str, str]:
    """Svarene som allerede staar i grunnlaget, felt for felt."""
    from src.kolonner import SVAR_TIL_KOLONNE, finn_navn

    kolonner = [str(navn) for navn in row.index]
    answers: dict[str, str] = {}
    for key, kolonnenavn in SVAR_TIL_KOLONNE.items():
        treff = finn_navn(kolonner, kolonnenavn) or (
            QUESTION_COLUMNS[key] if QUESTION_COLUMNS[key] in row.index else ""
        )
        if treff and not is_empty(row[treff]):
            answers[key] = str(row[treff]).strip()
        else:
            answers[key] = ""
    return answers


def default_snowflake_url() -> str:
    explicit = (
        os.getenv("STIKKPROVE_SOURCE_URL")
        or os.getenv("SNOWFLAKE_URL")
        or os.getenv("SNOWFLAKE_UI_URL")
        or ""
    ).strip()
    if explicit:
        return explicit
    account = (os.getenv("SNOWFLAKE_ACCOUNT") or "").strip()
    if not account:
        return ""
    if account.startswith("http://") or account.startswith("https://"):
        return account
    if "snowflakecomputing.com" in account:
        return "https://" + account.lstrip("/")
    return "https://" + account + ".snowflakecomputing.com"


def source_open_info(source: dict | None) -> dict[str, str | Path | None]:
    source = source or {}
    raw_url = str(source.get("url") or "").strip()
    kind = str(source.get("kind") or "")
    path_text = str(source.get("path") or "")
    visningsnavn = str(source.get("original_name") or source.get("name") or "grunnlag")
    web = ""
    file_path: Path | None = None
    if raw_url.lower().startswith("http://") or raw_url.lower().startswith("https://"):
        web = raw_url
    elif raw_url:
        candidate = Path(raw_url)
        if candidate.exists():
            file_path = candidate
    if kind == "snowflake" and not web:
        web = default_snowflake_url()
    if path_text:
        stored = Path(path_text)
        if stored.exists():
            file_path = stored
    return {"web": web, "path": file_path, "name": visningsnavn}


def open_local_path(path: Path) -> None:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError("Fant ikke filen.")
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    opener = "open" if os.name == "posix" else "xdg-open"
    os.spawnlp(os.P_NOWAIT, opener, opener, str(target))
