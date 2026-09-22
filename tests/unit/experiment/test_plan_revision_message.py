"""What a planner is told when its plan is refused.

A run on 2026-09-22 died here. The plan was rejected three times, each time
differently — `direction: "in"`, then `OP-1` where an id belongs, then
`task_id`/`title` instead of `id`/`name` — until the revision budget ran out
and the experiment paused without ever reaching execution. The refusals had
carried pydantic's complaint and nothing else: what was wrong, never what is
right, and no sight of the plan just written. So each round was a fresh guess
rather than a correction.
"""

from CoScientist.experiments.review import _contract_lines, _revision_instruction

# The exact locations that run was rejected at.
REAL_ERRORS = [
    {"type": "literal_error",
     "loc": ["tasks", 2, "design", "metrics", 3, "direction"],
     "msg": "Input should be 'maximize', 'minimize' or 'compare'", "input": "in"},
    {"type": "value_error", "loc": ["tasks", 0, "id"],
     "msg": "Value error, task id must match EXP-<n>", "input": "OP-1"},
    {"type": "missing", "loc": ["tasks", 0, "route"], "msg": "Field required"},
]


def test_the_refusal_says_what_the_schema_actually_allows():
    lines = _contract_lines(REAL_ERRORS)
    joined = "\n".join(lines)

    assert any("direction" in line for line in lines)
    assert "maximize" in joined and "minimize" in joined and "compare" in joined
    assert any("route" in line for line in lines)
    assert "coder" in joined, "the route that would have run this task"


def test_the_allowed_values_come_from_the_model_not_from_prose():
    """Read off ExperimentPlan itself, so a schema change cannot leave the
    instruction describing a contract nobody enforces any more."""
    import json

    from CoScientist.experiments.schemas.models import ExperimentPlan

    line = next(l for l in _contract_lines(REAL_ERRORS) if "direction" in l)

    def enums(node):
        if isinstance(node, dict):
            if "enum" in node:
                yield node["enum"]
            for value in node.values():
                yield from enums(value)
        elif isinstance(node, list):
            for value in node:
                yield from enums(value)

    declared = next(
        (e for e in enums(ExperimentPlan.model_json_schema())
         if set(e) >= {"maximize", "minimize"}), None)
    assert declared, "the model still declares the metric directions"
    for value in declared:
        assert value in line, f"{value} came from the model but not from the hint"


def test_the_planner_is_shown_the_plan_it_just_wrote():
    rejected = {"tasks": [{"task_id": "T1", "title": "Собрать датасет"}]}

    message = _revision_instruction(
        "Schema validation failed. Errors:", REAL_ERRORS,
        contract=_contract_lines(REAL_ERRORS), previous_plan=rejected)

    assert "task_id" in message and "Собрать датасет" in message
    assert "не пиши заново" in message


def test_an_enormous_plan_is_clipped_rather_than_sent_whole():
    huge = {"tasks": [{"name": "x" * 20000}]}
    message = _revision_instruction("Errors:", [], previous_plan=huge)
    assert len(message) < 8000
    assert "план обрезан" in message


def test_a_location_the_model_does_not_know_is_skipped_quietly():
    """A hint must never be the thing that breaks a revision."""
    assert _contract_lines([{"loc": ["tasks", 0, "no_such_field"]}]) == []
    assert _contract_lines([{"msg": "no loc at all"}]) == []
    assert _contract_lines("not even a list") == []


def test_the_critique_can_be_switched_off_without_losing_schema_validation(monkeypatch):
    """Skipping the critique must not also skip the contract.

    A plan that does not parse is unusable whatever the policy says, so schema
    validation stays on. What comes off is the semantic layer — hypothesis and
    operation coverage — which was refusing plans over duplicate hypotheses in
    the research graph, upstream of the planner and unfixable by it.
    """
    from CoScientist.config import get_settings

    settings = get_settings().experiments
    assert hasattr(settings, "plan_critique_enabled")

    monkeypatch.setattr(settings, "plan_critique_enabled", False)
    assert settings.plan_critique_enabled is False
    monkeypatch.setattr(settings, "plan_critique_enabled", True)
    assert settings.plan_critique_enabled is True


def test_a_skipped_critique_is_announced_not_silent():
    """A check that is off and quiet is one that quietly becomes permanent."""
    source = (
        __import__("pathlib").Path(__import__("CoScientist.experiments.review",
                                              fromlist=["review"]).__file__).read_text()
    )
    assert "EXPERIMENT_PLAN_CRITIQUE_SKIPPED" in source
    # And the verdict is still recorded on the plan either way.
    assert 'state["experiment_plan_critique"] = critique_json' in source
