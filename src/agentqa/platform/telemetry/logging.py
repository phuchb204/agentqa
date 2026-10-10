from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

SAFE_LOG_FIELDS = ("logger", "level", "message", "request_id", "run_id", "execution_id", "worker_id")


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "run_id", "execution_id", "worker_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
