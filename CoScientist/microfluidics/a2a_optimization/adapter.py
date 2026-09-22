"""One external A2A task owns optimization, CFD and equipment execution.

Local tools validate the hand-off, retain raw task responses, and resume the
same task. They never interpret a remote plan as local equipment commands.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from typing import Any

from google.adk.tools import ToolContext

from .a2a_test_client import A2AClient, A2ARequestError
from .contracts import INPUT_KEYS, EconomicsRankingError, prepare_inputs
from .operator_ranking import DECLINED, RANKING_KEY, request_operator_ranking

ACTIVE_KEY = "optimization_a2a_task"
HISTORY_KEY = "optimization_a2a_runs"
RESULT_KEY = "optimization_result"
TERMINAL = {"completed", "failed", "rejected", "canceled"}


def _client() -> A2AClient:
    url = os.getenv("OPTIMIZATION_A2A_URL") or os.getenv(
        "A2A_ROUTER_PUBLIC_URL", "https://ailab.se.ifmo.ru/"
    )
    return A2AClient(url, timeout=30.0)


def _save(context: ToolContext, record: dict) -> dict:
    context.state[ACTIVE_KEY] = record
    history = dict(context.state.get(HISTORY_KEY) or {})
    history[record["experiment_id"]] = record
    context.state[HISTORY_KEY] = history
    # Separate service data from the LLM's narrative. Preserve every response,
    # including earlier plan/artifact snapshots and partial results on failure.
    context.state[RESULT_KEY] = {
        key: record.get(key) for key in (
            "experiment_id", "task_id", "state", "phase", "planning_only",
            "task", "responses", "error", "error_response",
        )
    }
    return record


def _parts(message: Any) -> list:
    if not isinstance(message, dict) or not isinstance(message.get("parts", []), list):
        raise ValueError("Malformed A2A message")
    parts = message.get("parts", [])
    if any(not isinstance(part, dict) for part in parts):
        raise ValueError("Malformed A2A message part")
    return parts


def _receive(context: ToolContext, record: dict, response: dict) -> dict:
    try:
        if not isinstance(response, dict) or response.get("error"):
            raise ValueError("A2A error or invalid response")
        result = response.get("result")
        if not isinstance(result, dict):
            raise ValueError("A2A response contains no result object")
        task = result.get("task", result)
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
            raise ValueError("A2A response contains no task id")
        if record.get("task_id") and task["id"] != record["task_id"]:
            raise ValueError("A2A returned a different task id")
        if task.get("contextId") and task["contextId"] != record["context_id"]:
            raise ValueError("A2A returned a different context id")
        status = task.get("status")
        if not isinstance(status, dict) or not isinstance(status.get("state"), str):
            raise ValueError("A2A task contains no status state")
        state = status["state"].removeprefix("TASK_STATE_").lower().replace("-", "_")
        if state == "cancelled":
            state = "canceled"
        if state not in TERMINAL | {"submitted", "working", "input_required", "auth_required"}:
            raise ValueError(f"Unknown A2A task state: {state}")
        parts = _parts(status.get("message") or {})
        phase = next((str(p["data"]["phase"]) for p in parts
                      if isinstance(p.get("data"), dict) and p["data"].get("phase")), "")
        artifacts = task.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError("Malformed A2A artifacts")
        for artifact in artifacts:
            _parts(artifact)
        messages = task.get("history", [])
        if not isinstance(messages, list):
            raise ValueError("Malformed A2A task history")
        for message in messages:
            _parts(message)
    except ValueError as exc:
        raise A2ARequestError(str(exc), response if isinstance(response, dict) else None) from exc
    return _save(context, {
        **record, "task_id": task["id"], "state": state, "phase": phase,
        "task": task, "response": response,
        "responses": [*record.get("responses", []), response],
        "error": None, "error_response": None,
    })


def _failure(context, record, state, exc):
    return _save(context, {
        **record, "state": state, "error": str(exc),
        "error_response": getattr(exc, "response", None),
    })


def _operator_reachable(tool_context: ToolContext) -> bool:
    """HITL is on and this is a real ADK context a human can answer on.

    Bare unit/CLI contexts have no invocation/session channel on which a
    human could answer; real ADK ToolContext objects do.
    """
    from CoScientist.config import get_settings

    interactive_context = bool(
        getattr(tool_context, "_invocation_context", None)
        or getattr(tool_context, "invocation_context", None)
        or getattr(tool_context, "session", None)
    )
    return bool(get_settings().web.hitl_enabled and interactive_context)


async def _inputs_with_operator_ranking(
    tool_context: ToolContext, exc: EconomicsRankingError,
) -> tuple[dict | None, dict]:
    """Close a missing/unusable economics_ranking with the operator's costs.

    Returns ``(inputs, {})`` once the operator's ranking is stored and the
    hand-off validates, else ``(None, invalid_input result)``. The result is
    flagged ``economics_ranking_required`` so the session does not loop on a
    gap only new data can close.
    """
    failure = {"state": "invalid_input", "error": str(exc), "economics_ranking_required": True}
    if not _operator_reachable(tool_context):
        return None, {**failure, "operator_available": False}
    ranking, reason = await request_operator_ranking(tool_context, exc.route_ids, str(exc))
    if ranking is None:
        return None, {
            **failure, "operator_available": True,
            "operator_declined": reason == DECLINED,
            **({} if reason == DECLINED else {"operator_error": reason}),
        }
    tool_context.state[RANKING_KEY] = ranking
    try:
        return prepare_inputs(tool_context.state), {}
    except (ValueError, TypeError) as retry_exc:
        return None, {**failure, "error": str(retry_exc), "operator_available": True}


async def optimization_start(tool_context: ToolContext, planning_only: bool = False) -> dict[str, Any]:
    """Delegate the complete experiment/optimization workflow to one A2A task.

    planning_only is for explicitly requested planning and smoke tests. Repeated
    calls reuse the same task, including completed tasks; never rerun hardware
    automatically. A different investigation requires a new CoScientist session.
    """
    previous = tool_context.state.get(ACTIVE_KEY)
    if previous:
        return previous
    try:
        inputs = prepare_inputs(tool_context.state, planning_only=planning_only)
    except EconomicsRankingError as exc:
        # Only the cost ranking is missing: the operator can supply it here,
        # in the tool, instead of the model improvising a ranking it cannot store.
        inputs, result = await _inputs_with_operator_ranking(tool_context, exc)
        if inputs is None:
            tool_context.state[RESULT_KEY] = result
            return result
    except (ValueError, TypeError) as exc:
        result = {"state": "invalid_input", "error": str(exc)}
        tool_context.state[RESULT_KEY] = result
        return result
    suffix = uuid.uuid4().hex
    record = {
        "experiment_id": f"optimization-{suffix}", "context_id": f"ctx-{suffix}",
        "message_id": f"msg-{suffix}", "state": "submitting",
        "planning_only": planning_only, "inputs": inputs, "responses": [],
    }
    _save(tool_context, record)
    instruction = (
        "Ты — внешняя система оптимизации и выполнения экспериментов. "
        "Получаешь ТЗ с целевой молекулой, физико-химические свойства и маршруты "
        "из литературы, маршруты синтеза и ранжирование по стоимости. "
        "Самостоятельно управляй полным циклом: планирование, необходимые CFD "
        "через свой MCP, оборудование, сбор фактических результатов и оптимизация "
        "по выполненным опытам. Учти результаты последнего опыта перед завершением. "
        "CoScientist не исполняет план локально. Не выбирай invalid/unpriceable "
        "маршруты; partial означает неполную стоимость, сохрани оговорки. "
        "economics_ranking.source=\"operator\" означает, что стоимости задал оператор, "
        "а не прайс поставщика (cost_source у маршрута). "
        "Верни исходные результаты: план и его изменения, выполненные опыты "
        "с параметрами, единицами и измерениями, CFD со статусами и идентификаторами, "
        "итог оптимизации с причиной остановки и незакрытыми критериями. "
        "Используй сообщения/artifacts A2A; не выдавай симуляции за измерения. "
        "Недостающие данные и необходимые подтверждения запрашивай в этой задаче. "
        "Сначала верни план на подтверждение. Не запускай CFD, физическое "
        "оборудование или эксперименты до отдельного сообщения с подтверждением плана. "
    )
    if planning_only:
        instruction += (
            "РЕЖИМ ТОЛЬКО ПЛАНИРОВАНИЯ/СКРИНИНГА: не запускай CFD, оборудование "
            "или эксперименты. Построй план верификации маршрута, явно свяжи каждое "
            "измерение с незакрытым ограничением и запроси подтверждение."
        )
    else:
        instruction += "Выполни задачу в пределах заданных требований и ограничений."
    text = instruction + "\n\n" + json.dumps(inputs, ensure_ascii=False, allow_nan=False)
    try:
        response = await asyncio.to_thread(
            _client().send_message, text=text, experiment_id=record["experiment_id"],
            context_id=record["context_id"], message_id=record["message_id"],
        )
        return _receive(tool_context, record, response)
    except (A2ARequestError, OSError, ValueError) as exc:
        return _failure(tool_context, record, "submission_unknown", exc)


async def optimization_get_status(tool_context: ToolContext) -> dict[str, Any]:
    """Poll the existing task; no resubmission, including after message timeouts."""
    record = tool_context.state.get(ACTIVE_KEY)
    if not record or not record.get("task_id"):
        return {"state": "error", "error": "No known task id; do not resubmit an uncertain task"}
    if record["state"] in TERMINAL:
        return record
    try:
        response = await asyncio.to_thread(_client().get_task, record["task_id"])
        return _receive(tool_context, record, response)
    except (A2ARequestError, OSError, ValueError) as exc:
        return _failure(tool_context, record, "status_error", exc)


async def _continue(context: ToolContext, record: dict, text: str) -> dict:
    message_id = f"msg-{uuid.uuid4().hex}"
    record = {**record, "state": "sending_input", "last_message_id": message_id,
              "sent_messages": [*record.get("sent_messages", []), {"message_id": message_id, "text": text}]}
    _save(context, record)  # Blocks duplicate confirmations during an in-flight send.
    try:
        response = await asyncio.to_thread(
            _client().send_message, text=text, experiment_id=record["experiment_id"],
            context_id=record["context_id"], message_id=message_id, task_id=record["task_id"],
        )
        return _receive(context, record, response)
    except (A2ARequestError, OSError, ValueError) as exc:
        return _failure(context, record, "followup_unknown", exc)


async def optimization_provide_input(details: str, tool_context: ToolContext) -> dict[str, Any]:
    """Supply known/user-provided missing data to the same waiting_input task."""
    record = tool_context.state.get(ACTIVE_KEY) or {}
    if not record.get("task_id") or record.get("state") != "input_required" or record.get("phase") != "waiting_input":
        return {"state": "error", "error": "Task is not waiting for missing data"}
    if not details.strip():
        return {"state": "error", "error": "Nonempty clarification required"}
    text = details.strip()
    if record.get("planning_only"):
        text += "\nРежим только планирования сохраняется. Не запускай CFD и оборудование."
    return await _continue(tool_context, record, text)


async def optimization_approve(tool_context: ToolContext) -> dict[str, Any]:
    """Approve the external system's current plan within the authorized work order.

    May start physical equipment remotely. Only valid for input_required/approval;
    planning-only tasks cannot be approved through this adapter.
    """
    record = tool_context.state.get(ACTIVE_KEY) or {}
    if record.get("planning_only"):
        return {"state": "error", "error": "Planning-only task cannot execute"}
    if not record.get("task_id") or record.get("state") != "input_required" or record.get("phase") != "approval":
        return {"state": "error", "error": "Task is not waiting for plan approval"}
    task = record.get("task") or {}
    plan = {"message": (task.get("status") or {}).get("message"), "artifacts": task.get("artifacts")}
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    approvals = record.get("approved_plans", [])
    if fingerprint in approvals:
        return {"state": "error", "error": "This plan was already approved; poll instead of confirming again"}
    if _operator_reachable(tool_context):
        from CoScientist.agents.common import hitl_handler
        from CoScientist.graph.session_scope import session_key
        from CoScientist.hitl.models import HITLAction, HITLRequest

        user_id, session_id = session_key(tool_context)
        decision = await hitl_handler.handle_request(HITLRequest(
            agent_name="OptimizerAgent",
            action_type=HITLAction.APPROVE,
            message=(
                "Внешняя A2A-система подготовила план, подтверждение может запустить "
                "CFD и физическое оборудование. Разрешить выполнение этого плана?"
            ),
            context={
                "output": plan,
                "task_id": record.get("task_id"),
                "_session": {"user_id": user_id, "session_id": session_id},
            },
            invoked_via="tool",
            trigger="optimization_plan_approval",
        ))
        if not decision.approved:
            return _save(tool_context, {
                **record,
                "state": "rejected",
                "phase": "operator_rejected",
                "error": decision.instructions or decision.free_input or "План отклонён оператором.",
            })
    record = {**record, "approved_plans": [*approvals, fingerprint]}
    return await _continue(tool_context, record, "Подтверждаю план. Выполни все шаги в рамках переданного ТЗ и ограничений, включая необходимые CFD, эксперименты и оптимизацию. Верни фактические результаты и итог последнего опыта.")
