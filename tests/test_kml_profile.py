"""Recognising which KML is the trace, which are landfills, and which are neither.

Every client folder holds several KML and only one is the trace. On the real
share (23 files) the kinds are told apart by what is inside them, not by name:
the client's 27 MB survey file carries 370 PK-named points and still is not a
trace -- its geometry runs nowhere near them (measured: 18 553 m off).
"""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.core.kml_profile import (
    MIN_PK_POSTS,
    ROLE_EMPTY,
    ROLE_LANDMARKS,
    ROLE_SURVEY,
    ROLE_TRACE,
    ROLE_UNREADABLE,
    candidate_directories,
    describe,
    discover_kmls,
    profile_kml,
    recommend,
    suggest_trace_for,
    unregistered_landmarks,
)

HEAD = '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
TAIL = "</Document></kml>"


def _post(name: str, lon: float, lat: float) -> str:
    return f"<Placemark><name>{name}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"


def trace_kml(first_km: int = 18, count: int = 20, folder: str = "Trabajo nuevo") -> str:
    """PK posts one per 100 m, running north: a trace the calculator infers."""
    posts = "".join(
        _post(f"{first_km + (i * 100) // 1000}+{(i * 100) % 1000:03d}", -0.960, 37.800 + i * 0.0009)
        for i in range(count)
    )
    return f"{HEAD}<Folder><name>{folder}</name>{posts}</Folder>{TAIL}"


LANDMARKS_KML = (
    HEAD
    + "<Placemark><name>TP01</name><MultiGeometry>"
    "<Point><coordinates>-0.95,37.80,0</coordinates></Point>"
    "<Point><coordinates>-0.951,37.801,0</coordinates></Point>"
    "<Point><coordinates>-0.952,37.802,0</coordinates></Point>"
    "</MultiGeometry></Placemark>" + TAIL
)

SURVEY_KML = (
    HEAD + "<Folder><name>Parcelas</name><Placemark><name>1</name><Polygon><outerBoundaryIs><LinearRing>"
    "<coordinates>-1,38,0 -1.1,38,0 -1.1,38.1,0 -1,38,0</coordinates></LinearRing></outerBoundaryIs></Polygon>"
    "</Placemark></Folder>" + TAIL
)


def survey_disguised_as_trace() -> str:
    """The shape of the real 27 MB file: plenty of PK posts, geometry elsewhere."""
    posts = "".join(
        _post(f"{18 + i}+600", -0.960, 37.800 + i * 0.009) for i in range(MIN_PK_POSTS + 9)
    )
    line = (
        "<Placemark><LineString><coordinates>-1.200,38.000,0 -1.201,38.001,0</coordinates>"
        "</LineString></Placemark>"
    )
    return HEAD + line + posts + TAIL


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name: str, text: str, where: Path | None = None) -> str:
        target = (where or self.dir) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return str(target)


class ProfileTests(_Tmp):
    def test_a_file_full_of_pk_posts_is_a_trace(self) -> None:
        perfil = profile_kml(self.write("t.kml", trace_kml(count=20)))
        self.assertEqual(perfil.role, ROLE_TRACE)
        self.assertEqual(perfil.pk_posts, 20)
        self.assertEqual(perfil.span_label(), "18+000–19+900")

    def test_the_posts_are_counted_with_the_calculators_own_rule(self) -> None:
        """'PK-18+653' and plain numbers are posts; 'Vertedero 1' is not."""
        extra = _post("PK-18+653", -0.96, 37.8) + _post("Vertedero 1", -0.9, 37.8)
        perfil = profile_kml(self.write("t.kml", HEAD + extra + TAIL))
        self.assertEqual(perfil.pk_posts, 1)
        self.assertEqual(perfil.landmark_names, ("Vertedero 1",))

    def test_a_handful_of_named_points_is_a_landmark_file(self) -> None:
        perfil = profile_kml(self.write("v.kml", LANDMARKS_KML))
        self.assertEqual(perfil.role, ROLE_LANDMARKS)
        self.assertEqual(perfil.landmark_names, ("TP01",))
        self.assertEqual(perfil.landmark_points, 3)   # MultiGeometry: 3 puntos, 1 vertedero

    def test_polygons_are_a_survey_not_a_landmark(self) -> None:
        """A parcel file has a stray named point and 15 polygons."""
        # As in Parcela.kml on the real share: 15 polygons and one named point.
        poligono = SURVEY_KML.split("<Folder>")[1].split("</Folder>")[0]
        texto = HEAD + "<Folder>" + poligono * 15 + _post("04085A", -1, 38) + "</Folder>" + TAIL
        perfil = profile_kml(self.write("p.kml", texto))
        self.assertEqual(perfil.role, ROLE_SURVEY)
        self.assertIn("polígonos", perfil.reason)

    def test_zero_bytes_is_empty(self) -> None:
        """Ortofoto.kml, MDS.kml and friends on the real share."""
        perfil = profile_kml(self.write("o.kml", ""))
        self.assertEqual(perfil.role, ROLE_EMPTY)

    def test_garbage_is_unreadable_not_an_exception(self) -> None:
        perfil = profile_kml(self.write("x.kml", "esto no es xml <<<"))
        self.assertIn(perfil.role, (ROLE_UNREADABLE, ROLE_EMPTY))

    def test_a_missing_file_does_not_raise(self) -> None:
        self.assertEqual(profile_kml(str(self.dir / "no.kml")).role, ROLE_UNREADABLE)

    def test_internal_folder_names_are_kept(self) -> None:
        perfil = profile_kml(self.write("t.kml", trace_kml(folder="Vertederos")))
        self.assertEqual(perfil.folders, ("Vertederos",))

    def test_kmz_is_read_too(self) -> None:
        ruta = self.dir / "t.kmz"
        with zipfile.ZipFile(ruta, "w") as z:
            z.writestr("doc.kml", trace_kml(count=15))
        self.assertEqual(profile_kml(str(ruta)).role, ROLE_TRACE)

    def test_too_few_posts_is_not_a_trace(self) -> None:
        perfil = profile_kml(self.write("t.kml", trace_kml(count=MIN_PK_POSTS - 1)))
        self.assertNotEqual(perfil.role, ROLE_TRACE)


