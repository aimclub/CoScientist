"""Stable, transport-neutral contracts for the Codesynapse integration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RunState(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_RUN_STATES = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.INTERRUPTED}
)


class ArtifactPart(BaseModel):
    """A small A2A artifact part or a metadata-only reference to a large object."""

    name: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    text: str | None = None
    data: dict[str, Any] | None = None
    artifact_id: str | None = None
    checksum_sha256: str | None = None

    @model_validator(mode="after")
    def validate_payload_or_reference(self) -> "ArtifactPart":
        values = [self.text is not None, self.data is not None, self.artifact_id is not None]
        if sum(values) != 1:
            raise ValueError("artifact part must contain exactly one inline payload or artifact reference")
        if self.text is not None and len(self.text.encode("utf-8")) > 512 * 1024:
            raise ValueError("inline artifact text exceeds 512 KiB")
        if self.data is not None and len(json.dumps(self.data, separators=(",", ":")).encode("utf-8")) > 512 * 1024:
            raise ValueError("inline artifact data exceeds 512 KiB")
        if self.artifact_id is not None and not self.checksum_sha256:
            raise ValueError("artifact references require checksum_sha256")
        return self


class TerminalArtifacts(BaseModel):
    """The fixed artifact contract returned by a terminal A2A task."""

    state: RunState
    final_report: ArtifactPart | None = None
    structured_result: ArtifactPart | None = None
    artifacts_manifest: ArtifactPart | None = None
    error: ArtifactPart | None = None

    @model_validator(mode="after")
    def validate_terminal_contract(self) -> "TerminalArtifacts":
        if self.state == RunState.COMPLETED and self.final_report is None:
            raise ValueError("final_report is required for a completed run")
        if self.state != RunState.COMPLETED and self.error is None:
            raise ValueError("error is required for a failed terminal run")
        return self


class IntegrationRun(BaseModel):
    """Durable external identity and state of one Codesynapse-owned run."""

    external_run_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    state: RunState = RunState.QUEUED
    a2a_task_id: str | None = None
    coscientist_run_id: str | None = None
    control_token_hash: str | None = None
    terminal_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def reject_blank_identity_fields(self) -> "IntegrationRun":
        for field_name in ("external_run_id", "tenant_id", "project_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        return self


class A2ATaskRecord(BaseModel):
    """Persistent task representation used to answer A2A ``tasks/get``."""

    a2a_task_id: str = Field(min_length=1)
    external_run_id: str = Field(min_length=1)
    coscientist_run_id: str = Field(min_length=1)
    state: RunState = RunState.RUNNING
    artifacts: TerminalArtifacts | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TraceEvent(BaseModel):
    """One externally visible, ordered fact about a CoScientist run."""

    schema_version: str = "coscientist-v1"
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node_id: str | None = None
    parent_node_id: str | None = None
    agent: str | None = None
    target: str | None = None
    status: str | None = None
    summary: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
