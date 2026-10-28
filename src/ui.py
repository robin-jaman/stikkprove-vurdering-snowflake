from __future__ import annotations

import html
from datetime import datetime, timezone

import streamlit as st

from src.config import (
    CHOOSE_OPTION,
    HANDLING_OPTIONS,
    KORREKT_OPTIONS,
    LINJE_NR_COL,
    ORGNR_COLS,
    QUESTION_COLUMNS,
    SAMPLE_ID_COL,
    STILLINGSFORHOLD_COLS,
    VANLIGHET_OPTIONS,
    VARSELKODE_COL,
    live_refresh_seconds,
    queue_refresh_seconds,
)
from src.formatting import DASH, as_text, is_empty
from src.loader import (
    ensure_default_sources,
    load_all_active_samples,
)
from src.store import (
    claim_next,
    claimable_sample_ids,
    decode_sak,
    egen_kostatus,
    encode_sak,
    get_assessment,
    get_source,
    list_reviewers,
    nullstill_lesinger,
    release_claims,
    sample_keys,
    save_assessment,
    sources_cache_key,
    touch_claim,
)

CSS = """
<style>
    .block-container { padding-top: 3.2rem; padding-bottom: 0.2rem; }
    div[data-testid="stHeadingWithActionElements"],
    div[data-testid="stHeadingWithActionElements"] h1,
    div[data-testid="stHeadingWithActionElements"] h2,
    [data-testid="stHeadingIconWrapper"],
    [data-testid="stHeadingIcon"] {
        overflow: visible !important;
    }
    [data-testid="stHeadingWithActionElements"] h2 {
        line-height: 1.35 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] { margin-bottom: 0.18rem; }
    [data-testid="InputInstructions"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] {
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebarContent"] {
        height: 100% !important;
        max-height: 100vh !important;
        overflow: hidden !important;
        display: flex !important;
        flex-direction: column;
        min-height: 0;
    }
    [data-testid="stSidebarNav"] {
        flex: 0 0 auto;
    }
    [data-testid="stSidebarUserContent"] {
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden !important;
        padding-top: 0.55rem !important;
        padding-bottom: 0.7rem !important;
        display: flex;
        flex-direction: column;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
        gap: clamp(0.2rem, 1.05vh, 0.8rem) !important;
    }
    [data-testid="stSidebar"] h2 {
        font-size: clamp(0.95rem, 2.05vh, 1.25rem) !important;
        line-height: 1.25 !important;
    }
    [data-testid="stSidebar"] h3 {
        font-size: clamp(0.92rem, 1.9vh, 1.15rem) !important;
        line-height: 1.25 !important;
    }
    [data-testid="stSidebarUserContent"] p,
    [data-testid="stSidebarUserContent"] li {
        font-size: clamp(0.78rem, 1.5vh, 1rem) !important;
        line-height: 1.35 !important;
    }
    .stApp:has(.st-key-vurdering_arbeid),
    .stApp:has(.st-key-vurdering_arbeid) [data-testid="stAppViewContainer"],
    .stApp:has(.st-key-vurdering_arbeid) [data-testid="stMain"],
    .stApp:has(.st-key-vurdering_arbeid) .stMain,
    .stApp:has(.st-key-vurdering_arbeid) [data-testid="stAppScrollToBottomContainer"] {
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
    }
    .stApp:has(.st-key-vurdering_arbeid) .block-container {
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
        display: flex !important;
        flex-direction: column;
        box-sizing: border-box;
    }
    .stApp:has(.st-key-vurdering_arbeid) .block-container > div[data-testid="stVerticalBlock"] {
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }
    .stApp:has(.st-key-vurdering_arbeid) .block-container > div[data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
        flex: 0 0 auto;
    }
    .stApp:has(.st-key-vurdering_arbeid) .block-container > div[data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(.st-key-vurdering_arbeid) {
        flex: 1 1 auto !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }
    .st-key-vurdering_arbeid {
        flex: 1 1 auto !important;
        min-height: 0 !important;
        height: 100% !important;
        overflow: hidden !important;
    }
    .st-key-vurdering_arbeid > [data-testid="stLayoutWrapper"],
    .st-key-vurdering_arbeid [data-testid="stHorizontalBlock"],
    .st-key-vurdering_arbeid [data-testid="stColumn"]:has(.st-key-vurderingsskjema),
    .st-key-vurdering_arbeid [data-testid="stColumn"]:has(.st-key-vurderingsskjema) > [data-testid="stVerticalBlock"] {
        height: 100% !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }
    .st-key-vurdering_arbeid [data-testid="stHorizontalBlock"] {
        align-items: stretch !important;
    }
    .st-key-vurdering_arbeid [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    .st-key-vurdering_arbeid [data-testid="stColumn"]:has(.st-key-sak_kolonne),
    .st-key-vurdering_arbeid [data-testid="stColumn"]:has(.st-key-sak_kolonne) > [data-testid="stVerticalBlock"] {
        min-height: 0 !important;
        height: 100% !important;
        overflow: hidden !important;
    }
    [data-testid="stLayoutWrapper"]:has(> .st-key-sak_kolonne) {
        height: 100% !important;
        min-height: 0 !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
    }
    .st-key-sak_kolonne {
        overflow: visible !important;
        container-type: inline-size;
        container-name: sak;
    }
    [data-testid="stLayoutWrapper"]:has(> .st-key-vurderingsskjema) {
        flex: 1 1 auto !important;
        align-self: stretch !important;
        height: 100% !important;
        max-height: 100% !important;
        min-height: 0 !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
        padding-right: 0.2rem;
    }
    .st-key-vurderingsskjema {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
    }
    .ada-rutenett {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.38rem;
    }
    @container sak (max-width: 26rem) {
        .ada-rutenett {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    @container sak (max-width: 16.5rem) {
        .ada-rutenett {
            grid-template-columns: minmax(0, 1fr);
        }
    }
    .ada-celle {
        min-height: 4.2rem;
        height: auto;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        box-sizing: border-box;
        border: 1px solid var(--st-border-color, #c5d0da);
        border-radius: 0.45rem;
        background: var(--st-secondary-background-color, #e8eef3);
        padding: 0.38rem 0.5rem 0.32rem;
    }
    .ada-etikett {
        font-size: clamp(0.68rem, 1.35cqi, 0.78rem);
        line-height: 1.2;
        color: var(--st-text-color);
        opacity: 0.78;
        margin-bottom: 0.12rem;
        overflow-wrap: anywhere;
    }
    .ada-verdi {
        font-weight: 650;
        font-size: clamp(0.78rem, 1.7cqi, 0.95rem);
        line-height: 1.25;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
</style>
"""


