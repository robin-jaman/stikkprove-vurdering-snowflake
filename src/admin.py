from __future__ import annotations

import hmac
import re
import time
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from src.config import ADMIN_PIN, SAMPLE_ID_COL, queue_refresh_seconds
from src.loader import (
    ensure_default_sources,
    load_source_frame,
)
from src.store import (
    ASSIGN_ALL,
    add_admin,
    add_reviewer,
    assignment_labels,
    completed_ids,
    format_oslo,
    kvitter_writeback_failures,
    list_admin_events,
    list_admin_logins,
    list_assessments,
    list_reviewer_records,
    list_reviewers,
    list_sources,
    log_admin_event,
    nullstill_lesinger,
    remove_reviewer,
    reviewer_progress,
    sample_keys,
    set_assignments,
    set_setting,
    sources_cache_key,
    writeback_failures,
)
from src.ui import _cached_samples

CSS = """
<style>
    .block-container { padding-top: 1.1rem; max-width: 960px; }
    [data-testid="InputInstructions"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
    }
    .st-key-admin_faner [role="tablist"] {
        display: flex !important;
        width: 100% !important;
        gap: 0.28rem !important;
        background: #dce6f2 !important;
        border: 1px solid #b3c4d8 !important;
        border-radius: 0.7rem !important;
        padding: 0.32rem !important;
        margin-bottom: 0.35rem !important;
    }
    .st-key-admin_faner [data-testid="stTab"] {
        flex: 1 1 0 !important;
        justify-content: center !important;
        text-align: center !important;
        min-height: 2.55rem !important;
        font-weight: 650 !important;
        color: #1b3654 !important;
        background: transparent !important;
        border-radius: 0.45rem !important;
        border: 0 !important;
        box-shadow: none !important;
    }
    .st-key-admin_faner [data-testid="stTab"] p {
        text-align: center !important;
        margin: 0 !important;
        font-weight: 650 !important;
        font-size: 0.95rem !important;
        color: inherit !important;
    }
    .st-key-admin_faner [data-testid="stTab"][aria-selected="true"] {
        background: #ffffff !important;
        color: #0b2540 !important;
        box-shadow: 0 1px 3px rgba(15, 40, 70, 0.16) !important;
    }
    .st-key-admin_faner .react-aria-SelectionIndicator,
    .st-key-admin_faner [role="tablist"] + *,
    .st-key-admin_faner [class*="e1ac7blb2"] {
        border-bottom: 0 !important;
    }
    .st-key-admin_faner .react-aria-SelectionIndicator {
        display: none !important;
    }
</style>
"""

ADMIN_ULAST = "admin_ulast"


def _forventet_pin() -> str:
    try:
        verdi = st.secrets.get("admin_pin")
        if verdi:
            return str(verdi)
    except Exception:
        pass
    return str(ADMIN_PIN)


def _riktig_pin(gitt: str) -> bool:
    forventet = _forventet_pin()
    kandidat = str(gitt or "").strip()
    if not kandidat or len(kandidat) != len(forventet):
        return False
    return hmac.compare_digest(kandidat.encode("utf-8"), forventet.encode("utf-8"))


def _render_admin_pin() -> None:
    with st.sidebar:
        st.info(
            "Denne siden er **bare for administrasjon**. "
            "Saksbehandlere skal holde seg p\u00e5 **Vurdering**."
        )
    st.title("Administrasjon")
    from src.identity import current_login, is_admin_login

    login = current_login()
    if login and is_admin_login(login):
        if st.button("\u00c5pne som " + login, type="primary"):
            st.session_state[ADMIN_ULAST] = True
            st.session_state.pop("admin_tvang_laas", None)
            st.rerun()
        st.caption("Eller bruk PIN.")
    st.write("Skriv inn PIN for \u00e5 \u00e5pne siden.")
    with st.form("admin_pin_skjema"):
        pin = st.text_input("PIN", type="password", max_chars=12)
        sendt = st.form_submit_button(
            "\u00c5pne administrasjon",
            type="primary",
            icon=":material/lock_open:",
        )
    if sendt:
        if _riktig_pin(pin):
            st.session_state[ADMIN_ULAST] = True
            st.session_state.pop("admin_tvang_laas", None)
            st.rerun()
        st.error("Feil PIN. Pr\u00f8v igjen.")


def _snowflake_ready() -> bool:
    from src.snowflake_client import snowflake_configured

    return snowflake_configured()


