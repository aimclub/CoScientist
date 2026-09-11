"""Field statuses of the microfluidics ТЗ.

«автоподбор» — the agent inferred the value itself; «уточнено оператором» —
only what a human set when reviewing; «не требуется» — deliberately left
unconstrained: never handed to the agent, the way to leave a field empty or
to clear an agent value that is not needed."""
from CoScientist.hitl.field_status import (
    AGENT_FILLED_STATUS,
    AUTO_STATUS,
    NOT_REQUIRED_STATUS,
    NOT_REQUIRED_VALUE,
    OPERATOR_STATUS,
)
from CoScientist.microfluidics.models import StructuredTZ, TZBlock, TZFieldRow
from CoScientist.microfluidics.render import render_tz_document
from CoScientist.microfluidics.tz_builder import ALLOWED_STATUSES, validate_section_fields
from CoScientist.microfluidics.tz_review import apply_operator_values, tz_view

SECTION = "Критерии качества"


def _tz(*fields):
    return StructuredTZ(original_request="r", blocks=[TZBlock(
        title=SECTION, usage="u",
        fields=[TZFieldRow(name=n, value=v, status=s) for n, v, s in fields],
    )])


def _row(tz, name):
    return next(f for f in tz.block(SECTION).fields if f.name == name)


# ── what the model may write ─────────────────────────────────────────────────

def test_model_may_use_auto_pick_and_not_required_but_not_agent_filled():
    assert AUTO_STATUS in ALLOWED_STATUSES
    assert NOT_REQUIRED_STATUS in ALLOWED_STATUSES
    assert AGENT_FILLED_STATUS not in ALLOWED_STATUSES


def test_auto_pick_needs_a_value():
    _rows, errors = validate_section_fields(
        [{"name": "Чистота", "value": "", "status": AUTO_STATUS}], where="w",
    )
    assert errors and "«автоподбор»" in errors[0]


def test_not_required_needs_no_value():
    rows, errors = validate_section_fields(
        [{"name": "Допустимые примеси", "value": "", "status": NOT_REQUIRED_STATUS}],
        where="w",
    )
    assert errors == []
    assert (rows[0].value, rows[0].status) == (NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS)


# ── what the operator's form does ────────────────────────────────────────────

def test_marking_a_field_not_required_keeps_it_from_the_agent():
    tz = _tz(("Чистота", "Не задано", "не задано"), ("Примеси", "Не задано", "не задано"))

    answers = apply_operator_values(tz, {SECTION: {"Чистота": NOT_REQUIRED_VALUE, "Примеси": ""}})

    assert (_row(answers.tz, "Чистота").status, _row(answers.tz, "Чистота").value) == (
        NOT_REQUIRED_STATUS, NOT_REQUIRED_VALUE,
    )
    assert answers.not_required == 1
    assert answers.left_to_agent == [(SECTION, ["Примеси"])]


def test_typing_not_required_works_too():
    tz = _tz(("Чистота", "Не задано", "не задано"))
    answers = apply_operator_values(tz, {SECTION: {"Чистота": "  Не требуется "}})
    assert _row(answers.tz, "Чистота").status == NOT_REQUIRED_STATUS


def test_an_agent_value_that_is_not_needed_can_be_cleared():
    tz = _tz(("Чистота", "≥ 95 %", AGENT_FILLED_STATUS))
    answers = apply_operator_values(tz, {SECTION: {"Чистота": NOT_REQUIRED_VALUE}})
    assert _row(answers.tz, "Чистота").status == NOT_REQUIRED_STATUS
    assert answers.left_to_agent == []


def test_not_required_stays_as_is_or_comes_back_to_life():
    tz = _tz(
        ("Kept", NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS),
        ("Typed", NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS),
        ("Cleared", NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS),
    )

    answers = apply_operator_values(tz, {SECTION: {
        "Kept": NOT_REQUIRED_VALUE, "Typed": "≥ 99 %", "Cleared": "",
    }})

    assert _row(answers.tz, "Kept").status == NOT_REQUIRED_STATUS
    assert answers.not_required == 0  # nothing new
    assert (_row(answers.tz, "Typed").value, _row(answers.tz, "Typed").status) == (
        "≥ 99 %", OPERATOR_STATUS,
    )
    assert answers.left_to_agent == [(SECTION, ["Cleared"])]


def test_an_auto_picked_value_the_operator_keeps_stays_auto_picked():
    tz = _tz(("Чистота", "≥ 95 %", AUTO_STATUS))
    answers = apply_operator_values(tz, {SECTION: {"Чистота": "≥ 95 %"}})
    assert _row(answers.tz, "Чистота").status == AUTO_STATUS
    answers = apply_operator_values(tz, {SECTION: {"Чистота": "≥ 98 %"}})
    assert _row(answers.tz, "Чистота").status == OPERATOR_STATUS


# ── what the panel and the document show ─────────────────────────────────────

def test_the_panel_flags_not_required_fields_without_awaiting_them():
    view = tz_view(_tz(("Чистота", NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS)))
    field = view["sections"][0]["fields"][0]
    assert field["not_required"] and not field["awaiting"]
    assert view["counts"]["not_required"] == 1
    assert view["counts"]["awaiting_fields"] == 0
    assert view["not_required_value"] == NOT_REQUIRED_VALUE


def test_the_document_explains_both_statuses_and_lists_free_fields():
    document = render_tz_document(_tz(
        ("Чистота", "≥ 95 %", AUTO_STATUS),
        ("Примеси", NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS),
    ))
    assert "| Автоподбор" in document
    assert "| Не требуется" in document
    free = document.split("## Поля, которые остаются свободными или незаполненными")[1]
    assert "Примеси" in free.split("\n---\n")[0]
    assert "Чистота" not in free.split("\n---\n")[0]
