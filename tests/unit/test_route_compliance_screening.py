"""A route with evidence gaps may be screened, but cannot enter production costing."""
from types import SimpleNamespace

from CoScientist.microfluidics.route_compliance import guard_economics_routes, qualify_routes


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


def test_route_without_reaction_sides_is_screening_only_before_costing():
    route = _route(yield_fraction=0.8)
    route["routes"][0]["steps"][0]["reactants"] = []
    result = qualify_routes(route, {"constraints": []})

    assert result.status == "screening_only"
    check = next(
        item for item in result.experimental_routes[0].tz_compliance
        if item.constraint_id == "SYS-ECONOMICS-ROUTE-SHAPE"
    )
    assert check.status == "unknown"
    assert "reactants" in check.reason


def test_costing_guard_explains_incomplete_legacy_qualified_route():
    route = _route(yield_fraction=0.8)["routes"][0]
    route["overall_status"] = "eligible"
    route["steps"][0]["products"] = []
    context = SimpleNamespace(state={"qualified_routes": {"status": "ok", "routes": [route]}})

    blocked = guard_economics_routes(
        tool=SimpleNamespace(name="rank_routes_by_cost"),
        args={"routes": [{"route_id": "LIT-1", "steps": [{
            "reactants": [{"name": "Feed"}], "products": [], "yield": 0.8,
        }]}]},
        tool_context=context,
    )

    assert blocked is not None
    assert "requires nonempty products" in blocked["reasons"][0]