@st.dialog("Slett saksbehandler?")
def _confirm_remove_reviewer(navn: str) -> None:
    st.write("Er du sikker p\u00e5 at du vil fjerne **" + navn + "** fra listen?")
    st.caption(
        "Navnet forsvinner fra nedtrekkslisten p\u00e5 Vurdering. "
        "Lagrede vurderinger beholdes."
    )
    avbryt, slett = st.columns(2)
    with avbryt:
        if st.button("Avbryt", width="stretch", key="avbryt_slett_saksbehandler"):
            st.rerun()
    with slett:
        if st.button(
            "Ja, slett",
            type="primary",
            width="stretch",
            key="bekreft_slett_saksbehandler",
        ):
            remove_reviewer(navn)
            log_admin_event("Fjernet saksbehandler " + navn + ".")
            st.rerun()


def _active_samples():
    try:
        ensure_default_sources()
        samples, warnings = _cached_samples(sources_cache_key())
        return samples, warnings, None
    except Exception as exc:
        return pd.DataFrame(), [], exc


def _export_filename(tag: str, suffix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tag) or "alle"
    return "vurderinger_" + safe + "_" + stamp + suffix


def _logg_nedlasting(
    n: int, fmt: str, hvem: str = "alle", kilde: str = "alle"
) -> None:
    deler = []
    if kilde and kilde != "alle":
        deler.append("grunnlag " + kilde)
    if hvem and hvem != "alle":
        deler.append(hvem)
    if not deler:
        log_admin_event("Lastet ned alle svar som " + fmt + " (" + str(n) + " rader).")
    else:
        log_admin_event(
            "Lastet ned svar som "
            + fmt
            + " for "
            + ", ".join(deler)
            + " ("
            + str(n)
            + " rader)."
        )


def _vis_kolonnesjekk(kolonner: list[str]) -> None:
    """Viser hvilke av appens kolonner som ble funnet i tabellen."""
    from src.kolonner import SVARKOLONNER, gjenkjente, manglende

    savnet = manglende(kolonner)
    if savnet:
        st.error(
            "Tabellen mangler kolonnen "
            + ", ".join(savnet)
            + ". Appen finner ikke stikkpr\u00f8vene uten den."
        )
    else:
        st.success("Fant " + SAMPLE_ID_COL + ", s\u00e5 k\u00f8en kan fylles.")

    funnet = gjenkjente(kolonner)
    svar_funnet = [navn for navn in funnet if navn in set(SVARKOLONNER)]
    st.caption(
        "Tabellen har "
        + str(len(kolonner))
        + " kolonner. Appen kjenner igjen "
        + str(len(funnet))
        + " av dem, derav "
        + str(len(svar_funnet))
        + " av "
        + str(len(SVARKOLONNER))
        + " svarkolonner."
    )
    with st.expander("Kolonner i tabellen"):
        st.dataframe(
            pd.DataFrame(
                {
                    "kolonne": kolonner,
                    "brukes av appen": [
                        "ja" if _kjent(kolonne) else "nei" for kolonne in kolonner
                    ],
                }
            ),
            hide_index=True,
            width="stretch",
        )


def _kjent(kolonne: str) -> bool:
    from src.kolonner import KJENTE_KOLONNER, forenkle

    return forenkle(kolonne) in {forenkle(navn) for navn in KJENTE_KOLONNER}


def _render_snowflake_query(source_id: str) -> None:
    from src.snowflake_client import (
        QUERY_SETTING,
        sample_query,
        set_source_table,
        set_writeback,
        source_table,
        table_columns,
        writeback_enabled,
    )

    with st.expander("Kildetabell", expanded=not source_table()):
        tabell = st.text_input(
            "Tabellen stikkpr\u00f8vene ligger i",
            value=source_table(),
            key="sf_tabell_" + source_id,
            placeholder="DATABASE.SCHEMA.TABELL",
        )
        st.caption(
            "Skriv hele navnet med database og schema. Appen finner kolonnene selv, "
            "ogs\u00e5 n\u00e5r de heter STIKKPROVE_NR i stedet for " + SAMPLE_ID_COL + "."
        )
        lagre_col, test_col = st.columns(2)
        with lagre_col:
            if st.button("Lagre tabell", key="lagre_sf_tabell_" + source_id, width="stretch"):
                set_source_table(tabell)
                _cached_samples.clear()
                log_admin_event("Satte Snowflake-kildetabell til " + str(tabell) + ".")
                st.rerun()
        with test_col:
            if st.button("Sjekk tabell", key="sjekk_sf_tabell_" + source_id, width="stretch"):
                try:
                    _vis_kolonnesjekk(table_columns(tabell))
                except Exception as exc:
                    st.error(str(exc))

        st.divider()
        paa = st.toggle(
            "Skriv svarene tilbake til raden i denne tabellen",
            value=writeback_enabled(),
            key="sf_tilbake_" + source_id,
        )
        if paa != writeback_enabled():
            set_writeback(paa)
            log_admin_event(
                "Sl\u00e5tt " + ("p\u00e5" if paa else "av") + " tilbakeskriving til kildetabellen."
            )
            st.rerun()
        st.caption(
            "Da oppdaterer appen svarkolonnene i raden stikkpr\u00f8ven kom fra. "
            "\u00c9n stikkpr\u00f8ve kan bare ha ett svar."
        )

    with st.expander("Egen sp\u00f8rring"):
        ny = st.text_area(
            "SQL som henter stikkpr\u00f8vene",
            value=sample_query(),
            key="sf_query_" + source_id,
            height=120,
        )
        st.caption(
            "Trengs bare hvis du vil filtrere eller koble sammen tabeller. "
            "St\u00e5r det noe her, overstyrer det tabellnavnet over. "
            "Sp\u00f8rringen m\u00e5 returnere kolonnen " + SAMPLE_ID_COL + "."
        )
        lagre_col, test_col = st.columns(2)
        with lagre_col:
            if st.button("Lagre sp\u00f8rring", key="lagre_sf_query_" + source_id, width="stretch"):
                set_setting(QUERY_SETTING, ny)
                _cached_samples.clear()
                log_admin_event("Endret Snowflake-sp\u00f8rringen.")
                st.rerun()
        with test_col:
            if st.button("Test sp\u00f8rring", key="test_sf_query_" + source_id, width="stretch"):
                try:
                    frame = load_source_frame(
                        {"source_id": source_id, "name": "Snowflake", "kind": "snowflake"}
                    )
                    st.success("Sp\u00f8rringen ga " + str(len(frame)) + " stikkpr\u00f8ver.")
                except Exception as exc:
                    st.error(str(exc))


