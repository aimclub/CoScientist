"""Pure state transition rules for a Codesynapse external run."""

from __future__ import annotations

from CoScientist.integrations.codesynapse.models import RunState


class InvalidRunTransition(ValueError):
    """Raised when a caller attempts to revive or skip a run state."""


_ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.QUEUED: frozenset({RunState.STARTING, RunState.CANCELLED}),
    RunState.STARTING: frozenset({RunState.RUNNING, RunState.QUEUED, RunState.FAILED, RunState.CANCELLED}),
    RunState.RUNNING: frozenset(
        {RunState.WAITING_FOR_HUMAN, RunState.CANCELLING, RunState.COMPLETED, RunState.FAILED, RunState.INTERRUPTED}
    ),
    RunState.WAITING_FOR_HUMAN: frozenset(
        {RunState.RUNNING, RunState.CANCELLING, RunState.FAILED, RunState.CANCELLED, RunState.INTERRUPTED}
    ),
    RunState.CANCELLING: frozenset({RunState.CANCELLED, RunState.INTERRUPTED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.INTERRUPTED: frozenset(),
}


def transition(current: RunState, target: RunState) -> RunState:
    """Validate and return an allowed transition without mutating storage."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidRunTransition(f"cannot transition from {current.value} to {target.value}")
    return target
