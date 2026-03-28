"""Shared logging configuration for harness entrypoints."""
from __future__ import annotations

import logging

from config import settings


def configure_logging(level: str | None = None) -> None:
    resolved = (level or settings.LOG_LEVEL or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, resolved, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
