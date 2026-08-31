"""Logging handler that forwards records to the Qt UI via a Signal."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class QtLogHandler(logging.Handler, QObject):
    """A :mod:`logging` handler that emits a Qt signal for every record.

    The signal is ``message(level_name, formatted_message)`` and is connected
    to the log tab from the main window.  Because Qt signals are thread-safe,
    worker threads can safely log through this handler without any extra
    synchronization.
    """

    message = Signal(str, str)

    def __init__(self, level: int = logging.INFO) -> None:
        logging.Handler.__init__(self, level)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - logging API
        try:
            if record.levelno < self.level:
                return
            self.message.emit(record.levelname, self.format(record))
        except Exception:  # pragma: no cover - defensive
            self.handleError(record)
