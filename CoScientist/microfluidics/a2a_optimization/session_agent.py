"""Session agent that cannot finish while its external A2A task is still running."""
from __future__ import annotations

from typing import Optional

from google.adk.agents.invocation_context import InvocationContext

from CoScientist.hitl.session_agent import SessionAgent
from CoScientist.microfluidics.a2a_optimization.adapter import ACTIVE_KEY


class OptimizationSessionAgent(SessionAgent):
    """Feed an early final answer back until A2A reaches a stable boundary."""

    unfinished_max_rounds: int = 12

    def _unfinished_feedback(self, ctx: InvocationContext) -> Optional[str]:
        task = ctx.session.state.get(ACTIVE_KEY)
        if not isinstance(task, dict):
            return None
        state = str(task.get("state") or "")
        if state in {"submitting", "sending_input", "submitted", "working"}:
            return (
                "Внешняя A2A-задача ещё не завершена. Не закрывай стадию: вызови "
                "sleep_tool(minutes=0.1), затем optimization_get_status и продолжай "
                "тот же task_id. Завершить можно только на terminal state или когда "
                "действительно требуется новый ввод пользователя."
            )
        if state == "input_required" and task.get("phase") == "approval":
            return (
                "Внешняя система ждёт утверждения плана. Проверь план и вызови "
                "optimization_approve; сам инструмент запросит решение человека."
            )
        return None


__all__ = ["OptimizationSessionAgent"]