def _render_oppfrisk() -> None:
    """Leser grunnlagene paa nytt, slik at nye stikkproever kommer i koen."""
    minutter = max(1, round(queue_refresh_seconds() / 60))
    knapp, tekst = st.columns([1.3, 2.7])
    with knapp:
        if st.button(
            "Oppdater k\u00f8en n\u00e5",
            icon=":material/refresh:",
            width="stretch",
            key="oppfrisk_koen",
        ):
            _cached_samples.clear()
            log_admin_event("Leste datagrunnlagene p\u00e5 nytt.")
            st.rerun()
    with tekst:
        st.caption(
            "Appen leser kildene p\u00e5 nytt av seg selv hvert "
            + str(minutter)
            + ". minutt. Trykk her hvis nye stikkpr\u00f8ver skal i k\u00f8en med en gang. "
            "Svar som allerede er lagret, blir st\u00e5ende."
        )


def _render_source(samples: pd.DataFrame, warnings: list[str], error: Exception | None) -> None:
    from src.snowflake_client import source_table

    if error is not None:
        st.warning(str(error))
    for warning in warnings:
        st.warning(warning)
    st.write(
        "Alle stikkpr\u00f8ver hentes fra \u00e9n tabell i Snowflake. "
        "Nye stikkpr\u00f8ver legges inn i tabellen utenfor appen, og kommer i k\u00f8en "
        "n\u00e5r den leses p\u00e5 nytt. Fordel dem p\u00e5 saksbehandlere under **Tildeling**."
    )
    sources = list_sources()
    if not sources:
        st.error(
            "Datagrunnlaget er ikke registrert. Last siden p\u00e5 nytt, og sjekk at appen "
            "f\u00e5r opprette hjelpetabellene sine."
        )
        return
    source_id = str(sources[0]["source_id"])
    st.metric("Stikkpr\u00f8ver i tabellen", len(samples))
    st.caption("Leser fra " + (source_table() or "sp\u00f8rringen nedenfor") + ".")
    _render_oppfrisk()
    _render_snowflake_query(source_id)


TILDING_OK_SEKUNDER = 8


@st.fragment(run_every=1)
def _tildeling_bekreftelse() -> None:
    tekst = str(st.session_state.get("tildeling_ok") or "")
    if not tekst:
        return
    start = st.session_state.get("tildeling_ok_at")
    now = time.time()
    if start is None:
        start = now
        st.session_state["tildeling_ok_at"] = start
    if now - float(start) >= TILDING_OK_SEKUNDER:
        st.session_state.pop("tildeling_ok", None)
        st.session_state.pop("tildeling_ok_at", None)
        return
    st.success(tekst, icon=":material/check_circle:")


FORDEL = "Fordel stikkpr\u00f8vene mellom saksbehandlerne"
ALLE = "La alle se hele bunken"
EN = "Gi hele bunken til \u00e9n saksbehandler"

HELE = "Alle sammen"
ANTALL = "Et antall om gangen"
NUMRE = "Bestemte stikkpr\u00f8venummer"


def _fordel_likt(keys: list, mottakere: list[str]) -> dict[str, list]:
    """Deler stikkproevene i like store, sammenhengende bunker."""
    bunker: dict[str, list] = {}
    start = 0
    for i, navn in enumerate(mottakere):
        slutt = start + len(keys) // len(mottakere) + (1 if i < len(keys) % len(mottakere) else 0)
        bunker[navn] = keys[start:slutt]
        start = slutt
    return bunker


