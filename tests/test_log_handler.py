"""Unit tests for the Qt log handler bridge."""
import logging
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src.ui_qt.log_handler import QtLogHandler  # noqa: E402


class TestQtLogHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.handler = QtLogHandler(level=logging.DEBUG)
        self.received: list[tuple[str, str]] = []
        self.handler.message.connect(lambda lvl, msg: self.received.append((lvl, msg)))

    def test_emits_signal_with_level_and_message(self) -> None:
        record = logging.LogRecord(
            name="tests",
            level=logging.WARNING,
            pathname=__file__,
            lineno=42,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        self.handler.handle(record)
        self.assertEqual(len(self.received), 1)
        level, message = self.received[0]
        self.assertEqual(level, "WARNING")
        self.assertEqual(message, "hello world")

    def test_level_filter_is_respected(self) -> None:
        self.handler.setLevel(logging.ERROR)

        for level in (logging.DEBUG, logging.INFO, logging.WARNING):
            self.handler.handle(
                logging.LogRecord("tests", level, __file__, 1, "nope", None, None)
            )
        self.handler.handle(
            logging.LogRecord("tests", logging.ERROR, __file__, 1, "boom", None, None)
        )

        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0][0], "ERROR")


if __name__ == "__main__":
    unittest.main()
