"""Kobler kolonnenavn i Snowflake til navnene appen bruker.

En tabell i Snowflake heter gjerne STIKKPROVE_NR, mens appen leter etter
stikkpr\u00f8ve_nr. Her gjoeres begge om til en felles, forenklet form, slik at de
treffer hverandre uansett store bokstaver, understreker og norske bokstaver.
"""

from __future__ import annotations

import pandas as pd

from src.config import (
    ORGNR_COLS,
    SAMPLE_ID_COL,
    STILLINGSFORHOLD_COLS,
    VARSELKODE_COL,
)

# Kolonner appen leser fra grunnlaget. Rekkefolgen avgjor hvilket navn som
# vinner hvis to kolonner i tabellen forenkles til det samme.
DATAKOLONNER = (
    SAMPLE_ID_COL,
    "spk_person_id_kilde",
    STILLINGSFORHOLD_COLS[0],
    "linje_nr_kilde",
    VARSELKODE_COL,
    "aksjon_dt",
    "arbeidsgivernavn",
    ORGNR_COLS[0],
    "l\u00f8nn",
    "faste_tillegg",
    "variable_tillegg",
    "funksjonstillegg",
    "registrert_dt_kilde",
    "aksjonkodebesk",
    "stilling_kd",
    "stillingsbetegnelse",
    "stillingsstoerrelse_prs",
    "samlet_loenn_bel",
    "forrige_rad_aksjon_dt",
    "forrige_rad_loenn_bel",
    "forrige_rad_faste_tillegg_bel",
    "forrige_rad_funksjon_tillegg_bel",
    "forrige_rad_variable_tillegg_bel",
    "forrige_rad_samlet_loenn_bel",
    "endring_loenn_bel",
    "endring_faste_tillegg_bel",
    "endring_funksjon_tillegg_bel",
    "endring_variable_tillegg_bel",
    "endring_samlet_loenn_bel",
    "sikkert_varsel_flg",
    "har_historikkvarsel_flg",
    "antall_varsel_per_linje",
    "antall_kvittering_varsel_per_linje",
    "antall_validert_varsel_kunde_per_linje",
    "antall_varsel_mot_arbeidsgiver_per_linje",
    "behandlingsspor",
)

# Hvilken kolonne i kildetabellen hvert svarfelt skrives til.
#
# Skjemaet har atte felter, men tabellen har seks svarkolonner. De to
# fritekstfeltene star ikke her: handling_annet foelger handling, og
# unntak_forklaring foelger vanlighet. Begge slaas sammen med svaret sitt for
# skriving, se _writeback_values i snowflake_client.
SVAR_TIL_KOLONNE = {
    "handling": "haandtering_av_varselet",
    "begrunnelse": "begrunnelse_og_regelverk",
    "vanlighet": "praksis_og_eventuelle_unntak",
    "periode_spesielt": "saerlige_forhold",
    "historisk_korrekt": "vurdering_av_korrekthet",
    "kommentar": "andre_kommentarer",
}

# Kolonner appen kan skrive svar tilbake til.
SVARKOLONNER = tuple(SVAR_TIL_KOLONNE.values())

# Kolonner appen ikke klarer seg uten.
PAAKREVDE = (SAMPLE_ID_COL,)

KJENTE_KOLONNER = DATAKOLONNER + SVARKOLONNER


def forenkle(navn: object) -> str:
    """Reduserer et kolonnenavn til en form som taaler skrivemaatene i Snowflake."""
    tekst = str(navn or "").strip().lower()
    for fra, til in (
        ("\u00f8", "o"),
        ("\u00f6", "o"),
        ("\u00e6", "a"),
        ("\u00e5", "a"),
        ("\u00e4", "a"),
    ):
        tekst = tekst.replace(fra, til)
    tekst = "".join(ch for ch in tekst if ch.isalnum())
    for fra, til in (("oe", "o"), ("ae", "a"), ("aa", "a")):
        tekst = tekst.replace(fra, til)
    return tekst


def _oppslag() -> dict[str, str]:
    tabell: dict[str, str] = {}
    for navn in KJENTE_KOLONNER:
        tabell.setdefault(forenkle(navn), navn)
    return tabell


def finn_navn(kolonner: list[str], oensket: str) -> str:
    """Navnet i ``kolonner`` som svarer til ``oensket``, eller tom streng."""
    maal = forenkle(oensket)
    for kolonne in kolonner:
        if forenkle(kolonne) == maal:
            return str(kolonne)
    return ""


def oversett(frame: pd.DataFrame) -> pd.DataFrame:
    """Doeper om kolonnene i ``frame`` til navnene appen kjenner."""
    if frame is None or len(frame.columns) == 0:
        return frame
    kjent = _oppslag()
    nye: dict[object, str] = {}
    brukt: set[str] = set()
    for kolonne in frame.columns:
        navn = kjent.get(forenkle(kolonne))
        if navn and navn not in brukt and navn != kolonne:
            nye[kolonne] = navn
            brukt.add(navn)
        elif navn:
            brukt.add(navn)
    if not nye:
        return frame
    return frame.rename(columns=nye)


def manglende(kolonner: list[str]) -> list[str]:
    """Paakrevde kolonner som ikke finnes i ``kolonner``."""
    funnet = {forenkle(kolonne) for kolonne in kolonner}
    return [navn for navn in PAAKREVDE if forenkle(navn) not in funnet]


def gjenkjente(kolonner: list[str]) -> list[str]:
    """Appens kolonner som finnes i ``kolonner``."""
    funnet = {forenkle(kolonne) for kolonne in kolonner}
    return [navn for navn in KJENTE_KOLONNER if forenkle(navn) in funnet]
