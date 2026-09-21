"""Route-compliance rule semantics after the over-strict-gate fix.

A literature route must reach economics/experiment carrying honest caveats,
not be silently killed. Three behaviours are pinned:
  * temperature is a RANGE — it complies when it OVERLAPS the ТЗ window;
  * «в спирте или воде» permits an ethanol route (water_or_alcohol);
  * an unparsed ТЗ clause (no machine rule) is `needs_review`, not a block.
"""
from CoScientist.microfluidics.models import (
    NamedValue, ProcessStep, RequirementConstraint, RequirementSource,
    RequirementsSpec, Substance, SynthesisRoute,
)
from CoScientist.microfluidics import route_compliance as rc
from CoScientist.microfluidics.requirements import compile_requirements


def _temp_constraint(minimum=25.0, maximum=70.0):
    return RequirementConstraint(
        constraint_id="REQ-TEMP", scope="step", kind="temperature_range",
        hardness="hard", operator="within", value={"minimum": minimum, "maximum": maximum},
        resolution="confirmed", machine_evaluable=True,
        source=RequirementSource(block="b", field="f", field_status="задано заказчиком", value="v"),
    )


def _route(temp="50–80 °C", solvent="этанол", route_id="R1"):
    conds = [NamedValue(name="Температура", value=temp),
             NamedValue(name="Растворитель", value=solvent)]
    step = ProcessStep(operation="Манних", reactants=[Substance(name="2,6-ДТБФ")],
                       products=[Substance(name="P")], conditions=conds,
                       conditions_status="reported", yield_fraction=0.85, yield_status="reported")
    return SynthesisRoute(route_id=route_id, product=Substance(name="P"), steps=[step])


def _check(route, constraint):
    spec = RequirementsSpec(constraints=[constraint])
    out = rc.evaluate_route(route, spec, [])
    return next(c for c in out.tz_compliance if c.constraint_id == constraint.constraint_id)


def test_temperature_range_overlap_is_not_a_fail():
    # 50–80 vs 25–70: overlaps at 50–70 → not fail (unverified, no source).
    c = _check(_route(temp="50–80 °C"), _temp_constraint())
    assert c.status == "unverified"
    assert "50–70" in c.reason


def test_temperature_wholly_outside_still_fails():
    c = _check(_route(temp="90–120 °C"), _temp_constraint())
    assert c.status == "fail"


def test_temperature_inside_window_without_source_is_unverified():
    c = _check(_route(temp="60 °C"), _temp_constraint())
    assert c.status == "unverified"


def test_alcohol_or_water_medium_accepts_ethanol():
    tz = {"original_request": "", "blocks": [{"title": "Ограничения по технологии", "fields": [
        {"name": "Среда синтеза", "value": "в спирте или воде", "status": "задано заказчиком"}]}]}
    spec = compile_requirements(tz)
    aq = next(c for c in spec.constraints if c.kind == "aqueous_medium")
    assert aq.value["medium"] == "water_or_alcohol"
    c = _check(_route(solvent="этанол"), aq)
    assert c.status in ("unverified", "pass")  # ethanol satisfies water_or_alcohol


def test_unparsed_clause_needs_review_not_block():
    # A hard clause with no machine rule must not block the route.
    unparsed = RequirementConstraint(
        constraint_id="REQ-X", scope="step", kind="unparsed_constraint",
        hardness="hard", operator="requires_review", value={"description": "без газовыделения"},
        resolution="confirmed", machine_evaluable=False,
        source=RequirementSource(block="b", field="f", field_status="задано заказчиком", value="v"),
    )
    spec = RequirementsSpec(constraints=[unparsed])
    out = rc.evaluate_route(_route(), spec, [])
    c = next(x for x in out.tz_compliance if x.constraint_id == "REQ-X")
    assert c.status == "needs_review"
    assert out.overall_status == "eligible"


def test_temperature_range_overlap_yields_eligible_route():
    q = rc.qualify_routes([_route(temp="50–80 °C")], RequirementsSpec(constraints=[_temp_constraint()]), [])
    assert q.status == "ok"
    assert [r.route_id for r in q.routes] == ["R1"]


def test_missing_conditions_still_blocks():
    # No conditions at all → SYS-CONDITIONS-COMPLETE unknown → blocked.
    step = ProcessStep(operation="op", reactants=[Substance(name="A")], products=[Substance(name="P")],
                       conditions=[], conditions_status="missing",
                       conditions_missing_reason="нет данных",
                       yield_fraction=None, yield_status="missing", yield_missing_reason="нет")
    route = SynthesisRoute(route_id="R2", product=Substance(name="P"), steps=[step])
    out = rc.evaluate_route(route, RequirementsSpec(constraints=[]), [])
    assert out.overall_status == "blocked"
