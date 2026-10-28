"""Sjekker at alle st.*-kall finnes i den installerte Streamlit-versjonen.

Kjores med et miljo som har samme Streamlit som Snowflake, for aa fange opp
argumenter som bare finnes i nyere versjoner.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import streamlit as st


def sti_til(node: ast.AST) -> str | None:
    deler: list[str] = []
    while isinstance(node, ast.Attribute):
        deler.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name) and node.id == "st":
        return ".".join(reversed(deler))
    return None


def slaa_opp(sti: str):
    obj = st
    for del_ in sti.split("."):
        obj = getattr(obj, del_, None)
        if obj is None:
            return None
    return obj


def godkjente(obj) -> tuple[set[str], bool]:
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return set(), True
    navn = set()
    fritt = False
    for p in sig.parameters.values():
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            fritt = True
        else:
            navn.add(p.name)
    return navn, fritt


filer = [Path("app.py")] + sorted(Path("src").glob("*.py"))
avvik: list[str] = []

for fil in filer:
    tre = ast.parse(fil.read_text(encoding="utf-8"))
    for node in ast.walk(tre):
        if not isinstance(node, ast.Call):
            continue
        sti = sti_til(node.func)
        if sti is None:
            continue
        obj = slaa_opp(sti)
        if obj is None:
            avvik.append(f"{fil}:{node.lineno}: st.{sti} finnes ikke")
            continue
        navn, fritt = godkjente(obj)
        if fritt:
            continue
        for kw in node.keywords:
            if kw.arg and kw.arg not in navn:
                avvik.append(f"{fil}:{node.lineno}: st.{sti}(...) kjenner ikke '{kw.arg}'")

print("Streamlit", st.__version__)
for linje in avvik:
    print(linje)
print(len(avvik), "avvik")
sys.exit(1 if avvik else 0)
