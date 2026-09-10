"""The Research Frame — the framing entities of the meta-model as a filled form.

One frame = one run. The frame mirrors the microfluidics ТЗ shape (blocks of
fields, each field carrying a provenance status) but its blocks map onto the
Research Context Graph seeding (``context_init.commit``): question attributes,
the constraint context star, budgets, tools, empirical base, confirmation
criteria and the cost model.

``FRAME_SPEC`` is the single source of truth for the block set, in document
order. Each block declares HOW it seeds the graph (``kind`` + optional
``subtype``) and its field names. ``ResearchFrame.blank`` builds an all-open
frame from it, and ``ResearchFrame.normalized`` re-imposes the canonical
structure on an LLM-produced frame so the model can drift on values but never on
structure.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from CoScientist.hitl.field_status import FieldStatus, OPEN_STATUSES


# ── the canonical frame ───────────────────────────────────────────────────────
# (title, kind, subtype, usage, field_names). ``kind`` drives graph seeding:
#   question              -> attrs merged onto the root ResearchQuestion
#   constraint            -> one Constraint node (attrs.subtype = subtype)
#   resources             -> one Resource node per field
#   tools                 -> one Tool node per field
#   empirical_base        -> one EmpiricalBase node per field
#   confirmation_criteria -> one ConfirmationCriteria node
#   cost_model            -> one CostModel node (applies_to the question)
FrameSpecEntry = Tuple[str, str, Optional[str], str, Tuple[str, ...]]

FRAME_SPEC: Tuple[FrameSpecEntry, ...] = (
    ("Вопрос исследования", "question", None,
     "атрибуты корневого исследовательского вопроса",
     ("formulation", "domain", "specificity", "gap", "decomposition",
      "target_setting", "research_form", "trl")),
    ("Режим и завершение", "question", None,
     "режим применения ИИ и критерий остановки исследования",
     ("ai_application_model", "completion_criteria")),
    ("Профиль исследования", "constraint", "profile",
     "модальность и постановка — определяет активируемые модули",
     ("modality", "target_setting", "form_trl")),
    ("Методологические нормы", "constraint", "methodological_norms",
     "принятые способы проведения исследований этого типа",
     ("norms",)),
    ("Теоретические рамки", "constraint", "theoretical_framework",
     "формальные модели и теории домена",
     ("frameworks",)),
    ("Доменные стандарты", "constraint", "domain_standards",
     "ГОСТ/ISO/ICH/CLSI и требования журналов",
     ("standards",)),
    ("Этика и регуляторика", "constraint", "ethics",
     "жёсткие ограничения, которые нельзя нарушать",
     ("constraints",)),
    ("Экспертное знание", "constraint", "expert_knowledge",
     "неформализованное знание от человека в контуре",
     ("notes",)),
    ("Роли участников", "constraint", "roles",
     "состав лиц, чья деятельность автоматизируется",
     ("roles",)),
    ("Ресурсы и бюджеты", "resources", None,
     "конечные бюджеты — ограничивают критерии завершения",
     ("gpu_hours", "tokens", "money", "time", "expert_hours")),
    ("Инструменты", "tools", None,
     "известные инструменты и их статус",
     ("computational", "laboratory", "analytical", "informational")),
    ("Эмпирическая база", "empirical_base", None,
     "доступные наблюдения, данные и корпус",
     ("datasets", "corpora", "trusted_kb")),
    ("Условия подтверждения", "confirmation_criteria", None,
     "формальные условия достаточности свидетельств",
     ("threshold", "confirmations_needed", "reproducibility")),
    ("Модель стоимости", "cost_model", None,
     "правило стоимости шага и правило остановки по стоимости",
     ("cost_rule", "stop_rule")),
)

# Canonical block titles in document order.
CANONICAL_FRAME_BLOCKS: Tuple[str, ...] = tuple(e[0] for e in FRAME_SPEC)

_SPEC_BY_TITLE = {e[0]: e for e in FRAME_SPEC}


class FrameOperation(BaseModel):
    """One executable deliverable slot committed by ContextInit / HITL.

    Inventory chooses the route for this slot; the planner must not invent,
    merge, or drop it. Narrative-only report slots are omitted.
    """

    operation_id: str = Field(description="Stable id, e.g. OP-1")
    statement: str = Field(description="Deliverable copied from the ask / operator")


class FrameField(BaseModel):
    """One field of a block: |Поле|Значение|Статус|."""

    name: str = Field(description="Имя поля, напр. «formulation»")
    value: str = Field(default="Не задано", description="Значение поля")
    status: FieldStatus = Field(default="не задано")

    def is_set(self) -> bool:
        return self.status not in OPEN_STATUSES


class FrameBlock(BaseModel):
    """One block of the frame: a titled group of fields with a graph mapping."""

    title: str = Field(description="Название блока, напр. «Профиль исследования»")
    kind: str = Field(default="question", description="как блок ложится в граф")
    subtype: Optional[str] = Field(
        default=None, description="подтип Constraint, если kind == constraint")
    usage: str = Field(default="", description="как блок используется дальше")
    fields: List[FrameField] = Field(default_factory=list)

    def set_fields(self) -> List[FrameField]:
        return [f for f in self.fields if f.is_set()]


class ResearchFrame(BaseModel):
    """Структурированная рамка исследования (framing-сущности мета-модели).

    Blocks in document order, each a group of fields with a provenance status.
    The blocks seed the Research Context Graph (see ``context_init.commit``).
    """

    original_request: str = Field(
        default="", description="Исходный запрос пользователя дословно")
    operations: List[FrameOperation] = Field(
        default_factory=list,
        description="Executable slots: one non-optional plan task each",
    )
    blocks: List[FrameBlock] = Field(default_factory=list)

    @field_validator("operations", mode="before")
    @classmethod
    def coerce_operations(cls, value: Any) -> Any:
        if not value:
            return []
        if not isinstance(value, list):
            return value
        out: List[dict[str, str]] = []
        for i, item in enumerate(value, 1):
            if isinstance(item, FrameOperation):
                stmt = str(item.statement or "").strip()
                if stmt:
                    out.append({"operation_id": f"OP-{len(out) + 1}", "statement": stmt})
                continue
            if isinstance(item, str) and item.strip():
                out.append({"operation_id": f"OP-{len(out) + 1}", "statement": item.strip()})
                continue
            if isinstance(item, dict):
                stmt = str(item.get("statement") or item.get("content") or "").strip()
                if stmt:
                    out.append({"operation_id": f"OP-{len(out) + 1}", "statement": stmt})
        return out

    def block(self, title: str) -> Optional[FrameBlock]:
        for b in self.blocks:
            if b.title.strip().lower() == title.strip().lower():
                return b
        return None

    def open_fields(self) -> List[Tuple[str, str]]:
        """(block_title, field_name) for every field still needing a value."""
        out: List[Tuple[str, str]] = []
        for b in self.blocks:
            for f in b.fields:
                if not f.is_set():
                    out.append((b.title, f.name))
        return out

    @classmethod
    def blank(cls, original_request: str = "") -> "ResearchFrame":
        """An all-open frame with every canonical block and field."""
        blocks = [
            FrameBlock(
                title=title, kind=kind, subtype=subtype, usage=usage,
                fields=[FrameField(name=n) for n in field_names],
            )
            for title, kind, subtype, usage, field_names in FRAME_SPEC
        ]
        return cls(original_request=original_request, blocks=blocks)

    def normalized(self) -> "ResearchFrame":
        """Re-impose the canonical structure, keeping values/status the model set.

        The LLM may reorder blocks, rename kinds, or drop fields. This maps its
        output back onto ``FRAME_SPEC`` by title/field name so the graph mapping
        can never break, while preserving the values and statuses it produced.
        """
        blocks: List[FrameBlock] = []
        for title, kind, subtype, usage, field_names in FRAME_SPEC:
            src = self.block(title)
            src_fields = {f.name.strip().lower(): f for f in (src.fields if src else [])}
            fields = []
            for n in field_names:
                got = src_fields.get(n.strip().lower())
                if got is not None:
                    fields.append(FrameField(name=n, value=got.value, status=got.status))
                else:
                    fields.append(FrameField(name=n))
            blocks.append(FrameBlock(
                title=title, kind=kind, subtype=subtype, usage=usage, fields=fields))
        ops = [
            FrameOperation(
                operation_id=f"OP-{i}",
                statement=str(op.statement or "").strip(),
            )
            for i, op in enumerate(self.operations or [], 1)
            if str(getattr(op, "statement", "") or "").strip()
        ]
        return ResearchFrame(
            original_request=self.original_request, operations=ops, blocks=blocks,
        )


__all__ = [
    "CANONICAL_FRAME_BLOCKS",
    "FRAME_SPEC",
    "FrameBlock",
    "FrameField",
    "FrameOperation",
    "ResearchFrame",
]
