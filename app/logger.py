from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal

from rich.logging import RichHandler


LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


def _normalize_level(level: str | None) -> str:
    if not level:
        return "INFO"
    return str(level).strip().upper()


@lru_cache
def setup_logging(level: str | None = None) -> None:
    """
    Configura logging global (root) con RichHandler.

    Idempotente: gracias a lru_cache se ejecuta solo una vez por proceso.
    """
    resolved_level = _normalize_level(level or os.getenv("LOG_LEVEL") or os.getenv("APP_LOG_LEVEL"))

    root = logging.getLogger()
    root.setLevel(resolved_level)

    # Evita doble logging si uvicorn ya configuró handlers.
    if any(isinstance(h, RichHandler) for h in root.handlers):
        return

    handler = RichHandler(
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_time=True,
        show_level=True,
        show_path=False,
        markup=False,
    )
    formatter = logging.Formatter("%(name)s - %(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Alinea loggers típicos de servidores.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).setLevel(resolved_level)


def get_logger(name: str) -> logging.Logger:
    # Si alguien lo usa antes del startup, igual queda razonable.
    setup_logging()
    return logging.getLogger(name)
