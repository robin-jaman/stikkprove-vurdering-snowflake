from __future__ import annotations

import unittest

from src.admin import (
    _fordel_likt,
    _nummerspenn,
    _tildelte_per_person,
    _tolk_numre,
    _utsnitt,
    _velg_numre,
)


class FordelingTests(unittest.TestCase):
    def nokler(self, antall: int) -> list:
        return [("kilde", str(nr)) for nr in range(1, antall + 1)]

    def test_deler_jevnt_naar_det_gaar_opp(self) -> None:
        bunker = _fordel_likt(self.nokler(9), ["Kari", "Ola", "Per"])
        self.assertEqual([len(bunke) for bunke in bunker.values()], [3, 3, 3])

    def test_restene_gaar_til_de_forste(self) -> None:
        bunker = _fordel_likt(self.nokler(10), ["Kari", "Ola", "Per"])
        self.assertEqual([len(bunke) for bunke in bunker.values()], [4, 3, 3])

    def test_ingen_stikkproeve_havner_to_steder(self) -> None:
        keys = self.nokler(100)
        bunker = _fordel_likt(keys, ["Kari", "Ola", "Per", "Mari"])
        fordelt = [key for bunke in bunker.values() for key in bunke]
        self.assertEqual(len(fordelt), len(keys))
        self.assertEqual(len(set(fordelt)), len(keys))
        self.assertEqual(sorted(fordelt), sorted(keys))

    def test_faerre_stikkproever_enn_saksbehandlere(self) -> None:
        bunker = _fordel_likt(self.nokler(2), ["Kari", "Ola", "Per"])
        self.assertEqual([len(bunke) for bunke in bunker.values()], [1, 1, 0])

    def test_bunkene_henger_sammen(self) -> None:
        """Hver saksbehandler faar et sammenhengende spenn av stikkproevenummer."""
        bunker = _fordel_likt(self.nokler(6), ["Kari", "Ola"])
        self.assertEqual([nr for _, nr in bunker["Kari"]], ["1", "2", "3"])
        self.assertEqual([nr for _, nr in bunker["Ola"]], ["4", "5", "6"])


class UtsnittTests(unittest.TestCase):
    """Aa ta hundre av gangen skal gi hundre nye hver gang."""

    def nokler(self, antall: int) -> list:
        return [("kilde", str(nr)) for nr in range(1, antall + 1)]

    def test_de_forste_hundre(self) -> None:
        del_en = _utsnitt(self.nokler(523), 1, 100)
        self.assertEqual(len(del_en), 100)
        self.assertEqual(del_en[0][1], "1")
        self.assertEqual(del_en[-1][1], "100")

    def test_de_neste_hundre_overlapper_ikke(self) -> None:
        keys = self.nokler(523)
        del_en = _utsnitt(keys, 1, 100)
        del_to = _utsnitt(keys, 101, 100)
        self.assertEqual(del_to[0][1], "101")
        self.assertEqual(set(del_en) & set(del_to), set())

    def test_siste_bunke_blir_bare_det_som_er_igjen(self) -> None:
        self.assertEqual(len(_utsnitt(self.nokler(523), 501, 100)), 23)

    def test_start_forbi_slutten_gir_ingenting(self) -> None:
        self.assertEqual(_utsnitt(self.nokler(10), 11, 100), [])


class NummerspennTests(unittest.TestCase):
    """Tildelingen skal vises med stikkproevenummer, uten aa fylle hele cellen."""

    def test_sammenhengende_numre_blir_ett_spenn(self) -> None:
        self.assertEqual(_nummerspenn([str(nr) for nr in range(1, 101)]), "1-100")

    def test_hull_gir_flere_spenn(self) -> None:
        self.assertEqual(_nummerspenn(["1", "2", "3", "7", "9", "10"]), "1-3, 7, 9-10")

    def test_mange_spenn_forkortes(self) -> None:
        numre = [str(nr) for nr in range(1, 40, 2)]
        tekst = _nummerspenn(numre)
        self.assertTrue(tekst.endswith("og 10 til"), tekst)

    def test_numre_som_ikke_er_tall_staar_som_de_er(self) -> None:
        self.assertEqual(_nummerspenn(["B-2", "A-1"]), "A-1, B-2")

    def test_tabellen_viser_antall_og_numre_per_person(self) -> None:
        labels = {
            ("kilde", "1"): "Kari",
            ("kilde", "2"): "Kari",
            ("kilde", "3"): "Felles k\u00f8",
        }
        frame = _tildelte_per_person(labels)
        kari = frame[frame["Tildelt til"] == "Kari"].iloc[0]
        self.assertEqual(kari["Stikkpr\u00f8ver"], 2)
        self.assertEqual(kari["Stikkpr\u00f8venummer"], "1-2")


class NummerutvalgTests(unittest.TestCase):
    """Aa skrive 201-300 skal gi nettopp de stikkproevene."""

    def nokler(self, fra: int, til: int) -> list:
        return [("kilde", str(nr)) for nr in range(fra, til + 1)]

    def test_spenn_blir_til_alle_numrene(self) -> None:
        numre, ubrukelige = _tolk_numre("201-300")
        self.assertEqual(ubrukelige, [])
        self.assertEqual(len(numre), 100)
        self.assertEqual((numre[0], numre[-1]), ("201", "300"))

    def test_spenn_og_enkeltnummer_om_hverandre(self) -> None:
        numre, _ = _tolk_numre("201-300, 405, 410-420")
        self.assertEqual(len(numre), 112)
        self.assertIn("405", numre)

    def test_baklengs_spenn_leses_riktig_vei(self) -> None:
        self.assertEqual(_tolk_numre("300-201")[0], _tolk_numre("201-300")[0])

    def test_altfor_stort_spenn_avvises(self) -> None:
        numre, ubrukelige = _tolk_numre("1-99999999")
        self.assertEqual(numre, [])
        self.assertEqual(ubrukelige, ["1-99999999"])

    def test_velger_bare_de_som_er_i_utvalget(self) -> None:
        maal, mangler = _velg_numre(self.nokler(1, 250), ["249", "250", "251"])
        self.assertEqual([nr for _, nr in maal], ["249", "250"])
        self.assertEqual(mangler, ["251"])

    def test_rekkefoelgen_foelger_koen(self) -> None:
        maal, _ = _velg_numre(self.nokler(1, 10), ["7", "2", "5"])
        self.assertEqual([nr for _, nr in maal], ["2", "5", "7"])

    def test_ledende_nuller_treffer_likevel(self) -> None:
        maal, mangler = _velg_numre([("kilde", "0201")], ["201"])
        self.assertEqual(len(maal), 1)
        self.assertEqual(mangler, [])


if __name__ == "__main__":
    unittest.main()
