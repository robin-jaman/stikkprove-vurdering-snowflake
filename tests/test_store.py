from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import snowflake_schema_sql
from src.loader import _read_tabular_bytes
from src.store import (
    LOGG_TILBAKESKRIVING,
    add_admin,
    add_reviewer,
    add_source,
    claim_next,
    claimable_sample_ids,
    egen_kostatus,
    get_assessment,
    get_setting,
    glem_database,
    init_db,
    kvitter_writeback_failures,
    list_admin_events,
    list_admin_logins,
    list_reviewers,
    log_admin_event,
    read_source_bytes,
    release_claims,
    save_assessment,
    save_source_file,
    set_assignments,
    set_setting,
    writeback_failures,
)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.sqlite"

    def tearDown(self) -> None:
        glem_database(self.db)
        self._tmp.cleanup()

    def test_reviewer_and_assessment_roundtrip(self) -> None:
        self.assertEqual(add_reviewer("Kari Nordmann", db_path=self.db), "added")
        self.assertEqual(
            add_reviewer("Kari Nordmann", db_path=self.db, snowflake_bruker="KARI"),
            "updated",
        )
        self.assertEqual(list_reviewers(self.db), ["Kari Nordmann"])
        save_assessment(
            {
                "kilde_id": "k1",
                "stikkprove_nr": "2",
                "saksbehandler": "Kari Nordmann",
                "handling": "Annet",
                "kilde": "fil",
            },
            db_path=self.db,
        )
        save_assessment(
            {
                "kilde_id": "k1",
                "stikkprove_nr": "2",
                "saksbehandler": "Kari Nordmann",
                "handling": "Oppdatert",
                "kilde": "fil",
            },
            db_path=self.db,
        )
        row = get_assessment("2", "Kari Nordmann", kilde_id="k1", db_path=self.db)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["handling"], "Oppdatert")

    def test_claims_stay_until_released(self) -> None:
        add_reviewer("Kari", db_path=self.db)
        add_reviewer("Ola", db_path=self.db)
        keys = [("k", "1"), ("k", "2")]
        first = claim_next("Kari", keys, db_path=self.db)
        self.assertEqual(first, ("k", "1"))
        save_assessment(
            {"kilde_id": "k", "stikkprove_nr": "1", "saksbehandler": "Kari", "handling": "A"},
            db_path=self.db,
        )
        self.assertEqual(claim_next("Kari", keys, db_path=self.db), ("k", "1"))
        other = claim_next("Ola", keys, db_path=self.db)
        self.assertEqual(other, ("k", "2"))
        release_claims("Kari", db_path=self.db)
        self.assertIsNone(claim_next("Kari", keys, db_path=self.db))

    def test_assignment_limits_claimable(self) -> None:
        keys = [("k", "1"), ("k", "2")]
        set_assignments([keys[0]], ["Kari"], db_path=self.db)
        set_assignments([keys[1]], ["Ola"], db_path=self.db)
        self.assertEqual(claimable_sample_ids("Kari", keys, db_path=self.db), [("k", "1")])
        self.assertEqual(claimable_sample_ids("Ola", keys, db_path=self.db), [("k", "2")])

    def test_source_file_roundtrip(self) -> None:
        source_id = add_source("Uttrekk", "file", db_path=self.db)
        column = "stikkpr\u00f8ve_nr"
        payload = (column + ";varselkode\n7;V1\n").encode("utf-8")
        save_source_file(source_id, "uttrekk.csv", payload, db_path=self.db)
        data, name = read_source_bytes(
            {"source_id": source_id, "name": "Uttrekk"}, db_path=self.db
        )
        frame = _read_tabular_bytes(data, name)
        self.assertEqual(list(frame[column].astype(str)), ["7"])

    def test_admin_log_and_login(self) -> None:
        log_admin_event("La til grunnlag", db_path=self.db)
        events = list_admin_events(5, db_path=self.db)
        self.assertEqual(events[0]["tekst"], "La til grunnlag")
        add_admin("KARI", db_path=self.db)
        add_admin("kari", db_path=self.db)
        self.assertEqual(list_admin_logins(self.db), ["KARI"])

    def test_settings_roundtrip(self) -> None:
        self.assertEqual(get_setting("snowflake_query", "standard", db_path=self.db), "standard")
        set_setting("snowflake_query", "SELECT * FROM MINE_STIKKPROVER", db_path=self.db)
        self.assertEqual(
            get_setting("snowflake_query", "standard", db_path=self.db),
            "SELECT * FROM MINE_STIKKPROVER",
        )
        set_setting("snowflake_query", "   ", db_path=self.db)
        self.assertEqual(get_setting("snowflake_query", "standard", db_path=self.db), "standard")

    def test_tabellene_havner_i_eget_schema(self) -> None:
        import os

        from src.db import qualified

        forrige = os.environ.get("STIKKPROVE_TABLE_SCHEMA")
        try:
            os.environ["STIKKPROVE_TABLE_SCHEMA"] = "TEST.DATAFORVALTNING_TEMP"
            self.assertEqual(
                qualified("claims"), "TEST.DATAFORVALTNING_TEMP.STIKKPROVE_CLAIMS"
            )
            self.assertIn(
                "TEST.DATAFORVALTNING_TEMP.STIKKPROVE_SETTINGS",
                "\n".join(snowflake_schema_sql()),
            )
            # Tomt schema betyr samme schema som appen kjorer i.
            os.environ["STIKKPROVE_TABLE_SCHEMA"] = ""
            self.assertEqual(qualified("claims"), "STIKKPROVE_CLAIMS")
        finally:
            if forrige is None:
                os.environ.pop("STIKKPROVE_TABLE_SCHEMA", None)
            else:
                os.environ["STIKKPROVE_TABLE_SCHEMA"] = forrige

    def test_appen_lager_ikke_schemaer(self) -> None:
        from src.db import SnowflakeDb

        kjoert: list[str] = []
        db = SnowflakeDb()
        db.execute = lambda sql, params=None: kjoert.append(sql)  # type: ignore[method-assign]
        var_klar = SnowflakeDb._ready
        SnowflakeDb._ready = False
        try:
            db.ensure_schema()
        finally:
            SnowflakeDb._ready = var_klar

        self.assertEqual(len(kjoert), 7)
        for sql in kjoert:
            self.assertNotIn("CREATE SCHEMA", sql)

    def test_snowflake_schema_matches_form(self) -> None:
        setninger = snowflake_schema_sql()
        sql = "\n".join(setninger)
        self.assertEqual(len(setninger), 7)
        self.assertIn("KILDE_ID", sql)
        self.assertIn("SOURCE_FILES", sql)
        self.assertIn("SETTINGS", sql)
        self.assertNotIn("SIKKERHET", sql)
        self.assertNotIn("REGELVERK_REF", sql)
        # Administratorer og endringslogg ligger i SETTINGS.
        self.assertNotIn("ADMIN_LOG", sql)
        self.assertNotIn("ADMINS", sql)

    def test_gammel_base_flyttes_inn_i_settings(self) -> None:
        import sqlite3

        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "CREATE TABLE settings (navn TEXT PRIMARY KEY, verdi TEXT, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO settings VALUES ('snowflake_tabell', 'MIN.TABELL', '2026-01-01')"
            )
            conn.execute(
                "CREATE TABLE admins (snowflake_bruker TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO admins VALUES ('OLA', '2026-01-01')")
            conn.execute(
                "CREATE TABLE admin_log "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, happened_at TEXT NOT NULL, tekst TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO admin_log (happened_at, tekst) VALUES ('2026-01-01', 'Gammel hendelse')"
            )
            conn.commit()
        finally:
            conn.close()

        init_db(self.db)

        self.assertEqual(get_setting("snowflake_tabell", db_path=self.db), "MIN.TABELL")
        self.assertEqual(list_admin_logins(self.db), ["OLA"])
        self.assertEqual(list_admin_events(5, db_path=self.db)[0]["tekst"], "Gammel hendelse")
        conn = sqlite3.connect(self.db)
        try:
            navn = {
                str(rad[0])
                for rad in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertNotIn("admins", navn)
        self.assertNotIn("admin_log", navn)

    def test_egen_kostatus_teller_bare_min_egen_ko(self) -> None:
        keys = [("k1", str(nr)) for nr in range(1, 6)]
        set_assignments(keys[:2], ["Kari Nordmann"], self.db)
        set_assignments(keys[2:3], ["Ola Nordmann"], self.db)

        # Stikkproeve 4 og 5 er ikke tildelt, og ligger i felles ko for begge.
        kari = egen_kostatus("Kari Nordmann", keys, self.db)
        self.assertEqual(kari["total"], 4)
        self.assertEqual(kari["ferdig"], 0)
        ola = egen_kostatus("Ola Nordmann", keys, self.db)
        self.assertEqual(ola["total"], 3)

        save_assessment(
            {
                "kilde_id": "k1",
                "stikkprove_nr": "1",
                "saksbehandler": "Kari Nordmann",
                "handling": "Annet",
            },
            db_path=self.db,
        )
        kari = egen_kostatus("Kari Nordmann", keys, self.db)
        self.assertEqual((kari["ferdig"], kari["mine"]), (1, 1))

        # Karis svar ligger utenfor Olas ko, og skal ikke telle der.
        ola = egen_kostatus("Ola Nordmann", keys, self.db)
        self.assertEqual((ola["total"], ola["ferdig"], ola["mine"]), (3, 0, 0))

    def test_egen_kostatus_naar_ingenting_er_tildelt_deg(self) -> None:
        keys = [("k1", str(nr)) for nr in range(1, 4)]
        set_assignments(keys, ["Kari Nordmann"], self.db)
        tom = egen_kostatus("Ola Nordmann", keys, self.db)
        self.assertEqual(tom["total"], 0)

    def test_tilbakeskrivingsfeil_kvitteres_ut_en_gang(self) -> None:
        log_admin_event("Stikkpr\u00f8ve 3 " + LOGG_TILBAKESKRIVING + ": nei", self.db)
        log_admin_event("Tildelte 5 stikkpr\u00f8ver til Kari", self.db)
        self.assertEqual(len(writeback_failures(self.db)), 1)

        kvitter_writeback_failures(self.db)
        self.assertEqual(writeback_failures(self.db), [])

        log_admin_event("Stikkpr\u00f8ve 4 " + LOGG_TILBAKESKRIVING + ": nei", self.db)
        feil = writeback_failures(self.db)
        self.assertEqual(len(feil), 1)
        self.assertIn("Stikkpr\u00f8ve 4", feil[0]["tekst"])


if __name__ == "__main__":
    unittest.main()