# Nokkelen endrer seg ikke naar det kommer nye rader i en Snowflake-tabell, saa
# ttl er det som sorger for at koen etter hvert faar med seg nye stikkproever.
@st.cache_data(ttl=queue_refresh_seconds(), show_spinner="Leser stikkpr\u00f8ver...")
def _cached_samples(cache_key: str):
    return load_all_active_samples()


def _option_index(options: list[str], value: str | None, fallback: int = 0) -> int:
    if value and value in options:
        return options.index(value)
    return fallback


def _choice_options(options: list[str]) -> list[str]:
    return [CHOOSE_OPTION] + list(options)


def _svar_key(sample_nr: str, name: str, kilde_id: str = "") -> str:
    prefix = str(kilde_id or "") + "_" if kilde_id else ""
    return "svar_" + prefix + sample_nr + "_" + name


def _init_svar(sample_nr: str, name: str, value: str | None, kilde_id: str = "") -> str:
    key = _svar_key(sample_nr, name, kilde_id)
    if key not in st.session_state:
        st.session_state[key] = value or ""
    return key


def _clear_svar(sample_nr: str, kilde_id: str = "") -> None:
    for name in (
        "handling",
        "handling_annet",
        "begrunnelse",
        "vanlighet",
        "unntak_forklaring",
        "periode_spesielt",
        "historisk_korrekt",
        "kommentar",
    ):
        st.session_state.pop(_svar_key(sample_nr, name, kilde_id), None)


