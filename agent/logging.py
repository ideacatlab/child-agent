"""Tiny structured-ish logging built on the stdlib. No dependencies."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_CONFIGURED = False


def _level() -> int:
    name = os.environ.get("AGENT_LOG", "info").upper()
    return getattr(logging, name, logging.INFO)


def configure(log_dir: Path | None = None) -> None:
    """Configure root logging once. Streams to stderr; optionally tees to a file."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers: list[logging.Handler] = []

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%H:%M:%S")
    )
    handlers.append(stream)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fileh = logging.FileHandler(log_dir / "agent.log")
            fileh.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s")
            )
            handlers.append(fileh)
        except OSError:
            pass  # never let logging setup crash the agent

    logging.basicConfig(level=_level(), handlers=handlers, force=True)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        configure()
    return logging.getLogger(name)
