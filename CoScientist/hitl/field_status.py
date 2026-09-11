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
    "автоподбор",
    "уточнено оператором",
    "не задано",
    "не требуется",
    "свободный комментарий",
    "рассчитывается агентом",
    "заполнено агентом",
]

# Statuses that mean "there is no usable value here yet".
OPEN_STATUSES = ("не задано", "рассчитывается агентом")

# The agent inferred this value itself (from the request or the domain) — the
# customer did not name it and no human has confirmed it yet.
AUTO_STATUS = "автоподбор"

# A human set or corrected this value when reviewing (a HITL form, or
# corrections the agent applied on the human's word).
OPERATOR_STATUS = "уточнено оператором"

# Deliberately left unconstrained: the parameter does not matter, any value
# will do, so it must not narrow the solution. Not open — nobody is asked to
# fill it — and it needs no value of its own.
NOT_REQUIRED_STATUS = "не требуется"
NOT_REQUIRED_VALUE = "Не требуется — без ограничения"

# The operator left the field empty in a HITL form and the agent filled it —
# a working value the operator is shown again to check. Set by the system
# only, never by the model on its own.
AGENT_FILLED_STATUS = "заполнено агентом"


def is_open(status: str) -> bool:
    """True when the field still needs a value (drives the HITL form)."""
    return status in OPEN_STATUSES


__all__ = [
    "AGENT_FILLED_STATUS",
    "AUTO_STATUS",
    "FieldStatus",
    "NOT_REQUIRED_STATUS",
    "NOT_REQUIRED_VALUE",
    "OPEN_STATUSES",
    "OPERATOR_STATUS",
    "is_open",
]
