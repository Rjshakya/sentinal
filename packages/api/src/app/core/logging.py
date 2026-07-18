from __future__ import annotations

import json
import logging
from typing import Literal

StructuredLogLevel = Literal["INFO", "ERROR"]


class JsonFormatter(logging.Formatter):
    """Emit every log record as a single JSON object.

    Structured data is expected under ``record.structured_data``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "data": getattr(record, "structured_data", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


logger = logging.getLogger(__name__)


def structured_log(
    level: StructuredLogLevel,
    msg: str,
    object: dict,
    *,
    exc_info: bool = False,
) -> None:
    """Emit a structured log entry as JSON.

    Args:
        level: INFO or ERROR.
        msg: Short event/message key.
        object: Arbitrary serializable dict attached under ``data``.
        exc_info: If True, include the current exception traceback.
    """
    if level == "INFO":
        logger.info(msg, extra={"structured_data": object}, exc_info=exc_info)
    elif level == "ERROR":
        logger.error(msg, extra={"structured_data": object}, exc_info=exc_info)
    else:
        raise ValueError(f"Unsupported level: {level}")


def configure_structured_logging() -> None:
    """Make the root logger emit JSON."""
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(logging.INFO)
