import pytest

from CoScientist.integrations.codesynapse.models import RunState
from CoScientist.integrations.codesynapse.state import InvalidRunTransition, transition


def test_run_moves_from_queue_to_working_via_starting():
    assert transition(RunState.QUEUED, RunState.STARTING) is RunState.STARTING
    assert transition(RunState.STARTING, RunState.RUNNING) is RunState.RUNNING


def test_terminal_run_cannot_be_restarted():
    with pytest.raises(InvalidRunTransition):
        transition(RunState.COMPLETED, RunState.RUNNING)


def test_waiting_for_human_can_only_leave_to_running_or_terminal_state():
    assert transition(RunState.WAITING_FOR_HUMAN, RunState.RUNNING) is RunState.RUNNING
    assert transition(RunState.WAITING_FOR_HUMAN, RunState.FAILED) is RunState.FAILED

    with pytest.raises(InvalidRunTransition):
        transition(RunState.WAITING_FOR_HUMAN, RunState.STARTING)