def _row_value(row, *candidates: str) -> str:
    lookup = {str(key).strip().lower(): key for key in row.index}
    for name in candidates:
        key = lookup.get(name.lower())
        if key is None:
            continue
        text = as_text(row.get(key), "")
        if text:
            return text
    return DASH


def _filled(value: str | None) -> bool:
    return bool(value) and value != CHOOSE_OPTION and not is_empty(value)


def _missing_required(
    saksbehandler: str,
    handling: str,
    handling_annet: str,
    begrunnelse: str,
    vanlighet: str,
    unntak_forklaring: str,
    periode_spesielt: str,
    historisk_korrekt: str,
    kommentar: str,
) -> list[str]:
    missing: list[str] = []
    if not saksbehandler:
        missing.append("Saksbehandler")
    if not _filled(handling):
        missing.append(QUESTION_COLUMNS["handling"])
    if handling == "Annet" and not _filled(handling_annet):
        missing.append("Beskriv h\u00e5ndteringen n\u00e6rmere")
    if not _filled(begrunnelse):
        missing.append(QUESTION_COLUMNS["begrunnelse"])
    if not _filled(vanlighet):
        missing.append(QUESTION_COLUMNS["vanlighet"])
    if not _filled(unntak_forklaring):
        missing.append("Forklar om dette er vanlig h\u00e5ndtering, s\u00e6rtilfelle eller unntak")
    if not _filled(periode_spesielt):
        missing.append(QUESTION_COLUMNS["periode_spesielt"])
    if not _filled(historisk_korrekt):
        missing.append(QUESTION_COLUMNS["historisk_korrekt"])
    return missing


NAVN_STATE = "aktiv_saksbehandler"
NAVN_WIDGET = "saksbehandler_valg"
NAVN_HUSK = "saksbehandler_husket"
NAVN_PLACEHOLDER = "Velg navn"
NAVN_MANUELL = "navn_manuell"
AAPNE_BYTT_NAVN = "aapne_bytt_navn"
AKTIV_SAK = "aktiv_sak_nr"
FOKUS_FELT = "fokus_vurderingsfelt"


def _husk_navn() -> None:
    """Holder paa navnevalget naar brukeren bytter side."""
    st.session_state[NAVN_HUSK] = str(st.session_state.get(NAVN_WIDGET) or "")


def _felt_hint(label: str) -> None:
    if st.session_state.get(FOKUS_FELT) != label:
        return
    st.error("Fyll ut dette feltet f\u00f8r du lagrer.")


def _fornavn(navn: str) -> str:
    parts = navn.strip().split()
    return parts[0] if parts else navn


def _nullstill_navn() -> None:
    navn = str(st.session_state.get(NAVN_STATE) or "").strip()
    if navn:
        release_claims(navn)
    st.session_state[NAVN_STATE] = ""
    st.session_state[NAVN_MANUELL] = True
    st.session_state[NAVN_WIDGET] = NAVN_PLACEHOLDER
    st.session_state.pop(AKTIV_SAK, None)
    st.session_state.pop(AAPNE_BYTT_NAVN, None)


def _laas_navn(navn: str) -> None:
    st.session_state[NAVN_STATE] = navn
    st.session_state.pop(AAPNE_BYTT_NAVN, None)


def aktiv_saksbehandler(names: list[str]) -> str:
    navn = str(st.session_state.get(NAVN_STATE) or "").strip()
    if navn and names and navn not in names:
        st.session_state[NAVN_STATE] = ""
        return ""
    return navn if navn in names else ""


