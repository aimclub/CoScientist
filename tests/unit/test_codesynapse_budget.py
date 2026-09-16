import pytest

from CoScientist.integrations.codesynapse.budget import BudgetExceeded, BudgetGuard, RunLimits


def test_budget_reserves_before_a_model_call_and_reconciles_actual_usage():
    guard = BudgetGuard(RunLimits(max_model_calls=1, max_token_budget=100, max_monetary_budget=1.0))

    reservation = guard.reserve_model_call(max_tokens=80, max_cost=0.8)
    guard.reconcile_model_call(reservation, actual_tokens=50, actual_cost=0.5)

    assert guard.tokens_used == 50
    assert guard.cost_used == 0.5


def test_budget_blocks_call_when_reservation_exceeds_hard_limit():
    guard = BudgetGuard(RunLimits(max_model_calls=1, max_token_budget=100, max_monetary_budget=1.0))

    with pytest.raises(BudgetExceeded):
        guard.reserve_model_call(max_tokens=101, max_cost=0.5)