def _utsnitt(keys: list, start: int, antall: int) -> list:
    """Bunken fra og med plass ``start``, talt fra 1, og ``antall`` videre.

    Plassen telles i koen, ikke i stikkproevenumrene, for numrene trenger
    hverken aa starte paa 1 eller aa henge sammen.
    """
    forste = max(int(start), 1) - 1
    return keys[forste : forste + max(int(antall), 0)]


# Et spenn kan ikke vaere stoerre enn dette. Uten taket ville en skrivefeil som
# 1-99999999 brukt all hukommelsen paa aa lage numre som ikke finnes.
SPENNTAK = 100000


def _nummernokkel(nr: object) -> str:
    """Nummeret paa en form som taaler ledende nuller og store bokstaver."""
    tekst = str(nr).strip()
    return str(int(tekst)) if tekst.isdigit() else tekst.lower()


def _tolk_numre(tekst: str) -> tuple[list[str], list[str]]:
    """Tolker "201-300, 405" som en liste med numre.

    Returnerer numrene og de bitene som ikke gav mening, slik at brukeren faar
    vite om en skrivefeil i stedet for aa tildele feil bunke.
    """
    numre: list[str] = []
    ubrukelige: list[str] = []
    for bit in re.split(r"[,;\s]+", str(tekst or "").strip()):
        if not bit:
            continue
        spenn = re.fullmatch(r"(\d+)\s*[-\u2013]\s*(\d+)", bit)
        if spenn:
            fra, til = int(spenn.group(1)), int(spenn.group(2))
            if fra > til:
                fra, til = til, fra
            if til - fra >= SPENNTAK:
                ubrukelige.append(bit)
                continue
            numre.extend(str(nr) for nr in range(fra, til + 1))
        elif "-" in bit and not bit.replace("-", "").isalnum():
            ubrukelige.append(bit)
        else:
            numre.append(bit)
    return numre, ubrukelige


def _velg_numre(keys: list, numre: list[str]) -> tuple[list, list[str]]:
    """Stikkproevene i ``keys`` som har et av numrene, i koens rekkefoelge.

    Returnerer ogsaa numrene som ikke ble funnet. De er enten tildelt fra for,
    eller de finnes ikke i tabellen.
    """
    onsket = {_nummernokkel(nr) for nr in numre}
    valgt = [key for key in keys if _nummernokkel(key[1]) in onsket]
    funnet = {_nummernokkel(key[1]) for key in valgt}
    mangler = [nr for nr in dict.fromkeys(numre) if _nummernokkel(nr) not in funnet]
    return valgt, mangler


def _forkortet(deler: list[str], tak: int = 10) -> str:
    """Holder cellen lesbar naar bunken er stykket opp i mange spenn."""
    if len(deler) <= tak:
        return ", ".join(deler)
    return ", ".join(deler[:tak]) + " og " + str(len(deler) - tak) + " til"


def _nummerspenn(numre: list[str]) -> str:
    """Numrene skrevet som spenn, for eksempel "1-100, 205, 310-312".

    Bunkene deles ut sammenhengende, saa spenn gjoer en lang liste lesbar.
    Numre som ikke er tall, settes opp slik de er.
    """
    if not numre:
        return ""
    try:
        tall = sorted({int(str(nr)) for nr in numre})
    except ValueError:
        return _forkortet(sorted({str(nr) for nr in numre}))
    spenn: list[str] = []
    start = forrige = tall[0]
    for nr in tall[1:]:
        if nr == forrige + 1:
            forrige = nr
            continue
        spenn.append(str(start) if start == forrige else str(start) + "-" + str(forrige))
        start = forrige = nr
    spenn.append(str(start) if start == forrige else str(start) + "-" + str(forrige))
    return _forkortet(spenn)


def _tildelte_per_person(labels: dict) -> pd.DataFrame:
    per_navn: dict[str, list[str]] = {}
    for key, navn in labels.items():
        per_navn.setdefault(navn, []).append(str(key[1]))
    return pd.DataFrame(
        [
            {
                "Tildelt til": navn,
                "Stikkpr\u00f8ver": len(numre),
                "Stikkpr\u00f8venummer": _nummerspenn(numre),
            }
            for navn, numre in sorted(per_navn.items())
        ]
    )


