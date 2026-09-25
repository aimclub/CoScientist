"""Deterministic plan validation and critique for Experiment Module v1b."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from uuid import uuid4

from pydantic import ValidationError

from CoScientist.config.settings import ExperimentsSettings
from CoScientist.experiments.capabilities.inventory import (
    FAMILY_MEDICAL,
    FAMILY_RESEARCH,
    declared_family_capabilities,
    index_inventory_tools,
    inventory_nonempty,
    inventory_pairs,
    match_named_family_capability,
    match_named_inventory_tool,
    schema_property_defaults,
    schema_property_enums,
)
from CoScientist.experiments.critique.coverage import task_coverage_blob as _task_coverage_blob
from CoScientist.experiments.schemas import (
    CritiqueIssue,
    ExecutionRoute,
    ExperimentPlan,
    PlanCritique,
    utc_now,
)

_MCP = {ExecutionRoute.FEDOT_MAS, ExecutionRoute.REACT_TOOLS}
_EVIDENCE_AGENTS = {ExecutionRoute.RESEARCH, ExecutionRoute.MEDICAL}
_ALT = re.compile(r"\b(otherwise|else|либо|иначе|alternativ)\b|/", re.I)


class PlanValidationError(ValueError):
    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


def _issue(
    n: int,
    *,
    category: str,
    severity: str,
    message: str,
    suggestion: str,
    task_id: str | None = None,
    code: str = "",
) -> CritiqueIssue:
    return CritiqueIssue(
        issue_id=f"DET-{n:03d}",
        code=code,
        category=category,
        severity=severity,
        task_id=task_id,
        message=message,
        suggestion=suggestion,
    )


def _tool_output_blob(task: Any) -> str:
    return " ".join(
        str(getattr(tool, a, "") or "")
        for s in getattr(task, "mcp_servers", None) or []
        for tool in getattr(s, "tools", None) or []
        for a in ("name", "description", "input_schema")
    ).lower()


def _is_image_artifact(a: Any) -> bool:
    return getattr(a, "role", "") == "plot" or str(getattr(a, "media_type", "") or "").startswith("image/")


def _normalize_hypothesis_ids(refs: Iterable[Any]) -> list[str]:
    out, seen = [], set()
    for item in refs or []:
        if isinstance(item, dict):
            hid = str(item.get("hypothesis_id") or item.get("id") or "").strip().upper()
        else:
            hid = str(item or "").strip().upper()
        if hid and hid not in seen:
            seen.add(hid)
            out.append(hid)
    return out


def _iter_inventory(tools: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    out, seen = [], set()
    for item in tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append((name, item))
    return out


def _planned_tools(plan: ExperimentPlan, *, mcp_only: bool = False) -> set[str]:
    names: set[str] = set()
    for task in plan.tasks:
        if not mcp_only or task.route in _MCP:
            for server in task.mcp_servers:
                for tool in server.tools:
                    names.add(tool.name)
        if task.route in _EVIDENCE_AGENTS and not mcp_only:
            for art in task.design.analysis_artifacts:
                if tool := str(art.path_or_tool or "").strip():
                    names.add(tool)
    return names


def _explicit_tool_requirement(request: str, tool: str) -> bool:
    e = re.escape(tool.lower())
    return any(re.search(p, request, re.I | re.DOTALL) for p in (
        rf"(?:use|call|run|invoke|via|through|with|использу[йя]|вызови|через)\s+[`'\"]?{e}",
        rf"[`'\"]?{e}[`'\"]?\s+(?:tool|mcp|server|инструмент)",
        rf"(?:tool|mcp)\s+[`'\"]?{e}",
        rf"(?:must|should|required|обязательн\w*)\s+.{0,40}{e}",
    ))


def _unused_matched_inventory_tools(plan: ExperimentPlan, *, available_tools: Iterable[dict[str, Any]]) -> list[str]:
    """Option A: unused inventory tools named in the ask → minor."""
    planned = _planned_tools(plan, mcp_only=True)
    request = str(plan.source_request or "")
    unused = []
    for tool, _item in _iter_inventory(available_tools):
        if tool in planned:
            continue
        if re.search(rf"(?<![\w-]){re.escape(tool.lower())}(?![\w-])", request.lower()):
            unused.append(tool)
    return sorted(unused)


def _named_inventory_tools_missing(plan: ExperimentPlan, *, available_tools: Iterable[dict[str, Any]]) -> list[str]:
    """Explicitly required inventory tools omitted from the plan."""
    request = plan.source_request.lower()
    planned = _planned_tools(plan)
    named = []
    for tool, _item in _iter_inventory(available_tools):
        if re.search(rf"(?<![\w-]){re.escape(tool.lower())}(?![\w-])", request) and _explicit_tool_requirement(request, tool):
            named.append(tool)
    if not named:
        return []
    missing = [t for t in named if t not in planned]
    if not missing:
        return []
    if any(t in planned for t in named) and _ALT.search(request):
        return []
    return sorted(missing)


_PLACEHOLDER_HOST_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?(?:example\.(?:com|org|net)|localhost|127\.0\.0\.1)\b"
)
_FAKE_S3_RE = re.compile(r"(?i)\bs3://artifacts(?:/|\b)")
_PLACEHOLDER_TOKEN_RE = re.compile(
    r"(?i)\b(?:placeholder[_-]?url|dummy[_-]?url|fake[_-]?dataset|"
    r"your[_-]bucket|insert[_-]url[_-]here)\b"
)


def _iter_plan_url_strings(plan: ExperimentPlan) -> list[tuple[str, str]]:
    """Collect (task_id_or_plan, text) candidates that may contain fake URLs."""
    out: list[tuple[str, str]] = []
    for blob in (plan.goal, plan.hypothesis or "", *(plan.assumptions or []), *(plan.risks or [])):
        if str(blob).strip():
            out.append(("plan", str(blob)))
    for task in plan.tasks:
        tid = task.id
        for blob in (task.description, task.repo_url or "", *(task.warnings or [])):
            if str(blob).strip():
                out.append((tid, str(blob)))
        d = task.design
        for blob in (d.experiment_question, d.dataset.name, d.dataset.notes or ""):
            if str(blob).strip():
                out.append((tid, str(blob)))
        if d.dataset.ref is not None:
            ref = d.dataset.ref
            for blob in (
                getattr(ref, "url", None),
                getattr(ref, "workspace_path", None),
                getattr(ref, "prepare_instruction", None),
                getattr(ref, "description", None),
            ):
                if blob and str(blob).strip():
                    out.append((tid, str(blob)))
        for ref in task.input_data:
            for blob in (
                ref.url, ref.workspace_path, ref.prepare_instruction, ref.description,
                f"s3://{ref.bucket}/{ref.s3_key}" if ref.bucket and ref.s3_key else "",
            ):
                if blob and str(blob).strip():
                    out.append((tid, str(blob)))
        lp = task.launch_params
        if lp is None:
            continue
        if isinstance(lp, str):
            out.append((tid, lp))
        else:
            try:
                out.append((tid, json.dumps(lp, ensure_ascii=False)))
            except Exception:
                out.append((tid, str(lp)))
    return out


def _placeholder_url_hits(text: str) -> list[str]:
    hits: list[str] = []
    if _PLACEHOLDER_HOST_RE.search(text):
        hits.append("example/localhost host")
    if _FAKE_S3_RE.search(text):
        hits.append("s3://artifacts placeholder")
    if _PLACEHOLDER_TOKEN_RE.search(text):
        hits.append("placeholder dataset/url token")
    return hits


def _number_in_text(value: int | float, text: str) -> bool:
    """True when this number appears as its own token in text (3 does not match 30)."""
    forms = {str(value)}
    if isinstance(value, float) and value.is_integer():
        forms.add(str(int(value)))
    if isinstance(value, int):
        forms.add(str(value))
    for form in forms:
        if re.search(rf"(?<![\d.]){re.escape(form)}(?![\d.])", text):
            return True
    return False


def _same_number(value: Any, default: Any) -> bool:
    if isinstance(value, bool) or isinstance(default, bool):
        return False
    if not isinstance(value, (int, float)) or not isinstance(default, (int, float)):
        return False
    return float(value) == float(default)


def _param_is_grounded(value: Any, source_request: str, default: Any) -> bool:
    """A launch param may repeat the request, a schema literal is checked separately, or a schema default."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return _same_number(value, default) or _number_in_text(value, source_request)
    if isinstance(value, str):
        text = value.strip()
        return not text or text in source_request
    if isinstance(value, list):
        return all(_param_is_grounded(item, source_request, None) for item in value)
    return False


