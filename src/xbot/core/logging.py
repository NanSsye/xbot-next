from __future__ import annotations

import sys

from loguru import logger


def configure_logging(debug: bool = False) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        enqueue=True,
        backtrace=debug,
        diagnose=debug,
    )


__all__ = ["configure_logging", "logger"]

