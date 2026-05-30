from __future__ import annotations

import sys
import logging
import os
from pathlib import Path

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
    if os.environ.get("XBOT_DISABLE_FILE_LOGGING") != "1":
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "xbot.log",
            level="DEBUG" if debug else "INFO",
            rotation="10 MB",
            retention=10,
            encoding="utf-8",
            enqueue=True,
            backtrace=debug,
            diagnose=debug,
        )


def configure_terminal_logging(*, debug: bool = False, cwd: Path | None = None) -> None:
    os.environ["XBOT_TERMINAL_LOGGING"] = "1"
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("alembic.runtime.migration").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logger.remove()
    log_dir = (cwd or Path.cwd()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "xbot-terminal.log",
        level="DEBUG" if debug else "INFO",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
        backtrace=debug,
        diagnose=debug,
    )
    if debug:
        logger.add(
            sys.stderr,
            level="DEBUG",
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )


__all__ = ["configure_logging", "configure_terminal_logging", "logger"]
