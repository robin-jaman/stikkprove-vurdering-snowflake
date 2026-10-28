from __future__ import annotations

import unittest

import pandas as pd

from src.config import SAMPLE_ID_COL
from src.kolonner import (
    SVAR_TIL_KOLONNE,
    finn_navn,
    forenkle,
    gjenkjente,
    manglende,
    oversett,
)
from src.db import _uten_hermetegn
from src.snowflake_client import (
    _ny_rad,
    _sitert,
    _writeback_values,
    writeback_plan,
)

# Slik kolonnene faktisk heter i kildetabellen hos SPK: store bokstaver,
# og norske bokstaver skrevet om til oe/aa/ae.
SNOWFLAKE_KOLONNER = [
    "STIKKPROEVE_NR",
    "SPK_PERSON_ID_KILDE",
    "LINJE_NR_KILDE",
    "VARSELKODE",
    "AKSJON_DT",
    "ARBEIDSGIVERNAVN",
    "LOENN",
    "VURDERT_AV",
    "VURDERT_DT",
    "HAANDTERING_AV_VARSELET",
    "PRAKSIS_OG_EVENTUELLE_UNNTAK",
    "SAERLIGE_FORHOLD",
    "VURDERING_AV_KORREKTHET",
    "ANDRE_KOMMENTARER",
    "EN_KOLONNE_APPEN_IKKE_BRUKER",
]


class KolonneTests(unittest.TestCase):
    def test_norske_bokstaver_treffer_snowflake_skrivemaate(self) -> None:
        self.assertEqual(forenkle("STIKKPROVE_NR"), forenkle(SAMPLE_ID_COL))
        self.assertEqual(forenkle("LOENN"), forenkle("l\u00f8nn"))
        self.assertEqual(forenkle("STILLINGSSTOERRELSE_PRS"), forenkle("stillingsstoerrelse_prs"))

    def test_oversett_doeper_om_til_appens_navn(self) -> None:
        frame = pd.DataFrame({navn: ["x"] for navn in SNOWFLAKE_KOLONNER})
        oversatt = oversett(frame)
        self.assertIn(SAMPLE_ID_COL, oversatt.columns)
        self.assertIn("l\u00f8nn", oversatt.columns)
        self.assertIn("andre_kommentarer", oversatt.columns)
        # Ukjente kolonner skal staa urort.
        self.assertIn("EN_KOLONNE_APPEN_IKKE_BRUKER", oversatt.columns)

    def test_manglende_melder_fra_om_id_kolonnen(self) -> None:
        self.assertEqual(manglende(SNOWFLAKE_KOLONNER), [])
        self.assertEqual(manglende(["NOE_HELT_ANNET"]), [SAMPLE_ID_COL])

    def test_gjenkjente_teller_bare_appens_kolonner(self) -> None:
        funnet = gjenkjente(SNOWFLAKE_KOLONNER)
        self.assertIn(SAMPLE_ID_COL, funnet)
        self.assertNotIn("EN_KOLONNE_APPEN_IKKE_BRUKER", funnet)

    def test_finn_navn_gir_navnet_slik_det_staar_i_tabellen(self) -> None:
        self.assertEqual(finn_navn(SNOWFLAKE_KOLONNER, SAMPLE_ID_COL), "STIKKPROEVE_NR")
        self.assertEqual(finn_navn(SNOWFLAKE_KOLONNER, "ingen_slik_kolonne"), "")

    def test_writeback_plan_finner_svarkolonner_og_hvem_som_svarte(self) -> None:
        plan = writeback_plan(SNOWFLAKE_KOLONNER)
        self.assertEqual(plan["handling"], "HAANDTERING_AV_VARSELET")
        self.assertEqual(plan["vanlighet"], "PRAKSIS_OG_EVENTUELLE_UNNTAK")
        self.assertEqual(plan["periode_spesielt"], "SAERLIGE_FORHOLD")
        self.assertEqual(plan["historisk_korrekt"], "VURDERING_AV_KORREKTHET")
        self.assertEqual(plan["kommentar"], "ANDRE_KOMMENTARER")
        self.assertEqual(plan["saksbehandler"], "VURDERT_AV")
        self.assertEqual(plan["updated_at"], "VURDERT_DT")
        # Kolonnen mangler i denne tabellen, saa feltet skal ikke med.
        self.assertNotIn("begrunnelse", plan)

    def test_hele_tabellen_gir_alle_seks_svarkolonner(self) -> None:
        kolonner = ["STIKKPROEVE_NR"] + [
            navn.upper() for navn in SVAR_TIL_KOLONNE.values()
        ]
        plan = writeback_plan(kolonner)
        self.assertEqual(sorted(plan), sorted(SVAR_TIL_KOLONNE))

    def test_annet_slaas_sammen_med_fritekst(self) -> None:
        svar = _writeback_values({"handling": "Annet", "handling_annet": "Sendt til fagansvarlig"})
        self.assertEqual(svar["handling"], "Annet: Sendt til fagansvarlig")
        uendret = _writeback_values({"handling": "Korrigert fast tillegg", "handling_annet": ""})
        self.assertEqual(uendret["handling"], "Korrigert fast tillegg")

    def test_unntaksforklaring_slaas_sammen_med_vanlighet(self) -> None:
        svar = _writeback_values(
            {"vanlighet": "Unntak", "unntak_forklaring": "Etterbetaling av tariffoppgjoer"}
        )
        self.assertEqual(svar["vanlighet"], "Unntak: Etterbetaling av tariffoppgjoer")
        uendret = _writeback_values({"vanlighet": "Vanlig m\u00e5te", "unntak_forklaring": ""})
        self.assertEqual(uendret["vanlighet"], "Vanlig m\u00e5te")


