"""Month/year tokens resolved from the delivery folder.

The filename suffix carries the month (``[PK]-AGO26``) and was typed by hand
every delivery, so whatever a corridor stored was last month's. The Pulpí-Vera
tree shows the shape of it: ``2026/5.Mayo`` holds files named ``…-ABR26``.
"""
from __future__ import annotations

import unittest

from src.core.naming import has_tokens, month_tokens_from_path, resolve_suffix

BASE = "//dsconecta/aeroscan/01. PRODUCCION AEROSCAN/TRABAJOS/CLIENTES"


class MonthFromPathTests(unittest.TestCase):
    def test_reads_the_real_delivery_folders(self) -> None:
        casos = {
            f"{BASE}/UTE ACCIONA-AZVI TRAMO TORRE PACHECO/2026/8.Agosto": ("AGO", "26"),
            f"{BASE}/UTE AVE TRAZA LORCA-PULPI/2026/7.JULIO/Imagenes": ("JUL", "26"),
            f"{BASE}/UTE ACCIONA-FERROVIAL TRAZA PULPI-VERA/2026/5.Mayo/1.Editadas": ("MAY", "26"),
        }
        for ruta, (mes, aa) in casos.items():
            with self.subTest(ruta=ruta):
                tokens = month_tokens_from_path(ruta)
                self.assertIsNotNone(tokens)
                self.assertEqual(tokens["MES"], mes)
                self.assertEqual(tokens["AA"], aa)
                self.assertEqual(tokens["AAAA"], "2026")

    def test_works_from_a_subfolder_of_the_month(self) -> None:
        """The operator often picks 1.Editadas, not the month folder itself."""
        self.assertEqual(
            month_tokens_from_path(f"{BASE}/obra/2026/3.Marzo/1.Editadas/revisadas")["MES"],
            "MAR",
        )

    def test_every_month_is_covered(self) -> None:
        esperado = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
                    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
        nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        for indice, nombre in enumerate(nombres, start=1):
            with self.subTest(mes=nombre):
                tokens = month_tokens_from_path(f"G:/obra/2026/{indice}.{nombre}")
                self.assertEqual(tokens["MES"], esperado[indice - 1])

    def test_month_without_a_year_is_not_enough(self) -> None:
        self.assertIsNone(month_tokens_from_path("G:/suelto/8.Agosto"))

    def test_a_folder_that_names_no_month(self) -> None:
        self.assertIsNone(month_tokens_from_path("G:/obra/2026/Imagenes"))
        self.assertIsNone(month_tokens_from_path(""))

    def test_the_year_must_be_above_the_month(self) -> None:
        """A '2026' below the month folder is something else entirely."""
        self.assertIsNone(month_tokens_from_path("G:/obra/8.Agosto/2026"))


class SuffixResolutionTests(unittest.TestCase):
    def test_resolves_the_token(self) -> None:
        self.assertEqual(
            resolve_suffix("[PK]-{MES}{AA}", f"{BASE}/obra/2026/8.Agosto"),
            "[PK]-AGO26",
        )

    def test_is_case_insensitive(self) -> None:
        self.assertEqual(
            resolve_suffix("[PK]-{mes}{aa}", f"{BASE}/obra/2026/1.Enero"),
            "[PK]-ENE26",
        )

    def test_long_month_and_full_year(self) -> None:
        self.assertEqual(
            resolve_suffix("{MES_LARGO}{AAAA}", f"{BASE}/obra/2026/5.Mayo"),
            "Mayo2026",
        )

    def test_a_literal_suffix_is_untouched(self) -> None:
        """Nobody's existing configuration changes behaviour."""
        self.assertEqual(
            resolve_suffix("[PK]-AGO26", f"{BASE}/obra/2026/5.Mayo"), "[PK]-AGO26"
        )

    def test_an_unresolvable_token_stays_visible(self) -> None:
        """Better a visible {MES} in the preview than a silently wrong month."""
        self.assertEqual(
            resolve_suffix("[PK]-{MES}{AA}", "G:/sin/mes"), "[PK]-{MES}{AA}"
        )

    def test_has_tokens(self) -> None:
        self.assertTrue(has_tokens("[PK]-{MES}{AA}"))
        self.assertTrue(has_tokens("[PK]-{mes}"))
        self.assertFalse(has_tokens("[PK]-AGO26"))
        self.assertFalse(has_tokens(""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