@st.dialog("Bytte saksbehandler?")
def _confirm_bytt_navn(navn: str) -> None:
    st.write("Du er logget inn som **" + navn + "**.")
    st.write(
        "Vurderinger lagres p\u00e5 dette navnet. "
        "Bytt bare hvis det ikke er deg. Ellers kan svar bli lagret p\u00e5 feil person."
    )
    avbryt, bytt = st.columns(2)
    with avbryt:
        if st.button(
            "Fortsett som " + navn,
            width="stretch",
            key="avbryt_bytt_navn",
        ):
            st.session_state.pop(AAPNE_BYTT_NAVN, None)
            st.rerun()
    with bytt:
        if st.button(
            "Bytt navn",
            type="primary",
            width="stretch",
            key="bekreft_bytt_navn",
        ):
            _nullstill_navn()
            st.rerun()


def _skriv_tilbake(record: dict, kilderad: object = None) -> None:
    """Legger svaret inn i raden i kildetabellen, hvis det er slaatt paa.

    Gjelder alle grunnlag, ogsaa opplastede regneark. Raden finnes paa
    stikkproevenummeret, saa to grunnlag med samme nummer peker paa samme rad,
    og det sist lagrede svaret blir staaende. Mangler raden helt, lages den av
    stikkproevedataene i ``kilderad``.

    Alt dette er mellom appen og Snowflake. Saksbehandleren har allerede faatt
    svaret lagret, og kan ikke gjore noe med hvordan kilden oppforer seg, saa
    beskjeder herfra gaar til endringsloggen i Administrasjon i stedet.
    """
    from src.snowflake_client import write_back_assessment, writeback_enabled
    from src.store import LOGG_TILBAKESKRIVING, log_admin_event

    if not writeback_enabled():
        return
    nummer = str(record.get("stikkprove_nr") or "")
    try:
        beskjed = write_back_assessment(record, kilderad)
    except Exception as exc:
        log_admin_event(
            "Stikkpr\u00f8ve "
            + nummer
            + " "
            + LOGG_TILBAKESKRIVING
            + ": "
            + str(exc)
        )
        return
    if beskjed:
        log_admin_event(beskjed)


def persist(record: dict, kilderad: object = None) -> None:
    record = dict(record)
    kilde_id = str(record.get("kilde_id") or "")
    source = get_source(kilde_id) if kilde_id else None
    record["kilde"] = (source or {}).get("name") or record.get("kilde") or ""
    save_assessment(record)
    from src.db import uses_snowflake_storage

    if uses_snowflake_storage():
        _skriv_tilbake(record, kilderad)
        return
    from src.snowflake_client import save_assessment as save_snowflake
    from src.snowflake_client import snowflake_configured

    if not snowflake_configured():
        return
    try:
        save_snowflake(record)
    except Exception as exc:
        from src.store import log_admin_event

        log_admin_event(
            "Stikkpr\u00f8ve "
            + str(record.get("stikkprove_nr") or "")
            + " ble lagret lokalt, men ikke skrevet til Snowflake: "
            + str(exc)
        )


def render_copyable_id(person_id: str) -> None:
    """Viser SPK person-ID med kopiknapp.

    st.code har en innebygd kopiknapp som virker i begge kjoremiljoene i
    Snowflake. En egen komponent ville vaert penere, men Components v2 er ikke
    tillatt paa warehouse runtime.
    """
    st.markdown("**SPK person-ID**")
    if not person_id:
        st.write("\u2014")
        return
    st.code(person_id, language=None, wrap_lines=True)


def render_ada_keys(row) -> None:
    items = [
        ("Linjenummer", _row_value(row, LINJE_NR_COL, "linjenummer")),
        ("Varselkode", _row_value(row, VARSELKODE_COL)),
        ("Aksjonsdato", _row_value(row, "aksjon_dt", "aksjonsdato")),
        ("Arbeidsgivernavn", _row_value(row, "arbeidsgivernavn")),
        ("Arbeidsgiver org.nr", _row_value(row, *ORGNR_COLS)),
        ("Stillingsforholdsnummer", _row_value(row, *STILLINGSFORHOLD_COLS)),
    ]
    celler = []
    for label, value in items:
        celler.append(
            "<div class='ada-celle'>"
            "<div class='ada-etikett'>"
            + html.escape(label)
            + "</div>"
            "<div class='ada-verdi'>"
            + html.escape(value)
            + "</div>"
            "</div>"
        )
    st.html("<div class='ada-rutenett'>" + "".join(celler) + "</div>")