class SurveyDisguisedAsTraceTests(_Tmp):
    """The dangerous one: it has the PK posts, so counting alone would pick it."""

    def test_geometry_that_misses_the_posts_is_demoted(self) -> None:
        perfil = profile_kml(self.write("levantamiento.kml", survey_disguised_as_trace()))
        self.assertEqual(perfil.role, ROLE_SURVEY)
        self.assertFalse(perfil.trace_verified)
        self.assertIn("se desvía", perfil.reason)

    def test_without_verification_it_would_have_been_taken_for_a_trace(self) -> None:
        """Documents why the check exists: the counts alone say 'trace'."""
        perfil = profile_kml(self.write("levantamiento.kml", survey_disguised_as_trace()), verify=False)
        self.assertEqual(perfil.role, ROLE_TRACE)

    def test_a_trace_inferred_from_its_posts_is_not_called_verified(self) -> None:
        """It passes through its own posts by construction; that proves nothing."""
        perfil = profile_kml(self.write("t.kml", trace_kml()))
        self.assertEqual(perfil.role, ROLE_TRACE)
        self.assertIsNone(perfil.trace_verified)


class RecommendTests(_Tmp):
    def test_picks_the_real_trace_over_the_survey(self) -> None:
        self.write("Puntos.kml", trace_kml(count=20))
        self.write("Levantamiento.kml", survey_disguised_as_trace())
        self.write("Vertederos.kml", LANDMARKS_KML)
        self.write("Ortofoto.kml", "")

        rec = recommend(discover_kmls(str(self.dir)))

        self.assertEqual(rec.trace.name, "Puntos.kml")
        self.assertEqual([p.name for p in rec.landmark_kmls], ["Vertederos.kml"])
        self.assertEqual(
            sorted(p.name for p in rec.ignored), ["Levantamiento.kml", "Ortofoto.kml"]
        )

    def test_equivalent_traces_are_offered_as_alternatives(self) -> None:
        """Pulpí-Vera keeps two identical 261-post files."""
        self.write("A.kml", trace_kml(count=20))
        self.write("B.kml", trace_kml(count=20))
        rec = recommend(discover_kmls(str(self.dir)))
        self.assertIsNotNone(rec.trace)
        self.assertEqual(len(rec.alternatives), 1)

    def test_the_fuller_trace_wins(self) -> None:
        self.write("corta.kml", trace_kml(count=12))
        self.write("larga.kml", trace_kml(count=30))
        self.assertEqual(recommend(discover_kmls(str(self.dir))).trace.name, "larga.kml")

    def test_no_trace_is_reported_as_none(self) -> None:
        self.write("v.kml", LANDMARKS_KML)
        rec = recommend(discover_kmls(str(self.dir)))
        self.assertIsNone(rec.trace)
        self.assertIn("no se ha encontrado", describe(rec))

    def test_the_description_names_what_was_ignored_and_why(self) -> None:
        self.write("Levantamiento.kml", survey_disguised_as_trace())
        texto = describe(recommend(discover_kmls(str(self.dir))))
        self.assertIn("Ignorado: Levantamiento.kml", texto)
        self.assertIn("se desvía", texto)


