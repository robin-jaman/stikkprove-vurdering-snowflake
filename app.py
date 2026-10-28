from src.encoding_fix import ensure_utf8

try:
    ensure_utf8()
except OSError:
    pass

import streamlit as st

st.set_page_config(page_title="Stikkpr\u00f8vevurdering", page_icon="S", layout="wide")

MIN_STREAMLIT = (1, 51)


def _versjon(tekst: str) -> tuple[int, ...]:
    deler = []
    for bit in str(tekst).split(".")[:2]:
        siffer = "".join(ch for ch in bit if ch.isdigit())
        deler.append(int(siffer or 0))
    return tuple(deler)


if _versjon(st.__version__) < MIN_STREAMLIT:
    import sys

    st.error(
        "Appen trenger Streamlit "
        + ".".join(str(tall) for tall in MIN_STREAMLIT)
        + " eller nyere. Du kj\u00f8rer "
        + st.__version__
        + "."
    )
    st.write("Start appen med **start_app.bat**, eller fra prosjektmappen:")
    st.code(".\\.venv\\Scripts\\python.exe -m streamlit run app.py", language="powershell")
    st.caption("Kj\u00f8rer n\u00e5: " + sys.executable)
    st.stop()

from src import admin, ui


def vurdering() -> None:
    ui.main()


def administrasjon() -> None:
    admin.main()


sider = st.navigation(
    [
        st.Page(
            vurdering,
            title="Vurdering",
            icon=":material/rate_review:",
            default=True,
        ),
        st.Page(
            administrasjon,
            title="Administrasjon",
            icon=":material/admin_panel_settings:",
        ),
    ]
)
sider.run()


