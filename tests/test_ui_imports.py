"""Smoke tests ensuring the Qt UI modules are syntactically valid.

We parse the source files without importing them so the tests remain fast and
headless-friendly (no ``QApplication`` is spun up here).
"""
import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_QT_DIR = PROJECT_ROOT / "src" / "ui_qt"


class TestUIQtModulesParse(unittest.TestCase):
    """Every module under ``src/ui_qt`` must be valid Python."""

    def test_all_modules_parse(self) -> None:
        modules = list(UI_QT_DIR.glob("*.py"))
        self.assertGreater(len(modules), 0, "src/ui_qt should contain Python modules")
        for module in modules:
            with self.subTest(module=module.name):
                source = module.read_text(encoding="utf-8")
                # ast.parse raises SyntaxError if the module is broken.
                ast.parse(source)


if __name__ == "__main__":
    unittest.main()
