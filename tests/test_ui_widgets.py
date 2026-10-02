"""Smoke tests for Qt widgets using pytest-qt.

These tests spin up a ``QApplication`` (provided by the ``qtbot`` fixture)
and drive the widgets enough to validate that signals, models and the
sidebar/histogram paths work without a running main window.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from src.core.config import ConfigManager, AppConfig  # noqa: E402
from src.core.models import PhotoItem  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    cfg_file = tmp_path / "config.json"
    return ConfigManager(str(cfg_file))


def _make_item(name: str, inside: bool, excluded: bool = False) -> PhotoItem:
    return PhotoItem(
        path=f"/virtual/{name}",
        name=name,
        lat=40.0,
        lon=-3.0,
        distance=5.0 if inside else 300.0,
        is_inside_threshold=inside,
        excluded=excluded,
        new_name_base=f"PK-1_{name}" if inside else "",
    )


def test_sidebar_analysis_guards(qtbot, cfg):
    from src.ui_qt.sidebar import Sidebar

    sidebar = Sidebar(cfg)
    qtbot.addWidget(sidebar)

    assert not sidebar.analyze_btn.isEnabled()
    assert not sidebar.process_btn.isEnabled()
    sidebar.set_has_analysis(True)
    assert sidebar.process_btn.isEnabled()
    # Analizar remains gated on valid paths even after analysis exists.
    assert not sidebar.analyze_btn.isEnabled()
    sidebar.set_workflow_hint("<b>OK</b>", level="success")
    assert sidebar.workflow_banner.property("level") == "success"


def test_sidebar_analyze_enabled_when_inputs_valid(qtbot, cfg, tmp_path):
    from src.ui_qt.sidebar import Sidebar

    folder = tmp_path / "photos"
    folder.mkdir()
    kml = tmp_path / "traza.kml"
    kml.write_text("<kml></kml>", encoding="utf-8")

    sidebar = Sidebar(cfg)
    qtbot.addWidget(sidebar)
    assert not sidebar.analyze_btn.isEnabled()

    sidebar.set_values(folder=str(folder))
    assert not sidebar.analyze_btn.isEnabled()
    folder_ok, kml_ok = sidebar.inputs_ready()
    assert folder_ok and not kml_ok

    sidebar.set_values(kml_file=str(kml))
    assert sidebar.analyze_btn.isEnabled()
    assert sidebar.inputs_ready() == (True, True)


def test_preview_empty_state_mentions_auto_threshold(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    text = preview.empty_state.text()
    assert "umbral" in text.lower()
    assert "F5" in text


def test_preview_empty_state_stack(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    preview.set_items([])
    assert preview.content_stack.currentIndex() == 0
    preview.set_items([_make_item("a.jpg", True)])
    assert preview.content_stack.currentIndex() == 1


def test_sidebar_set_values_and_histogram(qtbot, cfg):
    from src.ui_qt.sidebar import Sidebar

    sidebar = Sidebar(cfg)
    qtbot.addWidget(sidebar)

    sidebar.set_values(folder="C:/tmp", kml_file="", threshold=42.0, suffix="hola",
                       create_backup=True)
    conf = sidebar.get_config()
    assert conf.folder == "C:/tmp"
    assert conf.threshold == 42.0
    assert conf.suffix == "hola"
    assert conf.create_backup is True

    # Histogram accepts arbitrary samples without crashing.
    sidebar.set_histogram([10.0, 25.0, 50.0, 200.0], threshold=30.0)


def test_preview_table_exclusion_toggle(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    items = [_make_item("a.jpg", True), _make_item("b.jpg", True)]
    preview.set_items(items)
    preview.update_preview(items)

    # Check initial count
    model = preview.model
    assert model.rowCount() == 2

    # Toggle exclusion on first row via setData
    from PySide6.QtCore import Qt
    idx = model.index(0, 0)
    ok = model.setData(idx, Qt.Unchecked, Qt.CheckStateRole)
    assert ok
    assert items[0].excluded is True


def test_preview_status_filter_uses_proxy_rows(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    inside = _make_item("in.jpg", True)
    outside = _make_item("out.jpg", False)
    preview.set_items([inside, outside])
    preview.update_preview([inside, outside])

    preview.status_filter.setCurrentText("Solo Dentro")
    preview._apply_filter()

    visible = [
        r
        for r in range(preview.proxy.rowCount())
        if not preview.table.isRowHidden(r)
    ]
    assert len(visible) == 1
    source_row = preview.proxy.mapToSource(preview.proxy.index(visible[0], 0)).row()
    assert preview.model.item_at(source_row).name == "in.jpg"


def test_preview_select_all_and_exclude_all(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    items = [_make_item(f"f{i}.jpg", True) for i in range(3)]
    preview.set_items(items)
    preview.update_preview(items)

    preview.model.set_all_excluded(True)
    assert all(it.excluded for it in items)

    preview.model.set_all_excluded(False)
    assert all(not it.excluded for it in items)


def test_preview_exclude_duplicates_button(qtbot):
    from src.ui_qt.preview_tab import PreviewTab

    preview = PreviewTab()
    qtbot.addWidget(preview)
    keep = _make_item("keep.jpg", True)
    dupe = _make_item("dupe.jpg", True)
    dupe.duplicate_of = "keep.jpg"
    already = _make_item("already.jpg", True)
    already.duplicate_of = "keep.jpg"
    already.excluded = True
    preview.set_items([keep, dupe, already])
    preview.update_preview([keep, dupe, already])

    changed = preview.model.exclude_duplicates()
    assert changed == 1
    assert not keep.excluded
    assert dupe.excluded
    assert already.excluded
    preview.refresh_counts()
    assert "excluidas" in preview.count_label.text()


def test_histogram_handles_no_data(qtbot):
    from src.ui_qt.histogram import DistanceHistogram

    hist = DistanceHistogram()
    qtbot.addWidget(hist)
    hist.set_data([], 30.0)
    hist.set_data([5.0, 10.0, 40.0], 30.0)
    # If we got here without raising in paintEvent we're good.
    hist.repaint()


def test_theme_resolves_system():
    from src.ui_qt import theme

    assert theme.resolve("dark") == "dark"
    assert theme.resolve("light") == "light"
    assert theme.resolve("system") in ("dark", "light")
    assert theme.toggle("dark") == "light"
    assert theme.toggle("light") == "system"
    assert theme.toggle("system") == "dark"


def test_undo_history_roundtrip(tmp_path):
    from src.ui_qt.undo_history import UndoHistory, apply_undo

    db = tmp_path / "undo.sqlite"
    history = UndoHistory(db)
    folder = tmp_path / "photos"
    folder.mkdir()

    # Simulate renamed files.
    (folder / "PK-1_a.jpg").write_bytes(b"1")
    (folder / "PK-1_b.jpg").write_bytes(b"2")

    mapping = {"PK-1_a.jpg": "a.jpg", "PK-1_b.jpg": "b.jpg"}
    row_id = history.record(str(folder), mapping)
    assert row_id > 0

    entries = history.list_entries()
    assert len(entries) == 1
    summary = apply_undo(entries[0])
    assert summary["ok"] == 2
    assert (folder / "a.jpg").exists()
    assert (folder / "b.jpg").exists()