def critique_plan(
    plan: ExperimentPlan,
    *,
    settings: ExperimentsSettings,
    available_tools: Iterable[dict[str, Any]] = (),
    preferred_tools: Iterable[dict[str, Any]] | None = None,
    previous_plan: ExperimentPlan | None = None,
    hypothesis_refs: Iterable[Any] = (),
    repo_candidates: Iterable[Any] = (),
    operations: Iterable[Any] = (),
    pipeline_scope: dict[str, Any] | None = None,
) -> PlanCritique:
    """Routes, registry refs, scientific design, revision invariants."""
    from CoScientist.context_init.operations import normalize_operation_rows

    issues: list[CritiqueIssue] = []
    ops = normalize_operation_rows(list(operations or []))
    ops_index = {
        str(op["operation_id"]).strip().upper(): op for op in ops if op.get("operation_id")
    }

    def add(**kw: Any) -> None:
        issues.append(_issue(len(issues) + 1, **kw))

    def fe(tid: str, sev: str, msg: str, sug: str, code: str = "") -> None:
        add(category="feasibility", severity=sev, task_id=tid, message=msg, suggestion=sug, code=code)

    def co(sev: str, msg: str, sug: str, tid: str | None = None, code: str = "") -> None:
        add(category="completeness", severity=sev, task_id=tid, message=msg, suggestion=sug, code=code)

    for scope, text in _iter_plan_url_strings(plan):
        if hits := _placeholder_url_hits(text):
            tid = None if scope == "plan" else scope
            fe(
                tid or "plan",
                "blocker",
                f"{scope}: fabricated/placeholder URL or data locator ({', '.join(hits)}).",
                "Use a real inventory/tool-backed dataset, an upstream task_artifact, "
                "or omit the URL — never example.com / s3://artifacts / dummy hosts.",
            )

    def _norm_repo_url(url: Any) -> str:
        return str(url or "").strip().rstrip("/").removesuffix(".git").lower()

    cand_list = [
        i for i in (repo_candidates or [])
        if isinstance(i, dict) and str(i.get("url") or "").strip()
    ]
    cand = {_norm_repo_url(i.get("url")) for i in cand_list}
    n = len(plan.tasks)
    if n > settings.max_plan_tasks:
        add(category="complexity", severity="blocker",
            message=f"Plan has {n} tasks; max is {settings.max_plan_tasks}.",
            suggestion="Merge tasks without losing dependencies or deliverables.")
    if n >= settings.complexity_warning_tasks:
        add(category="complexity", severity="minor",
            message=f"Plan has {n} tasks and may be expensive for v0.",
            suggestion="Confirm each task is an unavoidable execution unit.")

    research_forbidden = (
        isinstance(pipeline_scope, dict) and pipeline_scope.get("research") is False
    )
    enabled = {
        ExecutionRoute.REACT_TOOLS,
        ExecutionRoute.CODER,
        ExecutionRoute.RESEARCH,
        ExecutionRoute.MEDICAL,
        ExecutionRoute.DATASET_COLLECTOR,
    }
    if settings.route_fedot:
        enabled.add(ExecutionRoute.FEDOT_MAS)
    if settings.route_alembic:
        enabled.add(ExecutionRoute.ALEMBIC_BUILD)

    inv_list = list(available_tools)
    inventory = inventory_pairs(inv_list)
    by_tool_caps = index_inventory_tools(inv_list)
    completeness = list(preferred_tools) if preferred_tools is not None else list(available_tools)

    if settings.require_task_design:
        for task in plan.tasks:
            d, tid = task.design, task.id
            for field, sug in (
                ("baselines", "Optional: name a real comparator if one exists."),
                ("metrics", "Optional: name a metric only when a threshold is known."),
                ("analysis_artifacts", "Optional: list files this task will actually produce."),
            ):
                if not getattr(d, field):
                    co("minor", f"{tid} design.{field} is empty.", sug, tid)
            if not d.dataset.name.strip():
                co("minor", f"{tid} design.dataset.name is missing.",
                   "Name the dataset/benchmark if one is already known.", tid)
            for field, sug in (
                ("baselines", "Replace placeholder with a concrete baseline."),
                ("metrics", "Replace placeholder with a concrete metric and direction."),
            ):
                if any(x.name.strip().lower().startswith("unspecified") for x in getattr(d, field)):
                    co("minor", f"{tid} design.{field} still has an unspecified placeholder.", sug, tid)

        ctx = _normalize_hypothesis_ids(hypothesis_refs)
        plan_h = _normalize_hypothesis_ids([{"hypothesis_id": h.hypothesis_id} for h in plan.hypotheses])
        req, any_c = set(), set()
        for task in plan.tasks:
            ids = task.design.covered_hypothesis_ids()
            any_c |= ids
            if not task.optional:
                req |= ids
        untestable: list[str] = []
        if ctx:
            if miss := [h for h in ctx if h not in req]:
                testable = []
                if ops:
                    for hid in miss:
                        has_op = any(
                            hid.lower() in str(op.get("statement") or "").lower()
                            or hid.lower() in str(op.get("hypothesis_ref") or "").lower()
                            for op in ops
                        )
                        if has_op:
                            testable.append(hid)
                        else:
                            untestable.append(hid)
                else:
                    testable = list(miss)
                if testable:
                    co("major", f"Context hypothesis_refs uncovered by non-optional task design: {', '.join(testable)}.",
                       "Link each leftover id on an existing required task via "
                       "design.hypothesis_ref or also_tests.")
                if untestable:
                    co("minor", f"hypothesis_not_testable_at_this_stage: Context hypothesis_refs uncovered: {', '.join(untestable)}.",
                       "Uncovered hypotheses with no direct method at this stage will be marked postponed.")
            if plan_h and (mp := [h for h in ctx if h not in plan_h]):
                add(category="consistency", severity="major",
                    message=f"plan.hypotheses omits context hypothesis ids: {', '.join(mp)}.",
                    suggestion="Copy every context hypothesis_ref into plan.hypotheses.")
            if plan_h and (extra := [h for h in plan_h if h not in ctx]):
                co("major", f"plan.hypotheses invents ids absent from hypothesis_refs: {', '.join(extra)}.",
                   "Copy only hypothesis_refs; do not invent additional hypothesis ids.")
        elif not plan.hypotheses:
            co("major", "No hypothesis_refs in context and plan.hypotheses is empty.",
               "HypothesesAgent should populate hypothesis_refs; copy them "
               "into plan.hypotheses (or one H1 from source_request) and link tasks.")
        untestable_set = set(untestable)
        if plan_h and (orphan := [h for h in plan_h if h not in any_c and h not in untestable_set]):
            co("major", f"plan.hypotheses ids not linked from tasks: {', '.join(orphan)}.",
               "Each plan hypothesis must appear as design.hypothesis_ref (or also_tests) on ≥1 task.")

        if ops:
            ops_ids = [str(op["operation_id"]).strip().upper() for op in ops]
            ops_set = set(ops_ids)
            covered: list[str] = []
            missing_ref: list[str] = []
            for task in plan.tasks:
                if task.optional:
                    continue
                ref = str(task.design.operation_ref or "").strip().upper()
                if ref:
                    covered.append(ref)
                else:
                    missing_ref.append(task.id)
            covered_set = set(covered)
            if miss_ops := [oid for oid in ops_ids if oid not in covered_set]:
                co("major",
                   f"Frame operations uncovered by non-optional tasks: {', '.join(miss_ops)}.",
                   "Add a required task per uncovered OP-n and set design.operation_ref. "
                   "Leftover MCP without a named tool on that slot is required coder, not coverage.")
            if missing_ref:
                sev = "major" if miss_ops else "minor"
                co(sev,
                   f"Non-optional tasks missing design.operation_ref: {', '.join(missing_ref)}.",
                   "Set design.operation_ref to a frame operation_id (OP-n).")
            if extra_ops := [ref for ref in covered_set if ref not in ops_set]:
                sev = "major" if miss_ops else "minor"
                co(sev,
                   f"Tasks reference operation ids absent from the frame: {', '.join(sorted(extra_ops))}.",
                   "Copy operation_id from experiment_context.operations; do not invent OP-n.")
            dupes = sorted({ref for ref in covered if covered.count(ref) > 1})
            if dupes:
                co("minor",
                   f"Multiple non-optional tasks share the same operation_ref: {', '.join(dupes)}.",
                   "Multiple pipeline steps covering the same frame operation is supported.")

    for task in plan.tasks:
        tid = task.id
        if task.route == ExecutionRoute.ALEMBIC_BUILD:
            if not settings.route_alembic:
                fe(tid, "blocker", "Route 'alembic_build' is disabled by profile settings.",
                   "Use a ready MCP route or coder, or enable EXPERIMENTS__ROUTE_ALEMBIC.")
            elif not task.repo_url:
                fe(tid, "blocker", f"{tid} uses alembic_build but repo_url is missing.",
                   "Set repo_url to an exact URL from experiment_context.repo_candidates.")
            elif not cand:
                fe(tid, "blocker",
                   f"{tid} uses alembic_build but experiment_context.repo_candidates is empty "
                   "(no extracted git URL to build).",
                   "Only schedule alembic_build when a repo candidate from the ask fits.")
            elif _norm_repo_url(task.repo_url) not in cand:
                fe(tid, "blocker",
                   f"{tid} alembic repo_url {task.repo_url!r} is not in experiment_context.repo_candidates.",
                   "Copy repo_url from a listed candidate, or drop alembic_build.")
            elif not task.post_build_route:
                fe(tid, "blocker", f"{tid} uses alembic_build but post_build_route is missing.",
                   "Set post_build_route to fedot_mas or react_tools after MCP build.")
            if task.mcp_servers:
                fe(tid, "blocker", f"{tid} alembic_build must keep mcp_servers empty at plan time.",
                   "Set mcp_servers to [] — runtime injects the built MCP URL after Alembic.")
        elif task.route not in enabled:
            fe(tid, "blocker", f"Route {task.route.value!r} is disabled by profile settings.",
               "Choose an enabled route.")

        if research_forbidden and task.route == ExecutionRoute.RESEARCH:
            fe(
                tid, "blocker",
                f"{tid} uses route=research but the human-fixed pipeline_scope "
                "has research=false.",
                "Cover this step with fedot_mas/react_tools/coder; do not call ResearchAgent.",
            )
        if research_forbidden:
            for art in task.design.analysis_artifacts:
                if str(getattr(art, "prepare_via", "") or "") == "research":
                    fe(
                        tid, "blocker",
                        f"{tid} sets prepare_via=research but pipeline_scope.research is false.",
                        "Use prepare_via=mcp or prepare_via=coder.",
                    )

        if task.route in _MCP and not inventory:
            fe(tid, "blocker",
               f"{tid} uses {task.route.value} but the MCP capability inventory is empty.",
               "Use route=coder when no exact ready MCP covers the task.")

        if task.route in _EVIDENCE_AGENTS and not (
            research_forbidden and task.route == ExecutionRoute.RESEARCH
        ):
            if task.mcp_servers:
                fe(tid, "blocker",
                   f"{tid} uses {task.route.value} but lists mcp_servers; "
                   "that route agent's toolset is not registry MCP.",
                   "Set mcp_servers to [] and bind the family tool via "
                   "design.analysis_artifacts.path_or_tool.")
            if not any(art.required for art in task.expected_artifacts):
                fe(tid, "major",
                   f"{tid} uses {task.route.value} without a required evidence artifact.",
                   "Require a notes/citations/report artifact (role=report or data).")
            family_tools = {
                row["tool"]
                for row in declared_family_capabilities(
                    FAMILY_RESEARCH if task.route == ExecutionRoute.RESEARCH else FAMILY_MEDICAL
                )
            }
            bound = {
                str(art.path_or_tool or "").strip()
                for art in task.design.analysis_artifacts
            }
            if not (bound & family_tools):
                fe(tid, "major",
                   f"{tid} uses {task.route.value} without binding a family tool "
                   f"({', '.join(sorted(family_tools)[:4])}, …).",
                   "Set design.analysis_artifacts.path_or_tool to an exact "
                   "available_research_capabilities / available_medical_capabilities name.")

        if task.route == ExecutionRoute.DATASET_COLLECTOR:
            if task.mcp_servers:
                fe(
                    tid, "blocker",
                    f"{tid} uses dataset_collector but lists mcp_servers; "
                    "DatasetCollectorAgent uses internal sandbox tools and APIs.",
                    "Set mcp_servers to [].",
                )
            if not any(art.required for art in task.expected_artifacts):
                fe(
                    tid, "major",
                    f"{tid} uses dataset_collector without a required data artifact.",
                    "Require at least one dataset artifact (role=data, e.g. dataset.csv).",
                )

        if task.route == ExecutionRoute.CODER and task.mcp_servers and not settings.route_coder_mcp:
            fe(tid, "major", "Direct MCP-to-Coder mode is disabled.",
               "Remove MCP refs from the coder task or enable EXPERIMENTS__ROUTE_CODER_MCP.",
               code="direct_mcp_coder_disabled")

        if task.route == ExecutionRoute.CODER and not task.optional:
            blob = _task_coverage_blob(task, ops_index)
            if match_named_family_capability(blob) and not research_forbidden:
                fe(
                    tid, "major",
                    f"{tid} uses route=coder, but THIS task names a research/medical "
                    "family tool — Coder must not reimplement that family.",
                    "Set route=research or route=medical and bind the family tool on "
                    "design.analysis_artifacts.path_or_tool.",
                    code="coder_reimplements_family",
                )
            elif by_tool_caps and match_named_inventory_tool(blob, by_tool_caps):
                co(
                    "minor",
                    f"{tid} uses route=coder, and mentions a retrieved inventory tool.",
                    "Consider binding that inventory tool on fedot_mas/react_tools if custom code is not required.",
                    tid,
                    code="coder_reimplements_inventory",
                )

        if task.route == ExecutionRoute.CODER and settings.route_alembic and cand_list and not inventory_nonempty(by_tool_caps):
            top = cand_list[0].get("url")
            co("minor",
               f"{tid} uses route=coder, but experiment_context.repo_candidates has a "
               f"fitting repository ({top}) and route_alembic is enabled — route=alembic_build "
               "may be a better fit than reimplementing via coder.",
               f"Consider route=alembic_build with repo_url={top!r} and "
               "post_build_route=fedot_mas (or react_tools) instead of reimplementing via coder.",
               tid,
               code="coder_prefer_alembic")

        for server in task.mcp_servers:
            if server.source == "registry":
                for tool in server.tools:
                    if (str(server.server_id), tool.name) not in inventory:
                        fe(tid, "blocker",
                           f"Registry tool {tool.name!r} on server {server.server_id!r} "
                           "is absent from the capability inventory.",
                           "Use an exact retrieved tool/server pair, or switch to coder.",
                           code="inventory_tool_absent")
                    elif tool.name in by_tool_caps and task.launch_params:
                        t_item = by_tool_caps[tool.name]
                        schema = t_item.get("input_schema")
                        t_enums = schema_property_enums(schema)
                        defaults = schema_property_defaults(schema)
                        params = task.launch_params
                        if isinstance(params, str):
                            try:
                                params = json.loads(params)
                            except (TypeError, ValueError):
                                params = None
                        if isinstance(params, dict):
                            source = plan.source_request or ""
                            for p_name, val in params.items():
                                allowed = t_enums.get(p_name)
                                if allowed and isinstance(val, str) and val.strip():
                                    if not any(val.strip().lower() == lit.lower() for lit in allowed):
                                        fe(
                                            tid, "major",
                                            f"Task {tid} parameter {p_name}={val!r} is not in allowed choices for tool {tool.name!r}: {sorted(allowed)}.",
                                            f"Use one of {sorted(allowed)} or omit {p_name}.",
                                            code="invalid_tool_param_enum",
                                        )
                                    continue
                                if _param_is_grounded(val, source, defaults.get(p_name)):
                                    continue
                                fe(
                                    tid, "major",
                                    f"Task {tid} parameter {p_name}={val!r} is not in the request or the tool schema.",
                                    "Omit it. Copy a value that already appears in source_request, "
                                    "use a schema enum/const or schema default, or bind the input "
                                    "from an upstream task_artifact via depends_on and input_data.",
                                    code="invented_launch_param",
                                )

        if task.route in _MCP and "image/" not in _tool_output_blob(task):
            for art in task.expected_artifacts:
                if art.required and _is_image_artifact(art):
                    fe(tid, "minor",
                       f"Required artifact {art.name!r} is an image/plot "
                       "(role=plot or image/* media_type), but selected MCP tools do not "
                       "document image/* outputs.",
                       "Prefer required=false for viz extras; keep a required role=data artifact.",
                       code="mcp_missing_image_output")

        if getattr(settings, "evidence_strict", True) and task.route in (_MCP | {ExecutionRoute.CODER}) and not task.optional:
            req_crits = [c for c in task.success_criteria if c.required]
            if req_crits and all(str(c.kind) in ("artifact_exists", "execution") for c in req_crits):
                fe(
                    tid, "major",
                    f"Compute task {tid} has only execution/artifact_exists criteria; at least one threshold criterion is required.",
                    "Add a success_criteria item with kind='threshold', metric, operator, and target.",
                    code="only_execution_criteria",
                )
            if task.design.metrics:
                crit_metrics = {str(c.metric or "").strip().lower() for c in task.success_criteria if c.metric}
                design_metric_names = {str(m.name or "").strip().lower() for m in task.design.metrics if m.name}
                if not (crit_metrics & design_metric_names):
                    fe(
                        tid, "major",
                        f"Task {tid} declares design.metrics ({', '.join(sorted(design_metric_names))}), but no success_criteria references them.",
                        "Add a threshold criterion referencing one of the design.metrics.",
                        code="metrics_not_in_criteria",
                    )

        bound_tool_names = [tool.name for server in task.mcp_servers for tool in server.tools if tool.name]
        if len(bound_tool_names) > 1 and not task.optional:
            exp_art_names = " ".join(
                str(a.name or "") + " " + str(a.description or "") for a in task.expected_artifacts
            ).lower()
            missing_tool_arts = [t for t in bound_tool_names if t.lower() not in exp_art_names]
            if missing_tool_arts:
                fe(
                    tid, "major",
                    f"Composite task {tid} binds multiple tools ({', '.join(bound_tool_names)}), but lacks expected_artifacts for: {', '.join(missing_tool_arts)}.",
                    "Add an expected_artifact for each bound tool in the composite step.",
                )

    has_mcp = any(t.route in _MCP for t in plan.tasks)
    has_evidence = any(t.route in _EVIDENCE_AGENTS for t in plan.tasks)
    named_compute = False
    if by_tool_caps:
        if ops:
            named_compute = any(
                match_named_inventory_tool(str(op.get("statement") or ""), by_tool_caps)
                for op in ops
            )
        else:
            named_compute = match_named_inventory_tool(plan.source_request, by_tool_caps) is not None
    if named_compute and has_evidence and not has_mcp:
        add(category="feasibility", severity="major",
            message="A frame operation names a retrieved compute tool but the plan has no "
                    "fedot_mas/react_tools task — research/medical cannot replace that named tool.",
            suggestion="Add ≥1 fedot_mas (or react_tools) task bound to the named inventory tool.")

    if miss := _named_inventory_tools_missing(plan, available_tools=completeness):
        co("major",
           f"source_request explicitly requires inventory tools absent from the plan: {', '.join(miss)}.",
           "Add tasks for each explicitly required tool, or drop those requirements.")

    # Option A: unused thematic inventory is advisory (minor).
    if unused := _unused_matched_inventory_tools(plan, available_tools=completeness):
        co("minor",
           "Request mentions capabilities that ready inventory tools cover, "
           f"but no MCP-route task uses them: {', '.join(unused)} "
           "(non-blocking; inventory is availability, not a checklist).",
           "Optional: bind matching inventory tools on fedot_mas/react_tools when required.")

    if previous_plan is not None:
        if plan.plan_id != previous_plan.plan_id:
            add(category="consistency", severity="blocker", message="plan_id changed between revisions.",
                suggestion="Keep the original plan_id and increment revision.")
        if plan.revision <= previous_plan.revision:
            add(category="consistency", severity="blocker", message="A revised plan must increment revision.",
                suggestion=f"Use revision >= {previous_plan.revision + 1}.")
        if removed := sorted({t.id for t in previous_plan.tasks} - {t.id for t in plan.tasks}):
            add(category="consistency", severity="minor",
                message=f"Revised plan dropped task ids: {', '.join(removed)}.",
                suggestion="Keep stable task ids when possible; mark obsolete work optional instead of deleting.")

    return PlanCritique(
        schema_version="plan-critique/0.1",
        critique_id=f"CRIT-{uuid4().hex}",
        plan_id=plan.plan_id,
        plan_revision=plan.revision,
        critic_type="deterministic",
        verdict="revise" if any(i.is_blocking for i in issues) else "approve",
        issues=issues,
        checked_at=utc_now(),
    )


