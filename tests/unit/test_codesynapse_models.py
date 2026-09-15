from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from CoScientist.integrations.codesynapse.models import (
    ArtifactPart,
    IntegrationRun,
    RunState,
    TerminalArtifacts,
    TraceEvent,
)


def test_trace_event_requires_positive_sequence_and_project_scope():
    with pytest.raises(ValidationError, match="sequence"):
        TraceEvent(
            event_id="event-1",
            run_id="run-1",
            sequence=0,
            tenant_id="tenant-1",
            project_id="project-1",
            type="run.started",
        )

    event = TraceEvent(
        event_id="event-1",
        run_id="run-1",
        sequence=1,
        tenant_id="tenant-1",
        project_id="project-1",
        type="run.started",
        occurred_at=datetime.now(timezone.utc),
    )

    assert event.sequence == 1


def test_completed_terminal_artifacts_require_inline_final_report():
    with pytest.raises(ValidationError, match="final_report"):
        TerminalArtifacts(state=RunState.COMPLETED)

    result = TerminalArtifacts(
        state=RunState.COMPLETED,
        final_report=ArtifactPart(
            name="final_report",
            mime_type="text/markdown",
            text="# Result",
        ),
    )

    assert result.final_report.name == "final_report"


def test_integration_run_rejects_blank_external_identity():
    with pytest.raises(ValidationError, match="external_run_id"):
        IntegrationRun(
            external_run_id=" ",
            tenant_id="tenant-1",
            project_id="project-1",
        )