def render_sidebar(saksbehandler: str) -> None:
    with st.sidebar:
        if saksbehandler:
            st.subheader(saksbehandler, anchor=False)
            if st.button(":gray[Ikke deg?]", type="tertiary"):
                st.session_state[AAPNE_BYTT_NAVN] = True
                st.rerun()
            from src.identity import current_login

            login = current_login()
            if login:
                st.caption("Snowflake-bruker: " + login)
            st.header(":material/info: Hva skal du gj\u00f8re")
            st.markdown(
                "Du vurderer stikkpr\u00f8ver av historiske avvik og varsler fra l\u00f8nnsfilmottak. "
                "Svarene dine blir treningsgrunnlag, slik at en KI-modell kan l\u00e6re av faglig skj\u00f8nn."
            )
            st.header(":material/checklist: Slik gj\u00f8r du det")
            st.markdown(
                "1. Kopier *SPK person ID*.\n"
                "2. Sl\u00e5 den opp i ADA og finn linjen.\n"
                "3. Svar p\u00e5 sp\u00f8rsm\u00e5lene under *Din vurdering*.\n"
                "4. Lagre svar og hent neste stikkpr\u00f8ve i k\u00f8en."
            )


def render_welcome(names: list[str]) -> None:
    st.title(":material/waving_hand: Hei!")
    if not names:
        st.warning("Be administrasjon registrere navnet ditt f\u00f8rst.")
        return
    valg = [NAVN_PLACEHOLDER] + names
    husket = str(st.session_state.get(NAVN_HUSK) or "")
    st.selectbox(
        "Hva heter du?",
        valg,
        index=valg.index(husket) if husket in valg else 0,
        key=NAVN_WIDGET,
        on_change=_husk_navn,
    )
    st.caption(
        "Svarene lagres p\u00e5 navnet du velger. Velg bare ditt eget navn, "
        "og bytt ikke til en kollega hvis dere sitter ved samme maskin."
    )
    valgt = str(st.session_state.get(NAVN_WIDGET) or "").strip()
    if valgt and valgt != NAVN_PLACEHOLDER:
        if st.button("Fortsett som " + valgt, type="primary"):
            _laas_navn(valgt)
            st.rerun()


def render_fremdrift(ferdig: int, total: int) -> None:
    """Viser bare saksbehandlerens egen ko.

    Hvor mange stikkproever tabellen har i alt, og hva kollegene holder paa med,
    hoerer hjemme i Administrasjon. Her skal det bare staa hvor langt du er kommet
    med dine egne.
    """
    if total == 0:
        st.progress(0.0, text="Ingen stikkpr\u00f8ver er tildelt deg")
        return
    st.progress(
        ferdig / total,
        text="**{done}** av **{total}** vurdert".format(done=ferdig, total=total),
    )


@st.fragment(run_every=live_refresh_seconds())
def render_live_fremdrift(
    saksbehandler: str,
    all_ids,
    sample_nr: str | None = None,
    claimable=None,
    kilde_id: str = "",
) -> None:
    nullstill_lesinger()
    if sample_nr:
        touch_claim(sample_nr, saksbehandler, kilde_id=kilde_id)
    elif claimable:
        ledig = claim_next(saksbehandler, claimable)
        if ledig:
            st.session_state[AKTIV_SAK] = encode_sak(ledig)
            st.rerun()
    egen = egen_kostatus(saksbehandler, all_ids)
    render_fremdrift(egen["ferdig"], egen["total"])