def _render_antall(hele: list) -> list:
    """Lar brukeren ta en bunke av gangen, talt i plasser i koen."""
    start_col, antall_col = st.columns(2)
    with start_col:
        start = st.number_input(
            "Start p\u00e5 plass nr.",
            min_value=1,
            max_value=len(hele),
            value=1,
            step=1,
            help="Plassen i k\u00f8en, ikke stikkpr\u00f8venummeret.",
        )
    with antall_col:
        antall = st.number_input(
            "Hvor mange",
            min_value=1,
            max_value=len(hele),
            value=min(100, len(hele)),
            step=25,
        )
    maal = _utsnitt(hele, int(start), int(antall))
    if maal:
        st.caption(
            "Dette er "
            + str(len(maal))
            + " stikkpr\u00f8ver, fra nr. "
            + str(maal[0][1])
            + " til nr. "
            + str(maal[-1][1])
            + ". N\u00e5r de er tildelt, forsvinner de ut av felles k\u00f8, "
            + "og de neste ligger \u00f8verst neste gang."
        )
    return maal


def _render_numre(hele: list, bare_felles: bool) -> list:
    """Lar brukeren skrive numrene selv, for eksempel 201-300."""
    tekst = st.text_input(
        "Stikkpr\u00f8venummer",
        placeholder="201-300, 405, 410-420",
        help="Enkeltnummer eller spenn, atskilt med komma.",
    )
    if not str(tekst).strip():
        return []
    numre, ubrukelige = _tolk_numre(tekst)
    if ubrukelige:
        st.warning("Forstod ikke: " + ", ".join(ubrukelige) + ".")
    maal, mangler = _velg_numre(hele, numre)
    if maal:
        st.caption(
            "Dette er "
            + str(len(maal))
            + " stikkpr\u00f8ver: "
            + _nummerspenn([str(key[1]) for key in maal])
            + "."
        )
    if mangler:
        if bare_felles:
            hvorfor = (
                " De er enten tildelt fra f\u00f8r, og da m\u00e5 du velge **alle "
                "stikkpr\u00f8ver i k\u00f8en** over, eller s\u00e5 finnes de ikke i tabellen."
            )
        else:
            hvorfor = " De finnes ikke i tabellen."
        st.caption(
            "Ikke med i utvalget: "
            + _forkortet([str(nr) for nr in mangler])
            + "."
            + hvorfor
        )
    return maal


def _render_assignments(samples: pd.DataFrame, names: list[str]) -> None:
    st.write(
        "Her fordeles stikkpr\u00f8vene i tabellen. Det som ikke er tildelt, ligger i "
        "felles k\u00f8 og kan plukkes av hvem som helst."
    )
    keys = sample_keys(samples)
    if not keys:
        st.info("Ingen stikkpr\u00f8ver i k\u00f8en enn\u00e5.")
        return
    labels = assignment_labels(keys)
    felles = [key for key in keys if labels[key] == "Felles k\u00f8"]
    tall = st.columns(3)
    tall[0].metric("I k\u00f8en", len(keys))
    tall[1].metric("Tildelt", len(keys) - len(felles))
    tall[2].metric("I felles k\u00f8", len(felles))
    st.dataframe(
        _tildelte_per_person(labels),
        hide_index=True,
        width="stretch",
        column_config={
            "Stikkpr\u00f8venummer": st.column_config.TextColumn(width="large"),
        },
    )
    with st.expander("Vis hver stikkpr\u00f8ve for seg"):
        st.caption(
            "Samme rekkef\u00f8lge som k\u00f8en. Klikk p\u00e5 en kolonne for \u00e5 sortere, "
            "eller s\u00f8k i tabellen med forst\u00f8rrelsesglasset."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Stikkpr\u00f8ve": key[1], "Tildelt til": labels[key]}
                    for key in keys
                ]
            ),
            hide_index=True,
            width="stretch",
            height=320,
        )

    if not names:
        st.info("Registrer saksbehandlere under **Saksbehandlere** f\u00f8r du tildeler.")
        return

    bare_felles_tekst = "Bare de i felles k\u00f8 (" + str(len(felles)) + ")"
    valg = st.radio(
        "Hvilke stikkpr\u00f8ver skal tildeles?",
        [bare_felles_tekst, "Alle stikkpr\u00f8ver i k\u00f8en (" + str(len(keys)) + ")"],
    )
    bare_felles = valg == bare_felles_tekst
    hele = felles if bare_felles else keys
    maal = hele
    plukk = st.radio("Hvilken del av dem?", [HELE, ANTALL, NUMRE], horizontal=True)
    if plukk == ANTALL and hele:
        maal = _render_antall(hele)
    elif plukk == NUMRE:
        maal = _render_numre(hele, bare_felles)

    modus = st.radio("Hvordan skal de tildeles?", [FORDEL, ALLE, EN])
    mottakere: list[str] = []
    if modus == FORDEL:
        mottakere = st.multiselect(
            "Saksbehandlere som skal dele bunken",
            names,
            default=names,
        )
    elif modus == EN:
        mottakere = [st.selectbox("Saksbehandler", names)]

    if not maal:
        st.caption("Ingen stikkpr\u00f8ver i dette utvalget.")
        return
    if modus != ALLE and not mottakere:
        st.caption("Velg minst \u00e9n saksbehandler.")
        return
    if modus == FORDEL:
        st.caption(
            "Fordeling: "
            + ", ".join(
                navn + " " + str(len(bunke))
                for navn, bunke in _fordel_likt(maal, mottakere).items()
            )
        )

    if st.button("Tildel", type="primary"):
        if modus == ALLE:
            set_assignments(maal, [ASSIGN_ALL])
            tekst = str(len(maal)) + " stikkpr\u00f8ver er \u00e5pne for alle saksbehandlere."
        elif modus == EN:
            set_assignments(maal, mottakere)
            tekst = str(len(maal)) + " stikkpr\u00f8ver er tildelt " + mottakere[0] + "."
        else:
            bunker = _fordel_likt(maal, mottakere)
            for navn, bunke in bunker.items():
                if bunke:
                    set_assignments(bunke, [navn])
            tekst = (
                str(len(maal))
                + " stikkpr\u00f8ver er fordelt p\u00e5 "
                + ", ".join(
                    navn + " (" + str(len(bunke)) + ")"
                    for navn, bunke in bunker.items()
                    if bunke
                )
                + "."
            )
        log_admin_event(tekst)
        st.session_state["tildeling_ok"] = tekst
        st.session_state["tildeling_ok_at"] = time.time()
        st.rerun()


