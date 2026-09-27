"""Experiment Module runtime errors — imported by helpers."""
from __future__ import annotations

from typing import Any


class ExperimentRuntimeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, Any]:
        return {"status": "error", "error_code": self.code, "message": str(self)}


__all__ = ["ExperimentRuntimeError"]
