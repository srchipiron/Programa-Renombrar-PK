"""Shared pytest fixtures.

Ensures a single ``QApplication`` instance exists for the whole suite so that
Qt-based tests (pytest-qt and plain unittest) coexist without crashing on
Windows when pytest-qt would otherwise try to create a second app after
``QCoreApplication`` has already been initialised.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - PySide6 required at runtime
    QApplication = None  # type: ignore[assignment]


@pytest.fixture(scope="session", autouse=True)
def _shared_qapp():
    if QApplication is None:
        yield None
        return
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
