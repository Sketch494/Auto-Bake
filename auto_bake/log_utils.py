# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging for Auto Bake.

A single logger named ``AutoBake`` writes to the system console and mirrors
every record into an in-memory ring buffer so the artist can save a complete
session log to a text file from the UI (Advanced > Save Log).
"""

import logging
import time
from collections import deque

_LOGGER_NAME = "AutoBake"
_MAX_BUFFERED_LINES = 5000

# Ring buffer shared by every handler instance.
_buffer = deque(maxlen=_MAX_BUFFERED_LINES)


class _BufferHandler(logging.Handler):
    """Mirrors formatted log records into the in-memory buffer."""

    def emit(self, record):
        try:
            _buffer.append(self.format(record))
        except Exception:  # pragma: no cover - never let logging crash a bake
            pass


def get_logger():
    """Return the shared Auto Bake logger, creating handlers on first use."""
    logger = logging.getLogger(_LOGGER_NAME)
    if not getattr(logger, "_autobake_configured", False):
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"
        )
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
        buffered = _BufferHandler()
        buffered.setFormatter(formatter)
        logger.addHandler(buffered)
        logger.propagate = False
        logger._autobake_configured = True
    return logger


def set_level(level_name):
    """Set the log level from a preferences enum value."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    get_logger().setLevel(level)


def get_log_text():
    """Return the buffered session log as a single string."""
    header = "Auto Bake session log - saved %s\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), "-" * 60,
    )
    return header + "\n".join(_buffer) + "\n"


def save_log(filepath):
    """Write the buffered log to ``filepath``. Returns the path written."""
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(get_log_text())
    return filepath


def clear_log():
    """Empty the in-memory buffer (used when a new bake starts)."""
    _buffer.clear()
