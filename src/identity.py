from __future__ import annotations

import os


def _user_field(user: object) -> str:
    data: dict = {}
    to_dict = getattr(user, "to_dict", None)
    if callable(to_dict):
        try:
            data = dict(to_dict() or {})
        except Exception:
            data = {}
    for key in ("user_name", "userName", "login_name", "email"):
        value = data.get(key)
        if not value:
            try:
                value = user[key]  # type: ignore[index]
            except Exception:
                value = getattr(user, key, None)
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "null"}:
            return text
    return ""


def _streamlit_viewer() -> str:
    try:
        import streamlit as st
    except Exception:
        return ""
    for name in ("user", "experimental_user"):
        try:
            user = getattr(st, name)
        except Exception:
            continue
        if user is None:
            continue
        found = _user_field(user)
        if found:
            return found
    return ""


def current_login() -> str:
    """Viewer in Streamlit in Snowflake. CURRENT_USER() is the app owner, so it is not used."""
    viewer = _streamlit_viewer()
    if viewer:
        return viewer
    return os.getenv("STIKKPROVE_USER", "").strip()


def is_admin_login(login: str | None = None) -> bool:
    name = (current_login() if login is None else login).strip()
    if not name:
        return False
    want = name.lower()
    for part in os.getenv("STIKKPROVE_ADMIN_USERS", "").split(","):
        if part.strip().lower() == want:
            return True
    from src.store import list_admin_logins

    for item in list_admin_logins():
        if item.lower() == want:
            return True
    return False


def reviewer_for_login(login: str) -> str:
    want = str(login or "").strip().lower()
    if not want:
        return ""
    from src.store import list_reviewer_records

    for row in list_reviewer_records():
        bruker = str(row.get("snowflake_bruker") or "").strip().lower()
        if bruker and bruker == want:
            return str(row.get("navn") or "")
    return ""
