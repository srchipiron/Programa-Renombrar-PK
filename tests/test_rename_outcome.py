"""Tests for rename-outcome classification (operator recovery messaging)."""
from __future__ import annotations

import unittest

from src.ui_qt.rename_outcome import classify_rename_outcome


class TestRenameOutcome(unittest.TestCase):
    def test_empty_batch(self) -> None:
        outcome = classify_rename_outcome({"ok": 0, "skipped": 2, "errors": 0, "cancelled": 5})
        self.assertTrue(outcome.is_empty)
        self.assertFalse(outcome.is_partial)
        self.assertFalse(outcome.offer_undo)
        self.assertIn("No se renombró", outcome.dialog_body)
        self.assertIn("cancelaron 5", outcome.dialog_body)

    def test_clean_success(self) -> None:
        outcome = classify_rename_outcome({"ok": 10, "skipped": 1, "errors": 0, "cancelled": 0})
        self.assertFalse(outcome.is_empty)
        self.assertFalse(outcome.is_partial)
        self.assertFalse(outcome.offer_undo)
        self.assertEqual(outcome.dialog_title, "Renombrado completado")

    def test_partial_cancel_offers_undo(self) -> None:
        outcome = classify_rename_outcome(
            {"ok": 7, "skipped": 0, "errors": 0, "cancelled": 13}
        )
        self.assertTrue(outcome.is_partial)
        self.assertTrue(outcome.offer_undo)
        self.assertEqual(outcome.dialog_title, "Renombrado parcial")
        self.assertIn("canceló", outcome.dialog_body)
        self.assertIn("Deshacer", outcome.dialog_body)

    def test_partial_errors_offer_undo(self) -> None:
        outcome = classify_rename_outcome(
            {"ok": 3, "skipped": 1, "errors": 2, "cancelled": 0}
        )
        self.assertTrue(outcome.is_partial)
        self.assertTrue(outcome.offer_undo)
        self.assertIn("error", outcome.dialog_body.lower())

    def test_none_stats_treated_as_empty(self) -> None:
        outcome = classify_rename_outcome(None)
        self.assertTrue(outcome.is_empty)
        self.assertEqual(outcome.ok, 0)

    def test_stuck_mapping_offers_undo_even_when_ok_zero(self) -> None:
        outcome = classify_rename_outcome(
            {
                "ok": 0,
                "skipped": 0,
                "errors": 1,
                "cancelled": 0,
                "mapping": {"PK-STUCK.jpg": "stuck.jpg"},
            }
        )
        self.assertFalse(outcome.is_empty)
        self.assertTrue(outcome.is_partial)
        self.assertTrue(outcome.offer_undo)
        self.assertEqual(outcome.dialog_title, "Renombrado incompleto")
        self.assertIn("Deshacer", outcome.dialog_body)
        self.assertIn("retenidos", outcome.status_line)


class TestUncBackupRisk(unittest.TestCase):
    def test_detects_unc_paths(self) -> None:
        from src.ui_qt.rename_outcome import is_unc_path

        self.assertTrue(is_unc_path(r"\\dsconecta\aeroscan\obra"))
        self.assertTrue(is_unc_path("//dsconecta/aeroscan/obra"))
        self.assertFalse(is_unc_path(r"G:\AEROSCAN\obra"))
        self.assertFalse(is_unc_path(""))

    def test_backup_risk_note_only_for_unc_without_backup(self) -> None:
        from src.ui_qt.rename_outcome import backup_risk_note

        note = backup_risk_note(
            folder=r"\\dsconecta\share\job", create_backup=False
        )
        self.assertIn("UNC", note)
        self.assertIn("_backup_originales", note)
        self.assertEqual(
            backup_risk_note(folder=r"\\dsconecta\share", create_backup=True),
            "",
        )
        self.assertEqual(
            backup_risk_note(folder=r"C:\local\job", create_backup=False),
            "",
        )


if __name__ == "__main__":
    unittest.main()
