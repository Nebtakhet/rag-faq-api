# Logging configuration for the application.

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime

_request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_context.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id_context.get(),
        }
        for field in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload)


def configure_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
