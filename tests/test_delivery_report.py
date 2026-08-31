"""The document that goes out with the delivery.

Everything in it was already computed — coverage, holes, PK posts with no
photo, the routing of every file — but it lived in three separate exports the
operator recomposed by hand every month.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.core.coverage import CoverageGap, CoverageReport, MissingPk
from src.core.delivery_report import (
    build_delivery_report,
    default_filename,
    write_delivery_report,
)
from src.core.models import PhotoItem

BASE = "//dsconecta/aeroscan/01. PRODUCCION AEROSCAN/TRABAJOS/CLIENTES"
CARPETA = f"{BASE}/UTE ACCIONA-AZVI TRAMO TORRE PACHECO/2026/8.Agosto"


def _item(nombre: str, pk: float, *, dentro=True, base="", destino="", excluida=False) -> PhotoItem:
    return PhotoItem(
        path=f"{CARPETA}/{nombre}", name=nombre, lat=37.8, lon=-0.96,
        date_str="20260818", time_str="103000", pk_value=pk, distance=4.2,
        pk_display=f"PK-{int(pk // 1000)}+{int(pk % 1000):03d}",
        is_inside_threshold=dentro, excluded=excluida,
        new_name_base=base, dest_rel=destino, view_label="CEN",
    )


def _coverage(**kwargs) -> CoverageReport:
    datos = dict(
        inside_count=3, outside_count=1, trace_start_pk_m=18000.0,
        trace_end_pk_m=20000.0, pk_min_m=18100.0, pk_max_m=19900.0,
        covered_m=1200.0, coverage_ratio=0.6, pk_total=20,
        gaps=[CoverageGap(18500.0, 19000.0)],
        missing_pks=[MissingPk("PK-18+600", 18600.0)],
    )
    datos.update(kwargs)
    return CoverageReport(**datos)


class ReportContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            _item("DJI_1.jpg", 18100.0, base="PK-18+100-AGO26", destino="(raíz)"),
            _item("DJI_2.jpg", 18900.0, base="PK-18+900-AGO26", destino="VIADUCTOS"),
            _item("DJI_3.jpg", 19900.0, base="PK-19+900-AGO26", destino="VERTEDEROS/Gregal"),
            _item("DJI_4.jpg", 0.0, dentro=False),
        ]
        self.doc = build_delivery_report(
            self.items, _coverage(),
            project_name="UTE ACCIONA-AZVI TRAMO TORRE PACHECO",
            folder=CARPETA, kml=f"{BASE}/x/Puntos para script.kml",
            threshold=13.8, threshold_method="corte en el salto de distancias",
            now=datetime(2026, 8, 31, 9, 0),
        )

    def test_identifies_the_job_and_the_period(self) -> None:
        self.assertIn("UTE ACCIONA-AZVI TRAMO TORRE PACHECO", self.doc)
        self.assertIn("Agosto 2026", self.doc)
        self.assertIn("Puntos para script.kml", self.doc)
        self.assertIn("13.8 m", self.doc)
        self.assertIn("corte en el salto de distancias", self.doc)

    def test_is_self_contained(self) -> None:
        """It has to survive being emailed: no external CSS, JS or images."""
        self.assertNotIn("<script", self.doc)
        self.assertNotIn("http://", self.doc)
        self.assertNotIn("https://", self.doc)
        self.assertNotIn("file://", self.doc)

    def test_counts_match_the_delivery(self) -> None:
        self.assertIn(">4<", self.doc)          # analizadas
        self.assertIn(">3<", self.doc)          # en la entrega
        self.assertIn("60%", self.doc)          # traza cubierta
        self.assertIn("19/20", self.doc)        # PK con fotografia

    def test_the_bar_places_each_gap_to_scale(self) -> None:
        """A percentage says how much; the bar says where — that decides a reflight."""
        rojos = re.findall(r'<rect[^>]*fill="#dc2626"', self.doc)
        self.assertEqual(len(rojos), 1)
        self.assertIn("PK-18+000", self.doc)
        self.assertIn("PK-20+000", self.doc)

    def test_lists_the_gaps_longest_first(self) -> None:
        doc = build_delivery_report(
            self.items,
            _coverage(gaps=[CoverageGap(18100.0, 18300.0), CoverageGap(18500.0, 19400.0)]),
            folder=CARPETA,
        )
        primero = doc.index("PK-18+500")
        segundo = doc.index("PK-18+100</td>") if "PK-18+100</td>" in doc else doc.index("PK-18+100")
        self.assertLess(primero, segundo)

    def test_index_has_one_row_per_delivered_photo(self) -> None:
        for nombre in ("PK-18+100-AGO26", "PK-18+900-AGO26", "PK-19+900-AGO26"):
            self.assertIn(nombre, self.doc)
        # La que queda fuera del umbral no se entrega.
        self.assertNotIn("DJI_4.jpg", self.doc)

    def test_shows_where_the_photos_are_routed(self) -> None:
        self.assertIn("VIADUCTOS", self.doc)
        self.assertIn("VERTEDEROS/Gregal", self.doc)

    def test_escapes_names_that_come_from_the_client(self) -> None:
        """PK labels come from the KML and file names from disk (ADR-010)."""
        hostil = '<img src=x onerror="alert(1)">'
        items = [_item(f"{hostil}.jpg", 18100.0, base=hostil, destino=hostil)]
        doc = build_delivery_report(
            items, _coverage(missing_pks=[MissingPk(hostil, 18600.0)]),
            project_name=hostil, folder=CARPETA,
        )
        self.assertNotIn("<img src=x", doc)
        self.assertIn("&lt;img src=x", doc)

    def test_a_clean_job_says_so(self) -> None:
        doc = build_delivery_report(
            self.items, _coverage(gaps=[], missing_pks=[]), folder=CARPETA
        )
        self.assertIn("Sin huecos", doc)
        self.assertIn("Todos los puntos kilométricos tienen fotografía", doc)

    def test_survives_without_a_trace(self) -> None:
        doc = build_delivery_report(
            self.items,
            _coverage(trace_start_pk_m=None, trace_end_pk_m=None, coverage_ratio=None),
            folder="",
        )
        self.assertIn("no se puede situar la cobertura", doc)


class FilenameTests(unittest.TestCase):
    def test_named_after_the_delivery_month(self) -> None:
        self.assertEqual(default_filename(CARPETA), "informe_entrega_AGO26.html")

    def test_falls_back_to_the_date(self) -> None:
        self.assertEqual(
            default_filename("", datetime(2026, 8, 31)), "informe_entrega_20260831.html"
        )

    def test_writes_utf8_and_creates_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "sub" / "informe.html"
            escrito = write_delivery_report(destino, "<p>ñ · PK-1+000</p>")
            self.assertIn("ñ", escrito.read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
