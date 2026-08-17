from __future__ import annotations

import atexit
import logging
import sys
import threading
from pathlib import Path

from bot.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_PATH = LOG_DIR / "bot.log"
MAX_LOG_LINES = 100
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class TailFileHandler(logging.FileHandler):
    """File handler that keeps only the last N lines on disk."""

    def __init__(self, filename: Path, *, max_lines: int = MAX_LOG_LINES) -> None:
        filename.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(filename, mode="a", encoding="utf-8")
        self.max_lines = max_lines
        self._trim_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self._trim()

    def _trim(self) -> None:
        with self._trim_lock:
            try:
                self.flush()
                path = Path(self.baseFilename)
                text = path.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines(keepends=True)
                if len(lines) <= self.max_lines:
                    return
                path.write_text("".join(lines[-self.max_lines :]), encoding="utf-8")
            except Exception:
                pass


def setup_file_logging() -> Path:
    """Attach a 100-line file logger plus crash/exit hooks. Returns log path."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT)
    file_handler = TailFileHandler(LOG_PATH, max_lines=MAX_LOG_LINES)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(
        isinstance(h, TailFileHandler) and Path(getattr(h, "baseFilename", "")) == LOG_PATH
        for h in root.handlers
    ):
        root.addHandler(file_handler)

    def _excepthook(exc_type, exc, tb) -> None:
        logging.getLogger("bot.crash").critical(
            "Unhandled exception — process dying",
            exc_info=(exc_type, exc, tb),
        )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    atexit.register(lambda: logging.getLogger("bot.crash").warning("Process exiting (atexit)"))
    return LOG_PATH