@st.fragment
def render_vurderingsskjema(
    saksbehandler: str, sample_nr: str, row, draft: dict, kilde_id: str = ""
) -> None:
    st.subheader("Din vurdering", anchor=False)
    handling_choices = _choice_options(HANDLING_OPTIONS)
    vanlighet_choices = _choice_options(VANLIGHET_OPTIONS)
    korrekt_choices = _choice_options(KORREKT_OPTIONS)
    handling_key = _init_svar(
        sample_nr,
        "handling",
        draft.get("handling") if draft.get("handling") in handling_choices else CHOOSE_OPTION,
        kilde_id,
    )
    annet_key = _init_svar(sample_nr, "handling_annet", draft.get("handling_annet"), kilde_id)
    begrunnelse_key = _init_svar(sample_nr, "begrunnelse", draft.get("begrunnelse"), kilde_id)
    vanlighet_key = _init_svar(
        sample_nr,
        "vanlighet",
        draft.get("vanlighet") if draft.get("vanlighet") in vanlighet_choices else CHOOSE_OPTION,
        kilde_id,
    )
    unntak_key = _init_svar(sample_nr, "unntak_forklaring", draft.get("unntak_forklaring"), kilde_id)
    periode_key = _init_svar(sample_nr, "periode_spesielt", draft.get("periode_spesielt"), kilde_id)
    korrekt_key = _init_svar(
        sample_nr,
        "historisk_korrekt",
        draft.get("historisk_korrekt")
        if draft.get("historisk_korrekt") in korrekt_choices
        else CHOOSE_OPTION,
        kilde_id,
    )
    kommentar_key = _init_svar(sample_nr, "kommentar", draft.get("kommentar"), kilde_id)
    hint_handling = QUESTION_COLUMNS["handling"]
    hint_annet = "Beskriv h\u00e5ndteringen n\u00e6rmere"
    hint_begrunnelse = QUESTION_COLUMNS["begrunnelse"]
    hint_vanlighet = QUESTION_COLUMNS["vanlighet"]
    hint_unntak = "Forklar om dette er vanlig h\u00e5ndtering, s\u00e6rtilfelle eller unntak"
    hint_periode = QUESTION_COLUMNS["periode_spesielt"]
    hint_korrekt = QUESTION_COLUMNS["historisk_korrekt"]
    hint_kommentar = QUESTION_COLUMNS["kommentar"]
    mangler_naa = _missing_required(
        saksbehandler,
        str(st.session_state.get(handling_key) or ""),
        str(st.session_state.get(annet_key) or ""),
        str(st.session_state.get(begrunnelse_key) or ""),
        str(st.session_state.get(vanlighet_key) or ""),
        str(st.session_state.get(unntak_key) or ""),
        str(st.session_state.get(periode_key) or ""),
        str(st.session_state.get(korrekt_key) or ""),
        str(st.session_state.get(kommentar_key) or ""),
    )
    fokus = str(st.session_state.get(FOKUS_FELT) or "")
    if fokus and fokus not in mangler_naa:
        st.session_state.pop(FOKUS_FELT, None)
        fokus = ""

    vis_annet = str(st.session_state.get(handling_key) or "") == "Annet"
    h1, h2 = st.columns(2)
    with h1:
        with st.container(border=fokus == hint_handling):
            _felt_hint(hint_handling)
            handling = st.selectbox(
                hint_handling,
                handling_choices,
                key=handling_key,
            )
    with h2:
        with st.container(border=fokus == hint_annet):
            _felt_hint(hint_annet)
            handling_annet = st.text_input(
                hint_annet,
                key=annet_key,
                help=(
                    "P\u00e5krevd n\u00e5r du velger Annet. Ellers valgfritt."
                    if vis_annet
                    else "Valgfritt. P\u00e5krevd bare hvis du velger Annet."
                ),
            )
    with st.container(border=fokus == hint_begrunnelse):
        _felt_hint(hint_begrunnelse)
        begrunnelse = st.text_area(
            hint_begrunnelse,
            key=begrunnelse_key,
            height=56,
        )
    with st.container(border=fokus == hint_vanlighet):
        _felt_hint(hint_vanlighet)
        vanlighet = st.segmented_control(
            hint_vanlighet,
            vanlighet_choices,
            key=vanlighet_key,
            width="stretch",
        )
    with st.container(border=fokus == hint_unntak):
        _felt_hint(hint_unntak)
        unntak_forklaring = st.text_area(
            hint_unntak,
            key=unntak_key,
            height=44,
        )
    with st.container(border=fokus == hint_periode):
        _felt_hint(hint_periode)
        periode_spesielt = st.text_area(
            hint_periode,
            key=periode_key,
            height=44,
        )
    with st.container(border=fokus == hint_korrekt):
        _felt_hint(hint_korrekt)
        historisk_korrekt = st.segmented_control(
            hint_korrekt,
            korrekt_choices,
            key=korrekt_key,
            width="stretch",
        )
    with st.container(border=fokus == hint_kommentar):
        _felt_hint(hint_kommentar)
        kommentar = st.text_area(
            hint_kommentar,
            key=kommentar_key,
            height=40,
        )
    answers = {
        "handling": handling or "",
        "handling_annet": handling_annet or "",
        "begrunnelse": begrunnelse or "",
        "vanlighet": vanlighet or "",
        "unntak_forklaring": unntak_forklaring or "",
        "periode_spesielt": periode_spesielt or "",
        "historisk_korrekt": historisk_korrekt or "",
        "kommentar": kommentar or "",
    }
    komplett = not _missing_required(saksbehandler, **answers)
    allerede_lagret = get_assessment(sample_nr, saksbehandler, kilde_id=kilde_id) is not None
    utkast_key = "utkast_" + encode_sak((kilde_id, sample_nr))
    if allerede_lagret:
        st.success(
            "Lagret. Hent neste stikkpr\u00f8ve n\u00e5r du er klar.",
            icon=":material/check_circle:",
        )
    else:
        st.caption(
            "Svarene lagres f\u00f8rst n\u00e5r du trykker **Lagre svar**. "
            "Du kan avslutte etter lagring uten \u00e5 hente neste sak."
        )
    lagre_col, neste_col = st.columns(2)
    with lagre_col:
        lagre = st.button(
            "Lagre svar",
            type="secondary" if allerede_lagret else "primary",
            width="stretch",
            help=(
                None
                if komplett
                else "Skjemaet er ikke komplett. Trykk for \u00e5 g\u00e5 til feltet som mangler."
            ),
        )
    with neste_col:
        hent_neste = st.button(
            "Hent neste stikkpr\u00f8ve",
            type="primary" if allerede_lagret else "secondary",
            width="stretch",
            icon=":material/arrow_forward:",
            disabled=not allerede_lagret,
            help="Lagre svarene f\u00f8rst." if not allerede_lagret else None,
        )
    if lagre:
        mangler = _missing_required(saksbehandler, **answers)
        if mangler:
            st.session_state[FOKUS_FELT] = mangler[0]
            st.rerun(scope="fragment")
        persist(
            {
                "stikkprove_nr": sample_nr,
                "saksbehandler": saksbehandler,
                "varselkode": as_text(row.get(VARSELKODE_COL), ""),
                "handling": answers["handling"],
                "handling_annet": answers["handling_annet"],
                "begrunnelse": answers["begrunnelse"],
                "vanlighet": answers["vanlighet"],
                "unntak_forklaring": answers["unntak_forklaring"],
                "periode_spesielt": answers["periode_spesielt"],
                "historisk_korrekt": answers["historisk_korrekt"],
                "kommentar": answers["kommentar"],
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "kilde_id": kilde_id,
            },
            row,
        )
        st.session_state.pop(utkast_key, None)
        st.session_state.pop(FOKUS_FELT, None)
        st.rerun()
    if hent_neste:
        release_claims(saksbehandler)
        st.session_state.pop(utkast_key, None)
        st.session_state.pop(AKTIV_SAK, None)
        _clear_svar(sample_nr, kilde_id)
        st.rerun()


