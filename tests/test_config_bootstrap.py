"""Config bootstrap from config.example.json."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.config import ConfigManager, _CONFIG_EXAMPLE


class TestConfigBootstrap(unittest.TestCase):
    def test_creates_config_from_example_when_missing(self) -> None:
        if not _CONFIG_EXAMPLE.is_file():
            self.skipTest("config.example.json not in project root")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            self.assertFalse(target.exists())
            manager = ConfigManager(str(target))
            self.assertTrue(target.exists())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("threshold", data)
            self.assertEqual(manager.config.threshold, data["threshold"])


    def test_invalid_json_resets_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text("{not valid json", encoding="utf-8")
            manager = ConfigManager(str(target))
            self.assertEqual(manager.config.threshold, 30.0)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["threshold"], 30.0)


if __name__ == "__main__":
    unittest.main()
