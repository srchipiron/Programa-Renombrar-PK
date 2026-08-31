"""The version has to mean something, in every place that states it.

version.py exists because the number used to live only inside installer.iss,
so a build, a window title and an installer could disagree. It then drifted
anyway: the README documented v3.9 while __version__ still said 3.8.0. A
comment asking for the two to be kept in step is not a mechanism.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.core.version import (
    APP_EDITION,
    APP_NAME,
    __version__,
    app_title,
    version_line,
)

RAIZ = Path(__file__).resolve().parent.parent


class VersionFormatTests(unittest.TestCase):
    def test_is_a_release_number(self) -> None:
        self.assertRegex(__version__, r"^\d+\.\d+(\.\d+)?$")

    def test_the_title_identifies_the_build_in_a_screenshot(self) -> None:
        titulo = app_title()
        self.assertIn(__version__, titulo)
        self.assertIn(APP_NAME, titulo)
        self.assertIn(APP_EDITION, titulo)

    def test_the_log_line_identifies_the_build(self) -> None:
        self.assertIn(__version__, version_line())


class VersionAgreementTests(unittest.TestCase):
    """Every other place that writes the number must agree with version.py."""

    def test_the_readme_changelog_leads_with_this_version(self) -> None:
        texto = (RAIZ / "README.md").read_text(encoding="utf-8")
        encabezados = re.findall(r"^###\s+v(\d+\.\d+(?:\.\d+)?)\s", texto, re.M)
        self.assertTrue(encabezados, "el README no tiene registro de cambios")
        self.assertEqual(
            encabezados[0],
            __version__,
            "el registro del README y version.py se han separado: "
            f"README v{encabezados[0]} vs __version__ {__version__}",
        )

    def test_the_installer_fallback_agrees(self) -> None:
        """build.bat injects it, but the fallback is what a manual build uses."""
        iss = RAIZ / "installer.iss"
        if not iss.exists():  # pragma: no cover
            self.skipTest("sin installer.iss")
        encontrado = re.search(
            r'#define\s+AppVersion\s+"([^"]+)"', iss.read_text(encoding="utf-8", errors="replace")
        )
        self.assertIsNotNone(encontrado, "installer.iss sin AppVersion")
        self.assertEqual(encontrado.group(1), __version__)

    def test_the_number_is_written_down_in_one_module(self) -> None:
        """No other source file may hardcode a version literal."""
        sospechosos = []
        for p in (RAIZ / "src").rglob("*.py"):
            if p.name == "version.py":
                continue
            for i, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'["\']v?\d+\.\d+\.\d+["\']', linea) and "version" in linea.lower():
                    sospechosos.append(f"{p.relative_to(RAIZ)}:{i}")
        self.assertEqual(sospechosos, [], f"version fijada fuera de version.py: {sospechosos}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
