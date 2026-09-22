"""Conservative per-run resource guards independent of a model provider SDK."""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """Raised before a call that cannot be safely reserved."""


@dataclass(frozen=True)
class RunLimits:
    max_agent_invocations: int | None = None
    max_model_calls: int | None = None
    max_tool_attempts: int | None = None
    max_token_budget: int | None = None
    max_monetary_budget: float | None = None


@dataclass(frozen=True)
class ModelReservation:
    max_tokens: int
    max_cost: float


class BudgetGuard:
    """Reserves before model calls and records actual usage afterwards."""

    def __init__(self, limits: RunLimits) -> None:
        self._limits = limits
        self.model_calls = 0
        self.agent_invocations = 0
        self.tool_attempts = 0
        self.tokens_used = 0
        self.cost_used = 0.0
        self._tokens_reserved = 0
        self._cost_reserved = 0.0

    def reserve_model_call(self, *, max_tokens: int, max_cost: float) -> ModelReservation:
        if max_tokens < 0 or max_cost < 0:
            raise ValueError("reservation values must be non-negative")
        if self._limits.max_model_calls is not None and self.model_calls >= self._limits.max_model_calls:
            raise BudgetExceeded("max_model_calls exceeded")
        if self._limits.max_token_budget is not None and self.tokens_used + self._tokens_reserved + max_tokens > self._limits.max_token_budget:
            raise BudgetExceeded("max_token_budget exceeded")
        if self._limits.max_monetary_budget is not None and self.cost_used + self._cost_reserved + max_cost > self._limits.max_monetary_budget:
            raise BudgetExceeded("max_monetary_budget exceeded")
        self.model_calls += 1
        self._tokens_reserved += max_tokens
        self._cost_reserved += max_cost
        return ModelReservation(max_tokens=max_tokens, max_cost=max_cost)

    def reconcile_model_call(self, reservation: ModelReservation, *, actual_tokens: int, actual_cost: float) -> None:
        if actual_tokens < 0 or actual_cost < 0:
            raise ValueError("actual usage must be non-negative")
        self._tokens_reserved -= reservation.max_tokens
        self._cost_reserved -= reservation.max_cost
        self.tokens_used += actual_tokens
        self.cost_used += actual_cost

    def record_agent_invocation(self) -> None:
        self.agent_invocations += 1
        if self._limits.max_agent_invocations is not None and self.agent_invocations > self._limits.max_agent_invocations:
            raise BudgetExceeded("max_agent_invocations exceeded")

    def record_tool_attempt(self) -> None:
        self.tool_attempts += 1
        if self._limits.max_tool_attempts is not None and self.tool_attempts > self._limits.max_tool_attempts:
            raise BudgetExceeded("max_tool_attempts exceeded")