def _koble_snowflake_navn(names: list[str]) -> None:
    if st.session_state.get(NAVN_MANUELL):
        return
    if aktiv_saksbehandler(names):
        return
    from src.identity import current_login, reviewer_for_login

    matched = reviewer_for_login(current_login())
    if matched and matched in names:
        _laas_navn(matched)


def main() -> None:
    nullstill_lesinger()
    st.markdown(CSS, unsafe_allow_html=True)
    names = list_reviewers()
    _koble_snowflake_navn(names)
    saksbehandler = aktiv_saksbehandler(names)
    if st.session_state.get(AAPNE_BYTT_NAVN) and saksbehandler:
        _confirm_bytt_navn(saksbehandler)
    render_sidebar(saksbehandler)

    if not saksbehandler:
        render_welcome(names)
        return

    fornavn = _fornavn(saksbehandler)
    st.header(":material/waving_hand: Hei, " + fornavn, anchor=False)

    try:
        ensure_default_sources()
        samples, load_warnings = _cached_samples(sources_cache_key())
    except Exception as exc:
        st.error("Klarte ikke \u00e5 lese stikkpr\u00f8vefilen.")
        st.exception(exc)
        st.stop()
    for warning in load_warnings:
        st.warning(warning)

    keys = sample_keys(samples)
    claimable = claimable_sample_ids(saksbehandler, keys)
    prefer = decode_sak(st.session_state.get(AKTIV_SAK))
    aktiv = claim_next(saksbehandler, claimable, prefer=prefer)
    st.session_state[AKTIV_SAK] = encode_sak(aktiv)
    egen = egen_kostatus(saksbehandler, keys)

    if aktiv is None:
        render_live_fremdrift(
            saksbehandler, keys, claimable=claimable
        )
        if samples.empty:
            st.info(
                "Det er ingen aktive datagrunnlag i k\u00f8en. "
                "Be administrasjon legge til eller sl\u00e5 p\u00e5 et grunnlag."
            )
            return
        if not claimable:
            st.info(
                "Du har ingen tildelte stikkpr\u00f8ver akkurat n\u00e5. "
                "Be administrasjon tildele saker til deg, eller til alle saksbehandlere."
            )
            return
        if egen["ferdig"] < egen["total"]:
            st.info(
                "De siste sakene er hos en kollega akkurat n\u00e5. "
                "Ferdig-tallet oppdateres fortl\u00f8pende, og du f\u00e5r neste sak n\u00e5r den blir ledig."
            )
            return
        feir_key = "feiret_ko_" + saksbehandler
        if not st.session_state.get(feir_key):
            st.balloons()
            st.session_state[feir_key] = True
        st.success(
            "K\u00f8en er tom, {name}. Du har vurdert {n} saker. Takk for innsatsen.".format(
                name=fornavn, n=egen["mine"]
            ),
            icon=":material/celebration:",
        )
        return

    kilde_id, sample_nr = aktiv
    match = samples[
        (samples["_kilde_id"].astype(str) == kilde_id)
        & (samples[SAMPLE_ID_COL].astype(str) == sample_nr)
    ]
    if match.empty:
        st.session_state.pop(AKTIV_SAK, None)
        st.rerun()
    row = match.iloc[0]

    render_live_fremdrift(saksbehandler, keys, sample_nr, kilde_id=kilde_id)
    person_id = as_text(row.get("spk_person_id_kilde"), "")

    saved = get_assessment(sample_nr, saksbehandler, kilde_id=kilde_id)
    draft = dict(saved or {})
    draft.update(st.session_state.get("utkast_" + encode_sak(aktiv)) or {})

    with st.container(key="vurdering_arbeid"):
        sak_col, skjema_col = st.columns([0.95, 1.25], gap="medium")
        with sak_col:
            with st.container(key="sak_kolonne"):
                st.subheader("Denne stikkpr\u00f8ven", anchor=False)
                render_copyable_id(person_id)
                render_ada_keys(row)

        with skjema_col:
            with st.container(key="vurderingsskjema"):
                render_vurderingsskjema(
                    saksbehandler, sample_nr, row, draft, kilde_id=kilde_id
                )
