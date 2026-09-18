"""Session-scoped tools for the optimization service's documented A2A dialect.

Only the remote optimizer owns CFD. Raw tasks (including artifacts and status
messages) are retained for reporting. No equipment approval is sent here.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext

from .a2a_test_client import A2AClient, A2ARequestError, task_from_response, task_phase, task_state

ACTIVE_KEY = "optimization_a2a_task"
HISTORY_KEY = "optimization_a2a_runs"
INPUT_KEYS = (
    "structured_tz", "literature_analysis", "synthesis_routes", "economics",
    "economics_ranking", "experiment_plan", "experiment_journal",
)


def _client() -> A2AClient:
    url = os.getenv("OPTIMIZATION_A2A_URL") or os.getenv(
        "A2A_ROUTER_PUBLIC_URL", "http://127.0.0.1:19000/"
    )
    return A2AClient(url, timeout=30.0)


def _save(context: ToolContext, record: dict) -> dict:
    context.state[ACTIVE_KEY] = record
    history = dict(context.state.get(HISTORY_KEY) or {})
    history[record["experiment_id"]] = record
    context.state[HISTORY_KEY] = history
    return record


def _receive(context: ToolContext, record: dict, response: dict) -> dict:
    task = task_from_response(response)
    if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
        raise A2ARequestError("A2A response contains no task id", response)
    if record.get("task_id") and task["id"] != record["task_id"]:
        raise A2ARequestError("A2A returned a different task id", response)
    if task.get("contextId") and task["contextId"] != record["context_id"]:
        raise A2ARequestError("A2A returned a different context id", response)
    status = task.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("state"), str):
        raise A2ARequestError("A2A task contains no status state", response)
    state = task_state(task).removeprefix("TASK_STATE_").lower().replace("-", "_")
    if state == "cancelled":
        state = "canceled"
    if state not in {"submitted", "working", "input_required", "completed", "failed", "rejected", "canceled"}:
        raise A2ARequestError(f"Unknown A2A task state: {state}", response)
    message = status.get("message") or {}
    if not isinstance(message, dict) or not isinstance(message.get("parts", []), list):
        raise A2ARequestError("Malformed A2A status message", response)
    if not isinstance(task.get("artifacts", []), list):
        raise A2ARequestError("Malformed A2A artifacts", response)
    return _save(context, {
        **record, "task_id": task["id"], "state": state,
        "phase": task_phase(task), "task": task, "response": response,
        "error": None,
    })


async def optimization_start(tool_context: ToolContext) -> dict[str, Any]:
    """Send routes, economics, draft plan and actual journal to the optimizer.

    Repeated calls reuse the current task until EquipmentAgent consumes its
    result. CFD calculations must be requested from this service, never locally.
    """
    previous = tool_context.state.get(ACTIVE_KEY)
    if previous and not previous.get("consumed"):
        return previous
    inputs = {key: tool_context.state.get(key) for key in INPUT_KEYS}
    if not inputs["synthesis_routes"] or not inputs["experiment_plan"]:
        return {"state": "error", "error": "Synthesis routes and a draft experiment plan are required"}
    suffix = uuid.uuid4().hex
    record = {
        "experiment_id": f"optimization-{suffix}", "context_id": f"ctx-{suffix}",
        "message_id": f"msg-{suffix}", "state": "submitting", "consumed": False,
        "inputs": inputs,
    }
    # Persist before sending: a timeout can mean the server accepted the task.
    # Do not silently create another experiment on a subsequent tool call.
    _save(tool_context, record)
    text = (
        "Ты — модуль оптимизации экспериментов. На основе ТЗ, маршрутов синтеза, "
        "экономического рейтинга и выполненных опытов подготовь следующий полный "
        "план экспериментов с параметрами, единицами и критериями остановки. "
        "Необходимые расчёты CFD вызывай самостоятельно через свой MCP. "
        "Верни результаты CFD и их статусы без выдуманных чисел. "
        "Отделяй данные заглушек от измерений. Если оптимизация закончена, "
        "укажи причину и достигнутые критерии. Не запускай физическое оборудование: "
        "план исполняет отдельный агент управления установкой. Если нужны данные "
        "или подтверждение, запроси их; не считай запрос подтверждённым.\n\n"
        + json.dumps(inputs, ensure_ascii=False)
    )
    try:
        client = _client()
        response = await asyncio.to_thread(
            client.send_message, text=text, experiment_id=record["experiment_id"],
            context_id=record["context_id"], message_id=record["message_id"],
        )
        return _receive(tool_context, record, response)
    except (A2ARequestError, OSError, ValueError) as exc:
        return _save(tool_context, {
            **record, "state": "submission_unknown", "error": str(exc),
            "error_response": getattr(exc, "response", None),
        })


async def optimization_get_status(tool_context: ToolContext) -> dict[str, Any]:
    """Read the current session's A2A task, preserving its complete result.

    Poll submitted/working tasks with sleep_tool between calls. input_required
    is a pause, not a successful calculation or permission to run equipment.
    """
    record = tool_context.state.get(ACTIVE_KEY)
    if not record or not record.get("task_id"):
        return {"state": "error", "error": "No known A2A task id; do not resubmit an uncertain task"}
    if record["state"] in {"completed", "failed", "rejected", "canceled"}:
        return record
    try:
        response = await asyncio.to_thread(_client().get_task, record["task_id"])
        return _receive(tool_context, record, response)
    except (A2ARequestError, OSError, ValueError) as exc:
        return _save(tool_context, {
            **record, "state": "status_error", "error": str(exc),
            "error_response": getattr(exc, "response", None),
        })


def require_optimization_result(callback_context: CallbackContext):
    """Prevent rig execution without a fresh, completed optimization task."""
    from google.genai import types

    record = callback_context.state.get(ACTIVE_KEY) or {}
    task = record.get("task") or {}
    message = (task.get("status") or {}).get("message") or {}
    has_result = bool(task.get("artifacts") or message.get("parts"))
    if record.get("state") != "completed" or record.get("consumed") or not has_result:
        callback_context.actions.escalate = True
        return types.Content(role="model", parts=[types.Part(text=(
            "Опыты не выполнялись: нет нового завершённого результата A2A-оптимизации. "
            f"Статус: {record.get('state', 'not_started')}; фаза: {record.get('phase', '')}."
        ))])
    _save(callback_context, {**record, "consumed": True})
    return None
