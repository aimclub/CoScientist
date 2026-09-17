"""Fail-closed plan/result review agents."""
from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, AsyncGenerator, Literal

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from CoScientist.config import get_settings
from CoScientist.experiments.critique import PlanValidationError, validate_and_critique_plan
from CoScientist.experiments.runtime import approve_plan, initialize_runtime, mark_result_review
from CoScientist.experiments.runtime.shared import audit
from CoScientist.experiments.runtime.state_machine import REPLAN_ROUNDS_KEY
from CoScientist.experiments.schemas import ExperimentPlan
from CoScientist.graph.session_scope import session_key
from CoScientist.hitl.handler import AbstractHITLHandler, DelegatingHITLHandler
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.hitl.session_agent import SessionAgent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_AUTO_APPROVE_TRUTHY = frozenset({"1", "true", "yes", "on"})
_OK_TASK_STATUSES = frozenset({"done", "done_with_warnings", "skipped", "success", "completed", "partial", "partial_success"})
_EVIDENCE_ROUTES = frozenset({"research", "medical"})


def _publish_approved_plan_to_graph(ctx: InvocationContext, state: Any) -> None:
    """Best-effort: mirror the approved plan into the research graph
    (VerificationMethod per task + Hypothesis —tested_by→ VM). A graph failure
    must never break the approve itself."""
    try:
        from CoScientist.experiments.runtime.graph_bridge import publish_plan_to_graph
        from CoScientist.graph.research.store import get_research_graph

        publish_plan_to_graph(get_research_graph(ctx), state)
    except Exception as exc:  # noqa: BLE001 — approve wins over graph mirroring
        audit(logger, f"EXPERIMENT_GRAPH_PLAN_PUBLISH_FAILED error={exc}",
              level=logging.WARNING)


def result_tasks_ok(runtime: dict[str, Any] | None) -> bool:
    """Compute tasks must succeed. Failed literature/medical is ok if unused as input."""
    if not isinstance(runtime, dict):
        return False
    if runtime.get("tasks_ok") is True:
        return True
    raw_tasks = runtime.get("tasks") or {}
    if isinstance(raw_tasks, list):
        tasks = {str(t.get("id") or i): t for i, t in enumerate(raw_tasks) if isinstance(t, dict)}
    elif isinstance(raw_tasks, dict):
        tasks = raw_tasks
    else:
        tasks = {}

    rows = [row for row in tasks.values() if isinstance(row, dict)]
    if not rows:
        return False
    consumers: set[str] = set()
    for row in rows:
        dump = row.get("task") if isinstance(row.get("task"), dict) else {}
        for item in dump.get("input_data") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "") != "task_artifact":
                continue
            src = str(item.get("source_task_id") or "").strip()
            if src:
                consumers.add(src)
    for task_id, row in tasks.items():
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if status in _OK_TASK_STATUSES:
            continue
        route = str(row.get("planned_route") or (row.get("task") or {}).get("route") or "")
        tid = str((row.get("task") or {}).get("id") or task_id)
        if route in _EVIDENCE_ROUTES and tid not in consumers:
            continue
        return False
    return True


_audit = functools.partial(audit, logger)


class FailClosedExperimentHITLHandler(AbstractHITLHandler):
    """Pause review when no interactive reviewer is connected."""

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        return HITLResponse(
            action=HITLAction.REJECT, approved=False, timed_out=True,
            instructions="No interactive reviewer is connected; experiment remains paused.",
        )


def fail_closed_handler() -> DelegatingHITLHandler:
    """Delegating handler so Web runtime can attach its UI handler."""
    return DelegatingHITLHandler(FailClosedExperimentHITLHandler())


def _headless_auto_approve() -> bool:
    return os.getenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE", "").strip().lower() in _AUTO_APPROVE_TRUTHY


def _auto_approve_response() -> HITLResponse:
    # Empty instructions: SessionAgent overwrites output_key when approved+instructions are both set.
    return HITLResponse(action=HITLAction.APPROVE, approved=True, instructions="")


