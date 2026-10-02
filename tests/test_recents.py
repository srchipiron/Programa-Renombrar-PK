"""Tests for the bounded MRU list helper used by recent folders/KMLs."""
from __future__ import annotations

import unittest

from src.ui_qt.recents import push_recent


class TestPushRecent(unittest.TestCase):
    def test_inserts_new_value_at_front(self) -> None:
        result = push_recent(["a", "b"], "c", max_items=5)
        self.assertEqual(result, ["c", "a", "b"])

    def test_moves_existing_value_to_front_without_duplicating(self) -> None:
        result = push_recent(["a", "b", "c"], "b", max_items=5)
        self.assertEqual(result, ["b", "a", "c"])

    def test_caps_at_max_items(self) -> None:
        result = push_recent(["a", "b", "c"], "d", max_items=3)
        self.assertEqual(result, ["d", "a", "b"])

    def test_empty_value_returns_copy_unchanged(self) -> None:
        original = ["a", "b"]
        result = push_recent(original, "", max_items=5)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_does_not_mutate_input_list(self) -> None:
        original = ["a", "b"]
        push_recent(original, "c", max_items=5)
        self.assertEqual(original, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
