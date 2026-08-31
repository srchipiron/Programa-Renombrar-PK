"""Single source of truth for the application's identity and version.

The version used to exist only as a literal inside ``installer.iss``, so a
build, a window title and an installer could disagree about what they were.
When an operator reports a problem, the first thing needed is *which* build
they are running — that is what this makes answerable.

Bump :data:`__version__` when releasing; ``build.bat`` passes it to Inno Setup
and :mod:`src.core.diagnostics` stamps it on every report.
"""
from __future__ import annotations

#: Kept in step with the newest changelog heading in the README and with
#: the fallback in installer.iss; tests/test_version.py asserts all three.
__version__ = "3.9.2"

APP_NAME = "Renombrador PKS"
#: Kept in the window title: the operators call it by the year.
APP_EDITION = "2026"
ORGANISATION = "AEROSCAN"


def app_title() -> str:
    """Window title, with the version so a screenshot identifies the build."""
    return f"{APP_NAME} {APP_EDITION} · v{__version__}"


def version_line() -> str:
    """One-line identity for logs, diagnostics and the help tab."""
    return f"{APP_NAME} {APP_EDITION} v{__version__} ({ORGANISATION})"
