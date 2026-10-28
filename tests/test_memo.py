from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import SqliteDb
from src.store import (
    add_reviewer,
    assignment_labels,
    get_setting,
    glem_database,
    init_db,
    list_reviewers,
    nullstill_lesinger,
    set_assignments,
    set_setting,
)


class MemoTests(unittest.TestCase):
    """Memoet skal spare sporringer uten aa servere utdaterte tall."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.sqlite"
        init_db(self.db)

    def tearDown(self) -> None:
        glem_database(self.db)
        self._tmp.cleanup()

    def test_gjentatt_lesing_treffer_databasen_en_gang(self) -> None:
        add_reviewer("Kari Nordmann", db_path=self.db)
        nullstill_lesinger()
        telling = {"n": 0}
        ekte = SqliteDb.fetchall

        def tellende(self, sql, params=None):
            telling["n"] += 1
            return ekte(self, sql, params)

        SqliteDb.fetchall = tellende  # type: ignore[method-assign]
        try:
            list_reviewers(self.db)
            list_reviewers(self.db)
            list_reviewers(self.db)
        finally:
            SqliteDb.fetchall = ekte  # type: ignore[method-assign]
        self.assertEqual(telling["n"], 1)

    def test_skriving_gjor_neste_lesing_fersk(self) -> None:
        add_reviewer("Kari Nordmann", db_path=self.db)
        self.assertEqual(list_reviewers(self.db), ["Kari Nordmann"])
        add_reviewer("Ola Nordmann", db_path=self.db)
        self.assertEqual(
            list_reviewers(self.db), ["Kari Nordmann", "Ola Nordmann"]
        )

    def test_innstilling_oppdateres_etter_lagring(self) -> None:
        self.assertEqual(get_setting("kildetabell", "ingen", self.db), "ingen")
        set_setting("kildetabell", "TEST.SKJEMA.TABELL", self.db)
        self.assertEqual(
            get_setting("kildetabell", "ingen", self.db), "TEST.SKJEMA.TABELL"
        )

    def test_tildeling_synes_med_en_gang(self) -> None:
        keys = [("kilde", "1"), ("kilde", "2")]
        self.assertEqual(
            set(assignment_labels(keys, self.db).values()), {"Felles k\u00f8"}
        )
        set_assignments([keys[0]], ["Kari Nordmann"], self.db)
        labels = assignment_labels(keys, self.db)
        self.assertEqual(labels[keys[0]], "Kari Nordmann")
        self.assertEqual(labels[keys[1]], "Felles k\u00f8")


if __name__ == "__main__":
    unittest.main()
