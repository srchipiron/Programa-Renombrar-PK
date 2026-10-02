"""Console logging must survive PK typography on a non-UTF-8 code page.

Coverage/rename warnings contain ``≥``, ``·`` and ``→``. With stderr redirected
to a file or pipe on Windows the ANSI code page applies and ``logging`` used to
swallow the message behind a "--- Logging error ---" dump.
"""
from __future__ import annotations

import io
import logging
import sys
import unittest

from src.core.logging_config import _harden_console_encoding

MESSAGE = "Cobertura 3 huecos ≥100 m · PK-1+000 → PK-2+000"


class ConsoleEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_stderr = sys.stderr
        self._orig_stdout = sys.stdout
        self.addCleanup(self._restore)
        self.buffer = io.BytesIO()
        sys.stderr = io.TextIOWrapper(self.buffer, encoding="cp1252", line_buffering=True)
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", line_buffering=True)

    def _restore(self) -> None:
        sys.stderr = self._orig_stderr
        sys.stdout = self._orig_stdout

    def test_raw_cp1252_stream_would_fail(self) -> None:
        with self.assertRaises(UnicodeEncodeError):
            sys.stderr.write(MESSAGE)

    def test_hardened_stream_keeps_the_message(self) -> None:
        _harden_console_encoding()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("test.console.encoding")
        logger.propagate = False
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        logger.warning(MESSAGE)
        handler.flush()

        written = self.buffer.getvalue().decode("cp1252")
        self.assertNotIn("Logging error", written)
        self.assertIn("Cobertura 3 huecos", written)
        self.assertIn("PK-1+000", written)

    def test_hardening_is_idempotent_and_safe_without_streams(self) -> None:
        _harden_console_encoding()
        _harden_console_encoding()
        sys.stderr = None  # windowed PyInstaller build
        sys.stdout = None
        _harden_console_encoding()  # must not raise


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