def _context_invariant_errors(plan: ExperimentPlan, context: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if (rid := context.get("experiment_run_id")) and plan.experiment_run_id != rid:
        errors.append({
            "type": "context_invariant", "loc": ["experiment_run_id"], "input": plan.experiment_run_id,
            "msg": f"experiment_run_id must equal experiment_context.experiment_run_id ({rid!r})",
        })
    if (req := context.get("source_request")) and plan.source_request != req:
        errors.append({
            "type": "context_invariant", "loc": ["source_request"], "input": plan.source_request,
            "msg": "source_request must equal experiment_context.source_request",
        })
    return errors


def _json_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if not isinstance(value, str):
        return value
    from CoScientist.experiments.runtime.shared import parse_fenced_json

    return parse_fenced_json(value)


def _stamp_context_invariants(
    payload: Any, context: dict[str, Any], previous: ExperimentPlan | None = None,
) -> Any:
    """Authoritative context wins for run-id / source_request / plan identity.

    ``plan_id`` and ``revision`` are runtime bookkeeping, not planner output. The
    model has no reliable way to recall the previous plan_id across a revision
    round, and a wrong guess is a BLOCKING critique ("plan_id changed between
    revisions" / "A revised plan must increment revision") that costs one round
    of a budget only a few rounds deep. Observed 2026-09-04: a human HITL edit
    re-entered planning, the regenerated plan came back as
    ``PLAN-EXRUN-<uuid>`` where the runtime held ``PLAN-<uuid>``, and the whole
    experiment stopped without a single MCP call.

    The two validator checks stay where they are: stamping here makes them
    unreachable for model formatting while they still catch real programming
    errors, and it keeps the "validator repairs nothing" contract intact.
    """
    if not isinstance(payload, dict):
        return payload
    stamped = dict(payload)
    # Plan identity comes from the runtime, not from context, so it is stamped
    # even when experiment_context is empty - otherwise the two blocking checks
    # this defuses would quietly come back in exactly that corner.
    if previous is not None:
        stamped["plan_id"] = previous.plan_id
        stamped["revision"] = previous.revision + 1
    if not context:
        return stamped
    if run_id := context.get("experiment_run_id"):
        stamped["experiment_run_id"] = run_id
    if request := context.get("source_request"):
        stamped["source_request"] = request
    return stamped


def _esc(text: str, n: int | None = None) -> str:
    out = text.replace("|", "/")
    return out[:n] if n is not None else out


def _design_cell(value: Any, n: int | None = None) -> str:
    from CoScientist.experiments.schemas import is_design_placeholder
    if is_design_placeholder(value):
        return "—"
    return _esc(str(value).replace("\n", " "), n)


def render_experiment_plan(plan: ExperimentPlan) -> str:
    L = [
        f"# Experiment plan · revision {plan.revision}", f"Goal: {plan.goal}",
        f"Hypothesis summary: {plan.hypothesis or 'not specified'}",
        f"Methods: {', '.join(plan.methods)}", f"Total duration: {plan.total_est_duration_min} min",
    ]
    if plan.hypotheses:
        L += ["", "## Hypotheses"] + [f"- `{h.hypothesis_id}`: {h.statement}" for h in plan.hypotheses]
    L += [
        "", "## Design matrix (hypothesis → experiment → data → baseline → metrics)",
        "| Task | Hypothesis | Question | Dataset | Baselines | Metrics | Tools | Analysis artifacts | Route |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t in plan.tasks:
        d = t.design
        bl = "; ".join(f"{b.name} ({b.kind})" for b in d.baselines) if d.baselines else ""
        mt = "; ".join(f"{m.name}/{m.direction}" + (f" [{m.test}]" if m.test else "") for m in d.metrics) if d.metrics else ""
        ar = "; ".join(f"{a.name} ({a.role}/{a.prepare_via})" for a in d.analysis_artifacts) if d.analysis_artifacts else ""
        tools_summary = "; ".join(
            f"{s.name}:{','.join(x.name for x in s.tools)}" for s in t.mcp_servers
        ) if t.mcp_servers else ""
        L.append(
            f"| {t.id} | `{d.hypothesis_ref}` | {_design_cell(d.experiment_question, 120)} "
            f"| {_design_cell(d.dataset.name)} | {_design_cell(bl, 100)} "
            f"| {_design_cell(mt, 100)} | {_design_cell(tools_summary, 80)} "
            f"| {_design_cell(ar, 100)} | `{t.route.value}` |"
        )
    for t in plan.tasks:
        d = t.design
        tools = [
            f"{s.name} ({s.url}): {', '.join(x.name for x in s.tools)}"
            if s.url else f"{s.name}: {', '.join(x.name for x in s.tools)}"
            for s in t.mcp_servers
        ]
        criteria_parts = []
        for c in t.success_criteria:
            crit_text = f"{c.criterion_id}: {c.description}"
            if c.metric and c.operator is not None and c.target is not None:
                crit_text += f" [{c.metric} {c.operator} {c.target}]"
            criteria_parts.append(crit_text)
        criteria = "; ".join(criteria_parts)

        arts = "; ".join(
            f"{a.name} ({a.role})" if not a.description or a.description == a.name
            else f"{a.name} ({a.role}: {a.description})"
            for a in t.expected_artifacts
        )
        inputs_list = []
        for inp in t.input_data:
            loc = inp.url or inp.workspace_path or inp.s3_key or ""
            if loc:
                inputs_list.append(f"{inp.data_id} [{inp.kind}: {loc}]")
            else:
                inputs_list.append(f"{inp.data_id} [{inp.kind}]")
        inputs_str = "; ".join(inputs_list) if inputs_list else "none"

        also = f" (+{', '.join(d.also_tests)})" if d.also_tests else ""
        op_str = f" [Operation: `{d.operation_ref}`]" if d.operation_ref else ""
        notes = f" — {d.dataset.notes}" if d.dataset.notes else ""
        L += ["", f"## {t.id} · {t.name}", f"Route: `{t.route.value}`"]
        if t.route.value == "alembic_build":
            L += [f"Repo URL: {t.repo_url}", f"Post-build route: `{t.post_build_route}`"]
        L += [
            f"Hypothesis: `{d.hypothesis_ref}`{also}{op_str}",
            f"Question: {_design_cell(d.experiment_question)}",
            f"Dataset: {_design_cell(d.dataset.name)}{notes if d.dataset.name else ''}",
            f"Baselines: {_design_cell('; '.join(f'{b.name} ({b.kind})' for b in d.baselines))}",
            f"Metrics: {_design_cell('; '.join(f'{m.name} ({m.direction})' for m in d.metrics))}",
            f"Analysis artifacts: {_design_cell('; '.join(f'{a.name} [{a.role}]' for a in d.analysis_artifacts))}",
            f"Task: {t.description}",
        ]
        if t.rationale and t.rationale != t.description:
            L.append(f"Rationale: {t.rationale}")
        L.append(f"MCP/tools: {'; '.join(tools) if tools else 'none'}")
        if t.launch_params:
            params_str = ", ".join(f"{k}={v}" for k, v in t.launch_params.items())
            L.append(f"Launch params: {params_str}")
        L += [
            f"Inputs: {inputs_str}",
            f"Success criteria: {criteria}",
            f"Expected artifacts: {arts}",
            f"Duration: {t.est_duration_min} min",
            f"Warnings: {'; '.join(t.warnings) if t.warnings else 'none'}",
        ]
    if plan.risks:
        L += ["", "## Risks"] + [f"- {r}" for r in plan.risks]
    return "\n".join(L)


def _artifact_canonical_location(a: dict[str, Any]) -> str:
    """Prefer real http(s) URL, then s3://bucket/key, then workspace path."""
    url = str(a.get("external_url") or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    bucket, key = a.get("bucket"), a.get("s3_key")
    if bucket and key:
        return f"s3://{bucket}/{key}"
    if wp := a.get("workspace_path"):
        return str(wp)
    if url:
        return url
    return "(location missing)"


def build_experiment_artifacts_manifest(state: Any) -> list[dict[str, str]]:
    """Flat list of real ArtifactRef locations for prompts / reports."""
    rows: list[dict[str, str]] = []
    for r in state.get("experiment_task_results") or []:
        if not isinstance(r, dict):
            continue
        tid = str(r.get("task_id") or "")
        for a in r.get("artifacts") or []:
            if not isinstance(a, dict):
                continue
            rows.append({
                "task_id": tid,
                "artifact_id": str(a.get("artifact_id") or ""),
                "name": str(a.get("name") or ""),
                "location": _artifact_canonical_location(a),
                "media_type": str(a.get("media_type") or ""),
            })
    return rows


def render_experiment_results(state: Any) -> str:
    results = state.get("experiment_task_results") or []
    manifest = build_experiment_artifacts_manifest(state)
    if isinstance(state, dict):
        state["experiment_artifacts_manifest"] = manifest
    L = [
        "# Experiment results",
        f"Task results: {len(results)}",
        "",
        "## Canonical artifact locations (do not invent URLs)",
    ]
    if manifest:
        for m in manifest:
            L.append(
                f"- `{m['task_id']}` / `{m['name']}` (`{m['artifact_id']}`): `{m['location']}`"
            )
    else:
        L.append("- (none captured)")
    for r in results:
        L += [
            "",
            f"## {r.get('task_id')} · {r.get('status')}",
            str(r.get("summary") or ""),
            f"Route: `{r.get('route_used')}`",
        ]
        for a in r.get("artifacts") or []:
            if not isinstance(a, dict):
                continue
            L.append(
                f"- Artifact `{a.get('artifact_id')}` ({a.get('name')}): "
                f"`{_artifact_canonical_location(a)}`"
            )
    if summary := state.get("experiment_summary"):
        L += ["", "## Summary", str(summary)]
    return "\n".join(L)


# State this reviewer owns and must hand back to whoever invoked the module.
#
# The module runs as an ADK AgentTool, and AgentTool gives it a FRESH in-memory
# session seeded from a copy of the caller's state; the only thing that travels
# back is ``event.actions.state_delta`` (agent_tool.py: "Forward state delta to
# parent session"). This agent, like every SessionAgent, writes through
# ``ctx.session.state`` — a plain dict, not the ADK ``State`` wrapper — so its
# writes mutate the throwaway child session and are dropped when the tool
# returns. Callbacks are unaffected: ``callback_context.state`` IS a ``State``,
# so the planner context builder's writes DO travel back.
#
# That asymmetry is the re-planning loop. The builder's "new run" wipe
# (experiment_runtime = None) reached the caller; the approval that followed it
# — approve_plan, then mark_result_review's phase=completed — did not. The next
# module hop was therefore seeded with experiment_runtime=None, the completion
# gate had nothing to match on, and the whole experiment was planned and run
# again. Measured 2026-09-02: two full re-runs of the same three tasks in one
# 41-minute run, 19:50:46 phase=completed -> 19:50:59 gate sees NoneType.
_REVIEW_OWNED_STATE_KEYS = (
    "experiment_runtime",
    "experiment_plan",
    "experiment_plan_critique",
    "experiment_plan_validation_errors",
    "experiment_plan_review_paused",
    "experiment_plan_revision_count",
    "experiment_inventory_blocker_hits",
    "experiment_artifacts_manifest",
    "experiment_task_results",
    "experiment_summary",
    REPLAN_ROUNDS_KEY,
)


class ExperimentReviewSessionAgent(SessionAgent):
    """LLM plan/summary stage with deterministic validation and mandatory HITL."""

    review_kind: Literal["plan", "result"]
    max_inventory_blocker_hits: int = 2  # same inventory-absence blocker twice → pause

    def __init__(self, **data: Any):
        if data.get("hitl_handler") is None:
            data["hitl_handler"] = fail_closed_handler()
        super().__init__(**data)
        self._state_publish_pending = False

    def _should_run_review(self) -> bool:
        # Deterministic schema/critique + initialize_runtime live in
        # ``_review_plan``. They must run even when the global HITL switch is
        # off; headless auto-approve then skips the human console.
        return self.hitl_handler is not None

    def _review_output(self, output_text: Any) -> str:
        if self.review_kind != "plan":
            return str(output_text)
        try:
            return render_experiment_plan(ExperimentPlan.model_validate(_json_payload(output_text)))
        except Exception:
            return str(output_text)

    def _revise(
        self, *, ctx: InvocationContext, detail: Any, pause_prefix: str, edit_prefix: str,
        inventory_blocker: bool = False, **_kwargs: Any,
    ) -> HITLResponse:
        state = ctx.session.state
        try:
            revisions = int(state.get("experiment_plan_revision_count") or 0) + 1
        except (TypeError, ValueError):
            revisions = 1
        state["experiment_plan_revision_count"] = revisions

        try:
            hits = int(state.get("experiment_inventory_blocker_hits") or 0) + (1 if inventory_blocker else 0)
        except (TypeError, ValueError):
            hits = 1 if inventory_blocker else 0
        state["experiment_inventory_blocker_hits"] = hits

        max_rev = get_settings().experiments.max_plan_revisions
        if not (
            revisions >= max_rev
            or hits >= self.max_inventory_blocker_hits
        ):
            return HITLResponse(action=HITLAction.EDIT, approved=False, instructions=f"{edit_prefix} {detail}")
        state["experiment_plan_review_paused"] = True
        reason = (
            "inventory_blocker_repeated"
            if hits >= self.max_inventory_blocker_hits
            else "max_plan_revisions"
        )
        _audit(f"EXPERIMENT_PLAN_REVIEW_PAUSED reason={reason}")
        return HITLResponse(
            action=HITLAction.REJECT, approved=False, stop_review_loop=True,
            instructions=f"{pause_prefix} {detail}",
        )

    def _hitl(
        self, *, message: str, kind: str, plan_id: Any, output: str,
        user_id: str, session_id: str, timeout_seconds: float,
    ) -> HITLRequest:
        return HITLRequest(
            agent_name=self.name, action_type=HITLAction.APPROVE, message=message,
            context={
                "output": output, "experiment_review_kind": kind, "experiment_plan_id": plan_id,
                "_session": {"user_id": user_id, "session_id": session_id},
            },
            invoked_via="internal_loop", timeout_seconds=timeout_seconds,
        )

    def _publish_state(self, ctx: InvocationContext, event: Event) -> None:
        """Copy this reviewer's decisions into ``event``'s state delta.

        Only a delta on a yielded event survives the AgentTool boundary, so a
        decision that is not published here is invisible to the next module hop.
        Keys ADK already put on the event (the output_key it fills from the
        model turn) win — this fills in what nobody else reports.
        """
        state = ctx.session.state
        delta = event.actions.state_delta
        published = []
        for key in _REVIEW_OWNED_STATE_KEYS:
            if key in delta or key not in state:
                continue
            delta[key] = state[key]
            published.append(key)
        self._state_publish_pending = False
        if published:
            runtime = state.get("experiment_runtime")
            _audit(
                "EXPERIMENT_REVIEW_STATE_PUBLISHED kind=%s phase=%r keys=%d"
                % (
                    self.review_kind,
                    runtime.get("phase") if isinstance(runtime, dict) else None,
                    len(published),
                )
            )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if self.review_kind == "result":
            runtime = ctx.session.state.get("experiment_runtime") or {}
            if runtime.get("phase") not in {"reporting", "awaiting_result_review"}:
                _audit(f"EXPERIMENT_REVIEW_PAUSED kind=result phase={runtime.get('phase') or 'missing'}")
                yield Event(
                    invocation_id=ctx.invocation_id, author=self.name, branch=ctx.branch,
                    content=types.Content(role="model", parts=[types.Part(
                        text="Experiment result review is paused because execution has not reached reporting.",
                    )]),
                )
                return
        self._state_publish_pending = False
        async for event in super()._run_async_impl(ctx):
            if self._state_publish_pending:
                self._publish_state(ctx, event)
            yield event
        if self._state_publish_pending:
            # The base loop can decide without yielding anything (empty final
            # output, or a break on a paused review). Carry the delta out on an
            # event of our own rather than lose the decision.
            carrier = Event(
                invocation_id=ctx.invocation_id, author=self.name, branch=ctx.branch,
            )
            self._publish_state(ctx, carrier)
            yield carrier

    async def _review_plan(self, ctx: InvocationContext, output_text: Any) -> HITLResponse:
        state, cfg = ctx.session.state, get_settings().experiments
        user_id, session_id = session_key(ctx)
        try:
            context = state.get("experiment_context") or {}
            runtime = state.get("experiment_runtime") or {}
            previous = ExperimentPlan.model_validate(runtime["plan"]) if runtime.get("plan") else None
            payload = _stamp_context_invariants(_json_payload(output_text), context, previous)
            plan, critique = validate_and_critique_plan(
                payload, settings=cfg,
                available_tools=(
                    context.get("critique_mcp_capabilities")
                    or context.get("available_mcp_capabilities") or []
                ),
                preferred_tools=context.get("preferred_mcp_capabilities"), previous_plan=previous,
                hypothesis_refs=context.get("hypothesis_refs") or [],
                repo_candidates=context.get("repo_candidates") or [],
                operations=context.get("operations") or [],
                pipeline_scope=context.get("pipeline_scope"),
            )
            if errs := _context_invariant_errors(plan, context):
                raise PlanValidationError("ExperimentPlan context invariants failed", errors=errs)
        except (PlanValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors = getattr(exc, "errors", None) or [str(exc)]
            state["experiment_plan_validation_errors"] = errors
            _audit("EXPERIMENT_PLAN_REVISE reason=schema errors=" + json.dumps(errors, default=str, ensure_ascii=True))
            return self._revise(
                ctx=ctx, detail=errors,
                pause_prefix="Plan validation failed repeatedly; experiment remains paused. Last errors:",
                edit_prefix="Deterministic schema validation failed. Return a complete corrected ExperimentPlan JSON. Errors:",
            )

        critique_json = critique.model_dump(mode="json")
        state["experiment_plan_critique"] = critique_json
        if critique.verdict != "approve":
            issue_text = "; ".join(
                f"{i.severity}/{i.category}: {i.message} Suggestion: {i.suggestion}"
                for i in critique.issues if i.is_blocking
            )
            inv = any("absent from the capability inventory" in (i.message or "") for i in critique.issues)
            _audit("EXPERIMENT_PLAN_REVISE reason=critique issues=" + json.dumps(critique_json["issues"], ensure_ascii=True))
            return self._revise(
                ctx=ctx, detail=issue_text,
                pause_prefix="PlanCritique kept rejecting the plan; experiment remains paused. Last issues:",
                edit_prefix=(
                    "Deterministic PlanCritique requires revision. "
                    "Use ONLY tools from available_mcp_capabilities, or route=coder "
                    "(or alembic_build when a repo_candidate fits). Issues:"
                    if inv else "Deterministic PlanCritique requires revision:"
                ),
                inventory_blocker=inv,
            )

        state["experiment_plan_review_paused"] = False
        state["experiment_plan_validation_errors"] = None
        # The budget bounds CONSECUTIVE failures, not a whole session. Until this
        # reset it was only cleared in approve_plan, so a plan that validated but
        # was never approved left the count standing: a later human HITL edit then
        # re-entered planning with a partly spent budget and could exhaust it on
        # the first stumble.
        state["experiment_plan_revision_count"] = 0
        state["experiment_inventory_blocker_hits"] = 0
        initialize_runtime(state, plan, critique=critique_json)
        if _headless_auto_approve():
            approve_plan(state)
            _publish_approved_plan_to_graph(ctx, state)
            _audit(f"EXPERIMENT_REVIEW_APPROVED kind=plan mode=headless_auto plan_id={plan.plan_id} phase=execution")
            _audit("EXPERIMENT_DESIGN_MATRIX\n" + render_experiment_plan(plan))
            return _auto_approve_response()

        response = await self.hitl_handler.handle_request(self._hitl(
            message="Review and explicitly approve the experiment plan.", kind="plan",
            plan_id=plan.plan_id, output=render_experiment_plan(plan),
            user_id=user_id, session_id=session_id, timeout_seconds=cfg.plan_review_timeout_s,
        ))
        if response.approved:
            approve_plan(state)
            _publish_approved_plan_to_graph(ctx, state)
            _audit(f"EXPERIMENT_REVIEW_APPROVED kind=plan mode=human plan_id={plan.plan_id} phase=execution")
            _audit("EXPERIMENT_DESIGN_MATRIX\n" + render_experiment_plan(plan))
        return response

    async def _review_result(self, ctx: InvocationContext, _output_text: Any) -> HITLResponse:
        state, cfg = ctx.session.state, get_settings().experiments
        user_id, session_id = session_key(ctx)
        runtime = state.get("experiment_runtime") or {}
        runtime["phase"] = "awaiting_result_review"
        if runtime:
            # Same reason as in mark_result_review: ADK only records a state
            # delta on assignment, so mutating the nested dict leaves the phase
            # this reviewer just set invisible to everything downstream.
            state["experiment_runtime"] = runtime
        tasks_ok = result_tasks_ok(runtime)
        # Materialize canonical ArtifactRef locations before HITL / auto-approve.
        rendered = render_experiment_results(state)

        if _headless_auto_approve():
            result = mark_result_review(state, approved=True)
            _audit(
                f"EXPERIMENT_REVIEW_APPROVED kind=result mode=headless_auto "
                f"plan_id={runtime.get('plan_id')} phase={result['phase']} tasks_ok={str(tasks_ok).lower()}"
            )
            return _auto_approve_response()

        response = await self.hitl_handler.handle_request(self._hitl(
            message="Accept the experiment results, or reject with feedback to request a redesigned experiment.",
            kind="result", plan_id=runtime.get("plan_id"), output=rendered,
            user_id=user_id, session_id=session_id, timeout_seconds=cfg.result_review_timeout_s,
        ))
        if response.timed_out:
            return response
        if response.approved:
            result = mark_result_review(state, approved=True)
            _audit(
                f"EXPERIMENT_REVIEW_APPROVED kind=result mode=human "
                f"plan_id={runtime.get('plan_id')} phase={result['phase']} tasks_ok={str(tasks_ok).lower()}"
            )
            return response
        feedback = response.instructions or response.free_input or "Human requested experiment redesign."
        mark_result_review(state, approved=False, feedback=feedback)
        return response.model_copy(update={"stop_review_loop": True})

    async def _review_decision(self, ctx: InvocationContext, output_text: Any) -> HITLResponse:
        try:
            if self.review_kind == "plan":
                return await self._review_plan(ctx, output_text)
            return await self._review_result(ctx, output_text)
        finally:
            # Publish whatever the decision wrote, including on the raising and
            # pausing paths — a pause that does not reach the caller is a loop.
            self._state_publish_pending = True


__all__ = [
    "ExperimentReviewSessionAgent",
    "FailClosedExperimentHITLHandler",
    "build_experiment_artifacts_manifest",
    "fail_closed_handler",
    "render_experiment_plan",
    "render_experiment_results",
    "result_tasks_ok",
]
