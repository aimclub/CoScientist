from __future__ import annotations

import json
from typing import Any

from google.adk.events import Event
from google.adk.plugins import BasePlugin
from google.adk.runners import InvocationContext

from CoScientist.tools.fedot_trace_handler import FedotTraceHandler

_MAX_FIELD_CHARS = 800


def _unwrap_json_strings(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _unwrap_json_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_json_strings(v) for v in obj]
    if isinstance(obj, str) and obj[:1] in "{[":
        try:
            return _unwrap_json_strings(json.loads(obj))
        except (TypeError, ValueError):
            return obj
    return obj


def _safe_text(value: Any) -> str:
    try:
        text = json.dumps(_unwrap_json_strings(value), default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > _MAX_FIELD_CHARS:
        text = text[:_MAX_FIELD_CHARS] + f"… ({len(text)} chars total)"
    return text


def _request_shape(llm_request: Any) -> dict[str, Any]:
    """Cheap, no-tokenizer summary of an LlmRequest's size — attached to
    ``model_error`` so a context-window overflow shows its own cause (a huge
    ``max_output_tokens``, or a history that grew too long) right in the
    trace, instead of only the provider's raw error text.
    """
    try:
        config = getattr(llm_request, "config", None)
        contents = getattr(llm_request, "contents", None) or []
        chars = 0
        for content in contents:
            for part in getattr(content, "parts", None) or []:
                chars += len(getattr(part, "text", None) or "")
        return {
            "model": getattr(llm_request, "model", None),
            "max_output_tokens": getattr(config, "max_output_tokens", None),
            "turns": len(contents),
            "prompt_chars": chars,
        }
    except Exception:  # noqa: BLE001 — this is diagnostic best-effort, never fatal
        return {}


class FedotTracePlugin(BasePlugin):
    """Forwards FEDOT.MAS's ADK-level agent/tool events to a FedotTraceHandler."""

    def __init__(self, handler: FedotTraceHandler, run_id: str, name: str = "fedot_trace") -> None:
        super().__init__(name)
        self._handler = handler
        self._run_id = run_id

    async def _emit(self, event: str, **fields: Any) -> None:
        payload = {"type": "fedot_trace_event", "event": event, "run_id": self._run_id, **fields}
        try:
            await self._handler.broadcast(payload)
        except Exception:  # noqa: BLE001 — tracing must never break the actual run
            pass

    async def before_agent_callback(self, *, agent, callback_context):  # noqa: ANN001
        await self._emit("agent_start", agent_name=getattr(agent, "name", None))
        return None

    async def after_agent_callback(self, *, agent, callback_context):  # noqa: ANN001
        await self._emit("agent_end", agent_name=getattr(agent, "name", None))
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context):  # noqa: ANN001
        await self._emit(
            "tool_start",
            tool_name=getattr(tool, "name", None),
            tool_args=_safe_text(tool_args),
        )
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):  # noqa: ANN001
        await self._emit(
            "tool_end",
            tool_name=getattr(tool, "name", None),
            result_summary=_safe_text(result),
        )
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):  # noqa: ANN001
        await self._emit(
            "tool_error",
            tool_name=getattr(tool, "name", None),
            error=str(error),
        )
        return None

    async def on_model_error_callback(self, *, callback_context, llm_request, error):  # noqa: ANN001
        await self._emit(
            "model_error",
            agent_name=getattr(callback_context, "agent_name", None),
            error=str(error),
            **_request_shape(llm_request),
        )
        return None

    async def on_event_callback(  # noqa: ANN001
        self, *, invocation_context: InvocationContext, event: Event
    ):
        """Forwards the per-event detail fedotmas's own LoggingPlugin only
        sends to loguru (tokens, state_delta) — before/after_agent/tool_
        callback above never see those, so without this the trace tab is
        blind to them.
        """
        if event.partial:
            return None

        if event.usage_metadata:
            um = event.usage_metadata
            prompt = um.prompt_token_count or 0
            completion = um.candidates_token_count or 0
            if prompt or completion:
                await self._emit(
                    "tokens",
                    agent_name=event.author,
                    prompt=prompt,
                    completion=completion,
                )

        # The raw text a model turn produced — independent of state_delta
        # (below), which only shows up when the agent has an `output_key` and
        # only carries its LAST turn. A mid-pipeline reasoning turn, a worker
        # with no output_key, or anything before the final answer was
        # otherwise invisible in the trace even though the model said it.
        if event.content and event.content.parts:
            text = "\n".join(
                part.text for part in event.content.parts if part.text
            )
            if text:
                await self._emit(
                    "model_response",
                    agent_name=event.author,
                    text=_safe_text(text),
                )

        if event.actions.state_delta:
            # MAW-style worker agents (see fedotmas.maw.builder) write their
            # actual output — the EDA report, the tuned pipeline, feature
            # importances — via `output_key` straight into state, not through
            # a tool call or the final agent message. Sending only the keys
            # here (as this used to) hid that content entirely: the trace
            # showed the agent ran but never what it produced. Values are
            # truncated the same way every other field is.
            await self._emit(
                "state_update",
                agent_name=event.author,
                state={k: _safe_text(v) for k, v in event.actions.state_delta.items()},
            )

        return None
