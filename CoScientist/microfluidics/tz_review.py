"""Operator review of the assembled ТЗ through the web ТЗ panel (HITL form).

Once TZSpecAgent has filled every section, the operator gets the ТЗ as a form
in the ТЗ panel of the web UI:

  * sections that still have empty «не задано» fields come FIRST — they are
    what the human is expected to fill; sections that are complete follow, in
    ascending section order (the panel moves a section down as soon as its
    empty fields are filled);
  * every field can be edited; a value typed by the operator becomes
    «уточнено оператором»;
  * a field the operator leaves EMPTY goes to the agent — it fills it through
    ``fill_agent_fields`` as «заполнено агентом», and the ТЗ comes back to the
    operator with those fields highlighted. Round after round, until the
    operator submits a form with nothing left empty.

``tz_view`` is the one serialisation of the ТЗ the panel reads — both the
HITL form and the live ``tz_snapshot`` stream use it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from CoScientist.hitl.field_status import AGENT_FILLED_STATUS, OPERATOR_STATUS
from CoScientist.microfluidics.models import CANONICAL_BLOCKS, StructuredTZ
from CoScientist.microfluidics.questionnaire import QUESTION_BANK
from CoScientist.microfluidics.tz_builder import is_empty_value

FORM_KIND = "tz"
AWAITING_STATUS = "не задано"
DEFERRED_STATUS = "рассчитывается агентом"


def section_number(title: str, position: int) -> int:
    """The number the panel shows: the canonical one, extras after them."""
    try:
        return CANONICAL_BLOCKS.index(title) + 1
    except ValueError:
        return len(CANONICAL_BLOCKS) + position + 1


def tz_view(tz: StructuredTZ, agent_fill: Optional[dict] = None) -> dict:
    """The ТЗ as the web panel renders it (sections -> fields with flags)."""
    pending = {
        p.get("section"): set(p.get("fields") or [])
        for p in ((agent_fill or {}).get("pending") or [])
    }
    sections: List[dict] = []
    for position, block in enumerate(tz.blocks):
        question, hint = QUESTION_BANK.get(block.title, ("", ""))
        waiting = pending.get(block.title, set())
        fields = [
            {
                "name": f.name,
                "value": f.value,
                "status": f.status,
                "awaiting": f.status == AWAITING_STATUS,
                "deferred": f.status == DEFERRED_STATUS,
                "agent_filled": f.status == AGENT_FILLED_STATUS,
                "agent_pending": f.name in waiting,
            }
            for f in block.fields
        ]
        sections.append({
            "num": section_number(block.title, position),
            "title": block.title,
            "usage": block.usage,
            "question": question,
            "hint": hint,
            "awaiting": any(f["awaiting"] for f in fields),
            "fields": fields,
        })
    all_fields = [f for s in sections for f in s["fields"]]
    return {
        "original_request": tz.original_request,
        "sections": sections,
        "counts": {
            "sections": len(sections),
            "awaiting_sections": sum(1 for s in sections if s["awaiting"]),
            "awaiting_fields": sum(1 for f in all_fields if f["awaiting"]),
            "agent_filled": sum(1 for f in all_fields if f["agent_filled"]),
        },
    }


def tz_form(tz: StructuredTZ, round_no: int) -> dict:
    """The HITLRequest.form payload for one review round."""
    view = tz_view(tz)
    counts = view["counts"]
    if counts["awaiting_fields"]:
        intro = (
            f"Не заполнено полей: {counts['awaiting_fields']} в "
            f"{counts['awaiting_sections']} разделах — они вверху. Впишите "
            "известные значения; поля, оставленные пустыми, заполнит агент."
        )
    else:
        intro = "Все поля заполнены. Проверьте значения и подтвердите ТЗ."
    if counts["agent_filled"]:
        intro += (
            f" Агент заполнил полей: {counts['agent_filled']} — они выделены; "
            "исправьте их при необходимости."
        )
    return {"kind": FORM_KIND, "title": "Техническое задание", "intro": intro,
            "round": round_no, **view}


@dataclass
class OperatorAnswers:
    """What one submitted form did to the ТЗ."""

    tz: StructuredTZ
    set_by_operator: int = 0
    # [(section, [field names])] in document order — to be filled by the agent.
    left_to_agent: List[Tuple[str, List[str]]] = field(default_factory=list)

    @property
    def left_count(self) -> int:
        return sum(len(names) for _s, names in self.left_to_agent)


def apply_operator_values(tz: StructuredTZ, form_values: Any) -> OperatorAnswers:
    """Fold a submitted form ({section: {field: value}}) onto the ТЗ.

    Per field present in the form: a new non-empty value -> «уточнено
    оператором»; the same value as before -> unchanged (an agent value the
    operator kept stays «заполнено агентом»); an empty value -> left to the
    agent (the field becomes «не задано» until the agent fills it). Fields
    «рассчитывается агентом» are deferred to later stages, so leaving them
    empty keeps them as they are. Fields missing from the form are untouched.
    """
    tz = tz.model_copy(deep=True)
    answers = OperatorAnswers(tz=tz)
    if not isinstance(form_values, dict):
        return answers
    for block in tz.blocks:
        submitted = form_values.get(block.title)
        if not isinstance(submitted, dict):
            continue
        left: List[str] = []
        for f in block.fields:
            if f.name not in submitted:
                continue
            raw = submitted[f.name]
            new = "" if raw is None else str(raw).strip()
            if is_empty_value(new):
                if f.status == DEFERRED_STATUS:
                    continue
                f.value, f.status = "Не задано", AWAITING_STATUS
                left.append(f.name)
            elif f.status == AWAITING_STATUS or new != f.value.strip():
                f.value, f.status = new, OPERATOR_STATUS
                answers.set_by_operator += 1
        if left:
            answers.left_to_agent.append((block.title, left))
    return answers


def agent_fill_message(answers: OperatorAnswers, instruction: str) -> str:
    """The turn that sends the agent to fill what the operator left empty."""
    sections = len(answers.left_to_agent)
    return (
        "Оператор проверил ТЗ в веб-форме. Введённые им значения уже внесены в "
        f"ТЗ (полей: {answers.set_by_operator}). {answers.left_count} пол(я/ей) в "
        f"{sections} раздел(е/ах) оператор оставил пустыми — их должен заполнить "
        "ты: конкретными рабочими значениями из запроса и отраслевого контекста, "
        "по одному разделу за вызов fill_agent_fields, строго в указанном порядке. "
        "Остальные поля не меняй и fill_tz_section не вызывай. " + instruction
    )


__all__ = [
    "AWAITING_STATUS",
    "DEFERRED_STATUS",
    "FORM_KIND",
    "OperatorAnswers",
    "agent_fill_message",
    "apply_operator_values",
    "section_number",
    "tz_form",
    "tz_view",
]