def validate_and_critique_plan(
    payload: Any,
    *,
    settings: ExperimentsSettings,
    available_tools: Iterable[dict[str, Any]] = (),
    preferred_tools: Iterable[dict[str, Any]] | None = None,
    previous_plan: ExperimentPlan | None = None,
    hypothesis_refs: Iterable[Any] = (),
    repo_candidates: Iterable[Any] = (),
    operations: Iterable[Any] = (),
    pipeline_scope: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> tuple[ExperimentPlan, PlanCritique]:
    """Strict schema validation, then deterministic policy checks."""
    inventory = list(available_tools)
    repo_list = list(repo_candidates)
    try:
        plan = ExperimentPlan.model_validate(payload)
    except ValidationError as exc:
        raise PlanValidationError(
            "ExperimentPlan schema validation failed", errors=exc.errors(include_url=False)
        ) from exc
    return plan, critique_plan(
        plan, settings=settings, available_tools=inventory,
        preferred_tools=None if preferred_tools is None else list(preferred_tools),
        previous_plan=previous_plan, hypothesis_refs=hypothesis_refs, repo_candidates=repo_list,
        operations=operations,
        pipeline_scope=pipeline_scope,
    )


__all__ = ["PlanValidationError", "critique_plan", "validate_and_critique_plan"]
