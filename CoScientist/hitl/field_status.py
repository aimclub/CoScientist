"""Per-field provenance status, shared by structured HITL intakes.

Lifted from the microfluidics ТЗ model (``microfluidics/models.py``) so every
structured intake — the ТЗ and the research frame (``context_init/models.py``) —
uses one status vocabulary. A field is "open" when it has no usable value yet.
That is what a HITL form uses to decide which fields to ask the human to fill.

Statuses are plain string Literals (not an Enum) so the dicts ADK stores in
session state and injects into downstream prompts render as readable text.
"""
from __future__ import annotations

from typing import Literal

# How a field value was obtained — downstream code treats these differently.
FieldStatus = Literal[
    "задано заказчиком",
    "уточнено оператором",
    "не задано",
    "свободный комментарий",
    "рассчитывается агентом",
    "заполнено агентом",
]

# Statuses that mean "there is no usable value here yet".
OPEN_STATUSES = ("не задано", "рассчитывается агентом")

# The operator set this value by hand in a HITL form.
OPERATOR_STATUS = "уточнено оператором"

# The operator left the field empty in a HITL form and the agent filled it —
# a working value the operator is shown again to check. Set by the system
# only, never by the model on its own.
AGENT_FILLED_STATUS = "заполнено агентом"


def is_open(status: str) -> bool:
    """True when the field still needs a value (drives the HITL form)."""
    return status in OPEN_STATUSES


__all__ = [
    "AGENT_FILLED_STATUS",
    "FieldStatus",
    "OPEN_STATUSES",
    "OPERATOR_STATUS",
    "is_open",
]
