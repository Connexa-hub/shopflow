"""Structured logging configuration using structlog. Same pattern as
auth-service/inventory-service — see auth-service's app/core/logging.py
for why `processors` is built as one explicitly list[Any]-typed list with
.append() in each branch, rather than reassigning a narrowly-inferred bare
variable across if/else (a real mypy error caught and fixed there; written
correctly here from the start instead of repeating it a third time)."""
import logging
import sys
from typing import Any

import structlog
from shopflow_configuration import Environment

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.environment == Environment.PRODUCTION:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