def _render_reviewers(names: list[str]) -> None:
    st.write(
        "Navnene her vises i nedtrekkslisten p\u00e5 siden Vurdering. "
        "Bruk n\u00f8yaktig samme skrivem\u00e5te som skal lagres i kilden."
    )
    records = list_reviewer_records()
    if records:
        st.dataframe(
            pd.DataFrame(records).rename(
                columns={"navn": "Navn", "snowflake_bruker": "Snowflake-bruker"}
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "Snowflake-bruker er valgfri. N\u00e5r appen kj\u00f8rer i Snowflake, "
        "knyttes den innloggede brukeren til navnet automatisk. "
        "Registrerer du et navn som finnes fra f\u00f8r, oppdateres bare Snowflake-brukeren."
    )
    add_col, remove_col = st.columns(2)
    with add_col:
        new_name = st.text_input("Legg til navn", placeholder="F.eks. Kari Nordmann")
        snowflake_bruker = st.text_input(
            "Snowflake-bruker (valgfri)",
            placeholder="F.eks. KARI.NORDMANN",
        )
        if st.button("Registrer saksbehandler"):
            try:
                status = add_reviewer(new_name, snowflake_bruker=snowflake_bruker)
                visningsnavn = " ".join(new_name.split())
                if status == "updated":
                    log_admin_event(
                        "Oppdaterte Snowflake-bruker for saksbehandler " + visningsnavn + "."
                    )
                else:
                    log_admin_event("Registrerte saksbehandler " + visningsnavn + ".")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with remove_col:
        if names:
            to_remove = st.selectbox("Fjern navn", names)
            if st.button("Fjern saksbehandler"):
                _confirm_remove_reviewer(to_remove)
        else:
            st.info("Ingen saksbehandlere er registrert enn\u00e5.")
    from src.identity import current_login

    st.subheader("Administratorer", anchor=False)
    st.caption(
        "Snowflake-brukere her \u00e5pner Administrasjon uten PIN n\u00e5r appen kj\u00f8rer i Snowflake. "
        "PIN virker fortsatt, ogs\u00e5 lokalt."
    )
    login = current_login()
    if login:
        st.write("Innlogget Snowflake-bruker: **" + login + "**")
        if st.button("Gi denne brukeren administrasjon uten PIN"):
            add_admin(login)
            log_admin_event("La til administrator " + login + ".")
            st.rerun()
    else:
        st.caption("Brukernavnet vises her n\u00e5r appen kj\u00f8rer i Snowflake.")
    admins = list_admin_logins()
    if admins:
        st.write("Uten PIN: " + ", ".join(admins))


VIS_SVAR = "vis_svartabellen"


def _render_progress_and_export(keys: list, names: list[str], vurdert: int) -> None:
    st.caption(
        str(vurdert)
        + " av "
        + str(len(keys))
        + " stikkpr\u00f8ver i k\u00f8en er ferdig vurdert."
    )

    st.subheader("Per saksbehandler", anchor=False)
    st.caption(
        "Tabellen viser hver persons innsats p\u00e5 tvers av grunnlagene de er tildelt."
    )
    progress = reviewer_progress(keys)
    if progress.empty:
        st.caption("Registrer saksbehandlere for \u00e5 se fremdrift per person.")
    else:
        st.dataframe(
            progress,
            hide_index=True,
            width="stretch",
            column_config={
                "tildelt": "Tildelt",
                "vurdert": "Vurdert",
                "andel": st.column_config.ProgressColumn(
                    "andel", min_value=0, max_value=1, format="percent"
                ),
                "siste_vurdering_fullfort": st.column_config.TextColumn(
                    "Dato og tid siste vurdering fullf\u00f8rt",
                    help="Tidspunkt for siste lagrede vurdering, Oslo-tid.",
                ),
            },
        )

    if not st.session_state.get(VIS_SVAR):
        st.subheader("Svarfordeling og nedlasting", anchor=False)
        st.caption(
            "Hele svartabellen hentes ikke av seg selv. Den er den tyngste "
            "sp\u00f8rringen appen gj\u00f8r, og den trengs bare her."
        )
        if st.button("Hent svarene", icon=":material/table:", type="primary"):
            st.session_state[VIS_SVAR] = True
            st.rerun()
        return

    answers = list_assessments()
    if not answers.empty:
        st.subheader("Svarfordeling", anchor=False)
        dist_cols = st.columns(2)
        with dist_cols[0]:
            st.caption("Historisk korrekt?")
            st.bar_chart(answers["historisk_korrekt"].value_counts())
        with dist_cols[1]:
            st.caption("Vanlighet")
            st.bar_chart(answers["vanlighet"].value_counts())
        if "varselkode" in answers.columns:
            st.caption("Svar per varselkode")
            st.bar_chart(answers["varselkode"].fillna("(tom)").value_counts())

    st.subheader("Hent ferdige vurderinger", anchor=False)
    st.write(
        "Last ned lagrede svar som Excel eller CSV her. "
        "Filen f\u00f8lger filtrene under. La dem st\u00e5 p\u00e5 Alle for \u00e5 hente alt."
    )
    if answers.empty:
        st.info(
            "Ingen vurderinger er lagret enn\u00e5. "
            "Excel-nedlasting blir tilgjengelig n\u00e5r det finnes svar."
        )
        st.caption("Aktive grunnlag ligger under Datagrunnlag.")
        return

    sources = list_sources()
    grunnlag_navn = [str(src["name"]) for src in sources]
    if "kilde" in answers.columns:
        extra_kilder = sorted(
            {
                str(navn).strip()
                for navn in answers["kilde"].astype(str)
                if str(navn).strip() and str(navn).strip() not in grunnlag_navn
            }
        )
        grunnlag_navn = grunnlag_navn + extra_kilder
    extra_sb = sorted(set(answers["saksbehandler"].astype(str)) - set(names))
    kilde_col, sb_col = st.columns(2)
    with kilde_col:
        chosen_kilde = st.selectbox(
            "Filtrer p\u00e5 grunnlag",
            ["Alle"] + grunnlag_navn,
            key="filter_grunnlag",
        )
    with sb_col:
        chosen_sb = st.selectbox(
            "Filtrer p\u00e5 saksbehandler",
            ["Alle"] + names + extra_sb,
            key="filter_saksbehandler",
        )
    visning = answers
    if chosen_kilde != "Alle":
        kilde_ids = [
            str(src["source_id"]) for src in sources if str(src["name"]) == chosen_kilde
        ]
        treff = None
        if "kilde" in visning.columns:
            treff = visning["kilde"].astype(str) == chosen_kilde
        if kilde_ids and "kilde_id" in visning.columns:
            id_treff = visning["kilde_id"].astype(str).isin(kilde_ids)
            treff = id_treff if treff is None else (treff | id_treff)
        visning = visning[treff] if treff is not None else visning.iloc[0:0]
    if chosen_sb != "Alle":
        visning = visning[visning["saksbehandler"].astype(str) == chosen_sb]
    if visning.empty:
        st.info("Ingen svar matcher filteret.")
        return
    st.dataframe(visning, hide_index=True, width="stretch")
    csv_bytes = visning.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
    tag_deler = []
    if chosen_kilde != "Alle":
        tag_deler.append(chosen_kilde)
    if chosen_sb != "Alle":
        tag_deler.append(chosen_sb)
    file_tag = "_".join(tag_deler) if tag_deler else "alle"
    logg_kilde = "alle" if chosen_kilde == "Alle" else chosen_kilde
    logg_sb = "alle" if chosen_sb == "Alle" else chosen_sb
    excel_col, csv_col = st.columns(2)
    with excel_col:
        try:
            excel_data = _excel_bytes(visning)
        except Exception:
            # Uten openpyxl skal resten av siden fortsatt virke.
            excel_data = None
        if excel_data is None:
            st.button(
                "Last ned svar som Excel",
                disabled=True,
                width="stretch",
                key="fremdrift_excel_av",
            )
            st.caption("Excel krever pakken openpyxl. Bruk CSV s\u00e5 lenge.")
        elif st.download_button(
            "Last ned svar som Excel",
            excel_data,
            _export_filename(file_tag, ".xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch",
            key="fremdrift_excel",
        ):
            _logg_nedlasting(len(visning), "Excel", hvem=logg_sb, kilde=logg_kilde)
    with csv_col:
        if st.download_button(
            "Last ned svar som CSV",
            csv_bytes,
            _export_filename(file_tag, ".csv"),
            "text/csv",
            width="stretch",
            key="fremdrift_csv",
        ):
            _logg_nedlasting(len(visning), "CSV", hvem=logg_sb, kilde=logg_kilde)
    st.caption(
        "Excel og CSV kan lastes ned her uansett om svarene ligger lokalt eller i Snowflake. "
        "Kolonnen kilde viser hvilket grunnlag svaret h\u00f8rer til."
    )


def _render_tilbakeskrivingsfeil() -> None:
    """Varsler om svar som ble lagret, men som aldri naadde kildetabellen.

    Varselet staar oeverst paa siden til noen kvitterer det ut, slik at feilen
    ikke blir liggende ulest i endringsloggen.
    """
    feil = writeback_failures()
    if not feil:
        return
    nyeste = feil[0]
    tid = format_oslo(nyeste["happened_at"]) or nyeste["happened_at"]
    if len(feil) == 1:
        innledning = "Ett svar ble lagret, men n\u00e5dde ikke kildetabellen."
    else:
        innledning = (
            str(len(feil)) + " svar ble lagret, men n\u00e5dde ikke kildetabellen."
        )
    st.error(
        innledning
        + "\n\nSiste, "
        + tid
        + ": "
        + nyeste["tekst"]
        + "\n\nSvarene er trygge i appen, og kan skrives til kildetabellen p\u00e5 nytt "
        + "n\u00e5r \u00e5rsaken er rettet. Hele listen ligger under Endringshistorikk.",
        icon=":material/sync_problem:",
    )
    if st.button("Marker som sett", key="kvitter_tilbakeskriving"):
        kvitter_writeback_failures()
        st.rerun()


def _render_endringshistorikk() -> None:
    st.caption(
        "Hendelser i administrasjon, nyeste f\u00f8rst. "
        "Loggen viser filnavn, hvem som ble tildelt, og n\u00e5r svar er lastet ned."
    )
    events = list_admin_events(100)
    if not events:
        st.info("Ingen endringer er registrert enn\u00e5.")
        return
    rows = []
    for event in events:
        tid = format_oslo(event["happened_at"]) or event["happened_at"]
        rows.append({"Tidspunkt": tid, "Hendelse": event["tekst"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _excel_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="vurderinger")
    return buffer.getvalue()


def main() -> None:
    nullstill_lesinger()
    st.markdown(CSS, unsafe_allow_html=True)
    from src.identity import current_login, is_admin_login

    login = current_login()
    if st.session_state.get("admin_tvang_laas"):
        _render_admin_pin()
        return
    if not st.session_state.get(ADMIN_ULAST):
        if login and is_admin_login(login):
            st.session_state[ADMIN_ULAST] = True
        else:
            _render_admin_pin()
            return

    samples, warnings, error = _active_samples()
    names = list_reviewers()
    keys = sample_keys(samples)
    vurdert = len(completed_ids() & set(keys))

    with st.sidebar:
        st.info(
            "Denne siden er **bare for administrasjon**. "
            "Saksbehandlere skal holde seg p\u00e5 **Vurdering**."
        )
        if st.button("L\u00e5s administrasjon", icon=":material/lock:"):
            st.session_state[ADMIN_ULAST] = False
            st.session_state["admin_tvang_laas"] = True
            st.rerun()
    st.title("Administrasjon")

    oversikt = st.columns(3)
    oversikt[0].metric("Stikkpr\u00f8ver i k\u00f8en", len(keys))
    oversikt[1].metric("Ferdig", vurdert)
    oversikt[2].metric("Saksbehandlere", len(names))
    _render_tilbakeskrivingsfeil()
    # Fragmentet oppdaterer seg selv hvert sekund, saa det startes bare naar det
    # faktisk er en kvittering aa vise.
    if st.session_state.get("tildeling_ok"):
        _tildeling_bekreftelse()

    datagrunnlag, saksbehandlere, tildeling, fremdrift, historikk = st.tabs(
        [
            ":material/folder: Datagrunnlag",
            ":material/group: Saksbehandlere",
            ":material/assignment: Tildeling",
            ":material/analytics: Fremdrift og svar",
            ":material/history: Endringshistorikk",
        ]
    )
    with datagrunnlag:
        _render_source(samples, warnings, error)
    with saksbehandlere:
        _render_reviewers(names)
    with tildeling:
        _render_assignments(samples, names)
    with fremdrift:
        _render_progress_and_export(keys, names, vurdert)
    with historikk:
        _render_endringshistorikk()
