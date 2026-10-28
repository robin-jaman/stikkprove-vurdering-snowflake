"""Maaler hvor mange databasekall en vanlig kjoring av appen gjor."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

from src import db as dbmod
from src import store

DB = Path("data/_maal.sqlite")
if DB.exists():
    DB.unlink()

antall = {"connect": 0, "spor": 0}
ekte_connect = dbmod.SqliteDb._connect
ekte_fetch = dbmod.SqliteDb._fetch
ekte_exec = dbmod.SqliteDb.execute


def tell_connect(self):
    antall["connect"] += 1
    return ekte_connect(self)


def tell_fetch(self, sql, params):
    antall["spor"] += 1
    return ekte_fetch(self, sql, params)


def tell_exec(self, sql, params=None):
    antall["spor"] += 1
    return ekte_exec(self, sql, params)


dbmod.SqliteDb._connect = tell_connect
dbmod.SqliteDb._fetch = tell_fetch
dbmod.SqliteDb.execute = tell_exec

antall["init"] = 0
antall["init_ms"] = 0.0
ekte_init = store.init_db


def tell_init(db_path=store.DB_PATH):
    antall["init"] += 1
    start = time.perf_counter()
    try:
        return ekte_init(db_path)
    finally:
        antall["init_ms"] += (time.perf_counter() - start) * 1000


store.init_db = tell_init

store.init_db(DB)
store.add_source("Snowflake", "snowflake", db_path=DB)
kilde = store.list_sources(DB)[0]["source_id"]
for navn in ["Kari Nordmann", "Ola Hansen", "Per Olsen"]:
    store.add_reviewer(navn, db_path=DB)

N = 100
keys = [(str(kilde), str(nr)) for nr in range(1, N + 1)]
samples = pd.DataFrame(
    {
        "stikkpr\u00f8ve_nr": [str(nr) for nr in range(1, N + 1)],
        "_kilde_id": [str(kilde)] * N,
        "_kilde_navn": ["Snowflake"] * N,
        "_kilde_kind": ["snowflake"] * N,
    }
)


def nullstill() -> None:
    antall["connect"] = 0
    antall["spor"] = 0
    antall["init"] = 0
    antall["init_ms"] = 0.0


def rapport(hva: str, sekunder: float) -> None:
    print(
        hva.ljust(34)
        + str(antall["spor"]).rjust(5)
        + " kall, init_db "
        + str(antall["init"]).rjust(3)
        + (" (%6.0f ms)" % antall["init_ms"])
        + ("%8.0f ms totalt" % (sekunder * 1000))
    )


# Tildeling av hele bunken.
nullstill()
start = time.perf_counter()
store.set_assignments(keys, ["Kari Nordmann"], db_path=DB)
rapport("tildel 100 stikkproever", time.perf_counter() - start)

# En vanlig kjoring av saksbehandlersiden.
nullstill()
start = time.perf_counter()
store.list_reviewers(DB)
store.list_sources(DB)
store.sources_cache_key(DB)
nokler = store.sample_keys(samples)
claimable = store.claimable_sample_ids("Kari Nordmann", nokler, DB)
store.claim_next("Kari Nordmann", claimable, db_path=DB)
store.queue_stats("Kari Nordmann", nokler, DB)
store.get_assessment("1", "Kari Nordmann", kilde_id=str(kilde), db_path=DB)
rapport("en kjoring av Vurdering", time.perf_counter() - start)

# Fragmentet som oppdaterer fremdriften.
nullstill()
start = time.perf_counter()
store.touch_claim("1", "Kari Nordmann", kilde_id=str(kilde), db_path=DB)
store.queue_stats("Kari Nordmann", nokler, DB)
store.remaining_breakdown("Kari Nordmann", nokler, DB)
rapport("fremdrift-fragmentet", time.perf_counter() - start)

# Administrasjonssiden.
nullstill()
start = time.perf_counter()
store.list_sources(DB)
store.list_reviewer_records(DB)
store.assignment_labels(nokler, DB)
store.list_assessments(db_path=DB)
store.reviewer_progress(nokler, DB)
rapport("en kjoring av Administrasjon", time.perf_counter() - start)

print()
print("sqlite-versjon", sqlite3.sqlite_version)
store.glem_database(DB)
DB.unlink(missing_ok=True)
