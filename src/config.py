from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"
EXPORT_DIR = ROOT / "exports"
DB_PATH = DATA_DIR / "assessments.sqlite"

SOURCE = os.getenv("STIKKPROVE_SOURCE", "file").strip().lower()
ADMIN_PIN = os.getenv("STIKKPROVE_ADMIN_PIN") or "2233"


def live_refresh_seconds() -> int:
    """Hvor ofte fremdriften henter kollegenes tall paa nytt.

    I Snowflake koster hver runde en sporring per paalogget saksbehandler, og
    warehouset rekker aldri aa suspendere seg naar det bankes for ofte.
    """
    raw = os.getenv("STIKKPROVE_LIVE_SECONDS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    if os.getenv("STIKKPROVE_BACKEND", "auto").strip().lower() == "snowflake":
        return 60
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return 60
    except Exception:
        return 6

def queue_refresh_seconds() -> int:
    """Hvor lenge koen kan vaere basert paa en gammel lesning av kilden.

    Naar tiden er ute, leser appen tabellen paa nytt ved neste oppdatering, og
    nye stikkproever dukker opp i koen. Lavere tall gir ferskere ko, men flere
    sporringer mot warehouset.
    """
    raw = os.getenv("STIKKPROVE_QUEUE_SECONDS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return 300


DEFAULT_FILE_CANDIDATES = [
    Path(os.getenv("STIKKPROVE_FILE", "")),
    DATA_DIR / "samples.csv",
    DATA_DIR / "samples.xlsx",
]

SAMPLE_ID_COL = "stikkpr\u00f8ve_nr"
VARSELKODE_COL = "varselkode"
LINJE_NR_COL = "linje_nr_kilde"
STILLINGSFORHOLD_COLS = (
    "stillingsforhold_id_kilde",
    "stillingsforholdsnummer",
    "stillingsforhold_nr",
)
ORGNR_COLS = (
    "arbeidsgiver_orgnr",
    "arbeidsgiver_organisasjonsnummer",
    "organisasjonsnummer",
    "orgnr",
    "arbeidsgiverorgnr",
    "ag_orgnr",
    "arbeidsgiver_org_nr",
)
CHOOSE_OPTION = "Velg svar"

QUESTION_COLUMNS = {
    "handling": "1. Hvordan ville du h\u00e5ndtert dette varselet?",
    "begrunnelse": (
        "2. Hva er den viktigste grunnen til at du ville h\u00e5ndtert den slik? "
        "Er det noen regelverk endring som p\u00e5virker denne saken? "
        "Eventuelt vis til vilk\u00e5r, regelverksendring eller rutine denne saken er relatert til."
    ),
    "vanlighet": (
        "3. Er dette en vanlig m\u00e5te \u00e5 h\u00e5ndtere denne typen varsel p\u00e5, "
        "eller er det et s\u00e6rtilfelle/unntak? Forklar \u00e5rsaken til unntaket."
    ),
    "periode_spesielt": (
        "4. Er det noe spesielt med denne perioden/datoen, arbeidsgiveren, "
        "stillingsforholdet/type stilling, tillegget eller l\u00f8nnen for dette varselet?"
    ),
    "historisk_korrekt": "5. Vurderer du vurderingen av dette varslet som korrekt?",
    "kommentar": "Andre kommentarer?",
}

HANDLING_OPTIONS = [
    "Kvittert og bekreftet varslet",
    "Korrigert l\u00f8nn, innrapportert l\u00f8nn var feil",
    "Korrigert fast tillegg",
    "Korrigert variabelt tillegg",
    "Korrigert funksjonstillegg",
    "Korrigert l\u00f8nn p\u00e5 forrige linje",
    "Slettet linje med varslet",
    "Slettet linje, ny l\u00f8nn rapportert p\u00e5 tidligere linje",
    "Merket for midlertidig stilling / h\u00f8yere l\u00f8nn",
    "Ingen reell varsel / kan ikke gjenskapes",
    "Annet",
]

VANLIGHET_OPTIONS = [
    "Vanlig m\u00e5te",
    "S\u00e6rtilfelle",
    "Unntak",
    "Usikker",
]

KORREKT_OPTIONS = [
    "Ja",
    "Nei",
    "Delvis",
    "Kan ikke vurdere",
]