class DiscoveryTests(_Tmp):
    """The tree is …/CLIENTES/<obra>/<año>/<mes>; the KML live at <obra>."""

    def setUp(self) -> None:
        super().setUp()
        self.obra = self.dir / "CLIENTES" / "UTE EJEMPLO"
        self.mes = self.obra / "2026" / "8.Agosto"
        self.mes.mkdir(parents=True)

    def test_finds_the_kml_two_levels_above_the_delivery(self) -> None:
        self.write("Puntos.kml", trace_kml(), where=self.obra)
        rec = recommend(discover_kmls(str(self.mes)))
        self.assertEqual(rec.trace.name, "Puntos.kml")

    def test_looks_into_a_kml_subfolder(self) -> None:
        """MLG02.kml lives in a 'kml' folder on the real share."""
        self.write("Puntos.kml", trace_kml(), where=self.obra / "kml")
        self.assertEqual(recommend(discover_kmls(str(self.mes))).trace.name, "Puntos.kml")

    def test_does_not_climb_past_the_job_root(self) -> None:
        """Another client's KML next to CLIENTES must never be offered."""
        self.write("Ajeno.kml", trace_kml(), where=self.dir / "CLIENTES")
        self.assertIsNone(recommend(discover_kmls(str(self.mes))).trace)

    def test_does_not_walk_the_photo_folder(self) -> None:
        """A delivery holds thousands of JPEG over SMB; only KML are looked at."""
        for i in range(50):
            (self.mes / f"DJI_{i:04d}.JPG").write_bytes(b"x")
        self.write("Puntos.kml", trace_kml(), where=self.obra)
        encontrados = discover_kmls(str(self.mes))
        self.assertEqual([p.name for p in encontrados], ["Puntos.kml"])

    def test_the_delivery_folder_itself_is_searched_first(self) -> None:
        self.write("Local.kml", trace_kml(), where=self.mes)
        dirs = candidate_directories(str(self.mes))
        self.assertEqual(Path(dirs[0]), self.mes)

    def test_an_empty_folder_gives_nothing(self) -> None:
        self.assertEqual(discover_kmls(str(self.mes)), [])
        self.assertEqual(discover_kmls(""), [])

    def test_a_file_path_is_accepted_for_the_start(self) -> None:
        ruta = self.write("Puntos.kml", trace_kml(), where=self.obra)
        self.assertEqual(recommend(discover_kmls(ruta)).trace.name, "Puntos.kml")


class SuggestTraceTests(_Tmp):
    def test_points_at_the_right_file_when_the_wrong_one_was_chosen(self) -> None:
        self.write("Puntos.kml", trace_kml())
        mala = self.write("Vertederos.kml", LANDMARKS_KML)
        sugerida = suggest_trace_for(mala)
        self.assertIsNotNone(sugerida)
        self.assertEqual(sugerida.name, "Puntos.kml")

    def test_says_nothing_when_the_chosen_file_is_already_the_trace(self) -> None:
        buena = self.write("Puntos.kml", trace_kml())
        self.assertIsNone(suggest_trace_for(buena))

    def test_says_nothing_for_no_path(self) -> None:
        self.assertIsNone(suggest_trace_for(""))


def trace_with_landfills(*names: str) -> str:
    """A trace whose own folder also holds landfill points, like Torre Pacheco's."""
    extra = "".join(_post(n, -0.95, 37.80 + i * 0.001) for i, n in enumerate(names))
    return trace_kml().replace("</Folder>", "</Folder><Folder><name>Vertederos</name>" + extra + "</Folder>", 1)


class UnregisteredLandmarkTests(_Tmp):
    """Torre Pacheco's trace KML defines five landfills; the project keeps a
    hand-typed copy of their names. What the KML has and the project lacks is a
    landfill whose photos are not routed to its folder."""

    def setUp(self) -> None:
        super().setUp()
        self.perfil = profile_kml(
            self.write("t.kml", trace_with_landfills("Caliche", "Palomares", "Gregal"))
        )

    def test_the_trace_reports_the_landfills_it_defines(self) -> None:
        self.assertEqual(self.perfil.role, ROLE_TRACE)
        self.assertEqual(self.perfil.landmark_names, ("Caliche", "Palomares", "Gregal"))
        self.assertIn("Vertederos", self.perfil.folders)

    def test_names_the_project_lacks_are_reported(self) -> None:
        self.assertEqual(unregistered_landmarks(self.perfil, ["Caliche"]), ["Palomares", "Gregal"])

    def test_nothing_missing_when_everything_is_registered(self) -> None:
        self.assertEqual(unregistered_landmarks(self.perfil, ["caliche", " PALOMARES ", "Gregal"]), [])

    def test_comparison_ignores_case_and_padding(self) -> None:
        self.assertEqual(unregistered_landmarks(self.perfil, ["GREGAL "]), ["Caliche", "Palomares"])

    def test_a_trace_without_landfills_has_nothing_to_report(self) -> None:
        perfil = profile_kml(self.write("limpia.kml", trace_kml()))
        self.assertEqual(unregistered_landmarks(perfil, []), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
