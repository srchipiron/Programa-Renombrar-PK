"""
Centralized logging configuration for the application.
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def _harden_console_encoding() -> None:
    """Stop unencodable glyphs from blowing up console logging.

    Coverage and rename warnings carry PK typography (``≥``, ``·``, ``→``).
    When stderr is redirected to a pipe or file, Windows picks the ANSI code
    page and ``logging`` raises ``UnicodeEncodeError``, replacing the message
    with a "--- Logging error ---" dump. Switching the error handler keeps the
    line (escaped) whatever the code page is; the file handlers stay UTF-8.
    """
    for stream in (sys.stderr, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):  # pragma: no cover - exotic streams
            continue

class LoggingManager:
    """Manages application logging with rotation and structured output."""
    
    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Configure logging with both file and console handlers."""
        _harden_console_encoding()
        # Create logs directory
        self.log_dir.mkdir(exist_ok=True)
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        simple_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )
        
        # File handler with rotation
        log_file = self.log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(detailed_formatter)
        file_handler.setLevel(self.log_level)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(simple_formatter)
        console_handler.setLevel(logging.WARNING)  # Only warnings and errors to console
        
        # Error file handler
        error_log_file = self.log_dir / f"errors_{datetime.now().strftime('%Y%m%d')}.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setFormatter(detailed_formatter)
        error_handler.setLevel(logging.ERROR)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Add handlers
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        root_logger.addHandler(error_handler)
        
        # Suppress noisy third-party loggers
        logging.getLogger('PIL').setLevel(logging.WARNING)
        logging.getLogger('shapely').setLevel(logging.WARNING)
    
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """Get a logger instance for a specific module."""
        return logging.getLogger(name)
    
        
        # Update file handler level
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.FileHandler) and not handler.baseFilename.endswith('errors_'):
                handler.setLevel(self.log_level)

# Global logging manager instance
_logging_manager: Optional[LoggingManager] = None

def initialize_logging(log_dir: str = "logs", log_level: str = "INFO") -> None:
    """Initialize the logging system."""
    global _logging_manager
    _logging_manager = LoggingManager(log_dir, log_level)

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return LoggingManager.get_logger(name)
