"""Structured logging configuration using structlog.

All log lines are emitted as JSON in staging/production so they can be
ingested by any log aggregator, and as readable console output locally.
"""
import logging
import sys
from typing import Any

import structlog

from shopflow_configuration import Environment

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    # Explicitly typed as list[Any] from the start, rather than inferring
    # renderer's type from its first assignment and reassigning it in the
    # else branch (mypy narrows `renderer` to JSONRenderer from the first
    # branch, then rejects ConsoleRenderer in the second — a real type
    # error, not a false positive) or concatenating two independently-
    # inferred lists (which mypy widens to list[object], incompatible with
    # structlog.configure's declared Iterable[Callable[...]] parameter
    # type). Building one list and appending sidesteps both without
    # depending on structlog's own internal type alias names, which vary
    # enough across versions that hardcoding one felt riskier than this.
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
