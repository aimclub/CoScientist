from __future__ import annotations

import logging
import os

from loguru import logger as _loguru_logger

_FULL_LEVEL = "TRACE"

logging.addLevelName(5, "TRACE")
_log = logging.getLogger("CoScientist.fedotmas")
_log.setLevel(1)
if not any(isinstance(h, logging.StreamHandler) for h in _log.handlers):
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    )
    _log.addHandler(_handler)

_patched = False


def _sink(message) -> None:
    record = message.record
    name = record["extra"].get("name", "fedotmas")
    _log.log(
        record["level"].no,
        "%s:%s:%s | %s",
        name,
        record["function"],
        record["line"],
        record["message"],
    )


def _install_bridge(level: str | None = None) -> None:
    resolved = (level or os.getenv("FEDOTMAS_LOG_LEVEL") or _FULL_LEVEL).upper()
    _loguru_logger.remove()
    _loguru_logger.add(_sink, level=resolved)


def patch_fedotmas_logging() -> None:
    global _patched
    if _patched:
        return
    from fedotmas.core import base as _fedotmas_base

    _fedotmas_base.setup_logging = _install_bridge
    _install_bridge()
    _patched = True
