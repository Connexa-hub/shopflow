"""Structured logging configuration using structlog. Identical pattern to
auth-service — a good candidate to extract into packages/utilities in a
later phase once a third service confirms the pattern is truly stable and
doesn't need per-service tweaks."""
import logging
import sys
from typing import Any

import structlog
from shopflow_configuration import Environment

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    # See auth-service's app/core/logging.py for why this is built as one
    # explicitly list[Any]-typed list with .append(), rather than
    # reassigning a narrowly-inferred `renderer` variable across branches
    # and concatenating two separately-inferred lists — both trigger real
    # mypy errors (JSONRenderer/ConsoleRenderer type mismatch, and
    # list[object] vs the Iterable[Callable[...]] structlog.configure
    # expects) that this sidesteps without hardcoding structlog's internal
    # type alias names.
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
