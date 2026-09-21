"""A route with evidence gaps may be screened, but cannot enter production costing."""
from CoScientist.microfluidics.route_compliance import qualify_routes


def _route(*, yield_fraction=None):
    step = {
        "operation": "Aqueous reaction",
        "reactants": [{"name": "Feed"}],
        "products": [{"name": "Product"}],
        "conditions": [{"name": "Среда", "value": "water"}],
    }
    if yield_fraction is None:
        step.update({"yield_status": "missing", "yield_missing_reason": "Требуется измерение выхода"})
    else:
        step["yield_fraction"] = yield_fraction
    return {"routes": [{"route_id": "LIT-1", "product": {"name": "Product"}, "steps": [step]}]}


def test_missing_yield_becomes_screening_candidate_not_rejection():
    result = qualify_routes(_route(), {"constraints": []})
    assert result.status == "screening_only"
    assert not result.routes
    assert result.experimental_routes[0].overall_status == "experimental"


def test_unverified_conditions_remain_screening_only_even_with_a_yield():
    result = qualify_routes(_route(yield_fraction=0.8), {"constraints": []})
    assert result.status == "screening_only"
    assert result.experimental_routes[0].overall_status == "experimental"