class NyRadTests(unittest.TestCase):
    """Stikkproever fra et regneark som ikke finnes i kildetabellen."""

    def setUp(self) -> None:
        import src.db as db_modul

        self.fanget: dict[str, object] = {}
        self._original = db_modul.exec_snowflake
        db_modul.exec_snowflake = self._fang  # type: ignore[assignment]
        self.addCleanup(setattr, db_modul, "exec_snowflake", self._original)

    def _fang(self, sql: str, params: object = None) -> None:
        self.fanget["sql"] = sql
        self.fanget["params"] = params

    def test_tar_med_data_fra_regnearket_og_lar_svaret_vinne(self) -> None:
        rad = pd.Series(
            {
                "stikkpr\u00f8ve_nr": "4711",
                "l\u00f8nn": 500000,
                "haandtering_av_varselet": "gammelt svar fra arket",
                "_kilde_id": "abc",
                "har_referansevurdering": True,
            }
        )
        beskjed = _ny_rad(
            "TEST.SKJEMA.TABELL",
            ["STIKKPROEVE_NR", "LOENN", "HAANDTERING_AV_VARSELET"],
            "STIKKPROEVE_NR",
            "4711",
            {"handling": "Kvittert og bekreftet varslet"},
            rad,
        )
        sql = str(self.fanget["sql"])
        verdier = list(self.fanget["params"] or [])

        self.assertIn("INSERT INTO TEST.SKJEMA.TABELL", sql)
        self.assertIn('"LOENN"', sql)
        self.assertIn(500000, verdier)
        # Interne hjelpekolonner skal ikke forsoekes skrevet.
        self.assertNotIn("KILDE_ID", sql)
        # Svaret fra skjemaet vinner over det som laa i arket.
        self.assertIn("Kvittert og bekreftet varslet", verdier)
        self.assertNotIn("gammelt svar fra arket", verdier)
        self.assertIn("ny rad", beskjed)

    def test_tomme_celler_blir_null(self) -> None:
        rad = pd.Series({"stikkpr\u00f8ve_nr": "4711", "l\u00f8nn": float("nan")})
        _ny_rad(
            "TEST.SKJEMA.TABELL",
            ["STIKKPROEVE_NR", "LOENN"],
            "STIKKPROEVE_NR",
            "4711",
            {},
            rad,
        )
        self.assertIn(None, list(self.fanget["params"] or []))


class KolonnenavnFraSnowparkTests(unittest.TestCase):
    """Navnet som kommer ut av Snowpark maa kunne siteres igjen uten skade."""

    def test_hermetegn_fjernes_for_navnet_siteres_paa_nytt(self) -> None:
        # Snowpark setter hermetegn rundt kolonner som ikke er rent store.
        self.assertEqual(_uten_hermetegn('"stikkproeve_nr"'), "stikkproeve_nr")
        self.assertEqual(_sitert(_uten_hermetegn('"stikkproeve_nr"')), '"stikkproeve_nr"')

    def test_vanlige_navn_staar_uroert(self) -> None:
        self.assertEqual(_uten_hermetegn("STIKKPROEVE_NR"), "STIKKPROEVE_NR")
        self.assertEqual(_sitert("STIKKPROEVE_NR"), '"STIKKPROEVE_NR"')

    def test_hermetegn_inni_navnet_overlever(self) -> None:
        self.assertEqual(_uten_hermetegn('"rar""kolonne"'), 'rar"kolonne')
        self.assertEqual(_sitert('rar"kolonne'), '"rar""kolonne"')

    def test_smaa_bokstaver_treffer_appens_navn(self) -> None:
        kolonner = [_uten_hermetegn('"stikkproeve_nr"')]
        self.assertEqual(finn_navn(kolonner, SAMPLE_ID_COL), "stikkproeve_nr")


if __name__ == "__main__":
    unittest.main()
