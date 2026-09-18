"""Domain models for the microfluidics case.

The ТЗ follows the reference document
``Пример_уточненного_структурированного_ТЗ_для_агентов.md``: a document made
of BLOCKS, where every block is a table of concrete fields and every field
carries a provenance status. The TZAgent pipeline outputs:

  TZSpecAgent      -> StructuredTZ        (state key ``structured_tz``)
  TZQueryGenAgent  -> LiteratureQueries   (state key ``tz_literature_queries``)
  LiteratureSynthesisAgent -> LiteratureAnalysis (state key ``literature_analysis``)
  MolDesignAgent   -> DesignCandidates    (state key ``design_candidates``)
  SynthRouteAgent  -> SynthesisRoutes     (state key ``synthesis_routes``)

``CoScientist.microfluidics.render.render_tz_document`` turns a validated
StructuredTZ into the human-readable Markdown document of the reference
format (interpretation rules, per-block tables, open fields, questionnaire
coverage check).

Statuses are plain string Literals (not Enum) so the dicts ADK stores in
session state — and injects into downstream prompts — render as readable
JSON-like text instead of Enum reprs.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

# Field-status vocabulary is shared with the research frame intake — one name
# for one thing. Re-exported here so existing importers keep working.
from CoScientist.hitl.field_status import FieldStatus, OPEN_STATUSES

# Canonical block set of the reference ТЗ document, in document order.
CANONICAL_BLOCKS: tuple[str, ...] = (
    "Тип задачи",
    "Целевой продукт",
    "Область применения",
    "Требуемые свойства",
    "Критерии качества",
    "Масштаб результата",
    "Ограничения по сырью",
    "Ограничения по поставкам",
    "Ограничения по себестоимости",
    "Ограничения по технологии",
    "Доступное оборудование",
    "Аналитические методы",
    "Известные данные заказчика",
    "Безопасность и регуляторика",
    "Приоритеты отбора",
    "Форма результата",
)


class TZFieldRow(BaseModel):
    """One row of a block table: |Поле|Значение|Статус|."""

    name: str = Field(description="Название поля, напр. «Минимальная чистота образца»")
    value: str = Field(default="Не задано", description="Значение поля")
    status: FieldStatus = Field(default="не задано")

    def is_set(self) -> bool:
        return self.status not in OPEN_STATUSES


class TZBlock(BaseModel):
    """One block of the ТЗ document: a titled table of concrete fields."""

    title: str = Field(description="Название блока, напр. «Критерии качества»")
    usage: str = Field(
        default="",
        description="Как блок используется дальше по пайплайну (одна фраза)",
    )
    fields: List[TZFieldRow] = Field(default_factory=list)


class StructuredTZ(BaseModel):
    """Структурированное техническое задание (кейс микрофлюидики).

    Shape mirrors the reference document: the verbatim customer request plus
    the canonical blocks, each a table of measurable fields with statuses.
    """

    original_request: str = Field(
        default="", description="Исходный свободный запрос заказчика дословно"
    )
    blocks: List[TZBlock] = Field(default_factory=list)

    def block(self, title: str) -> TZBlock | None:
        for b in self.blocks:
            if b.title.strip().lower() == title.strip().lower():
                return b
        return None


class LiteratureQuery(BaseModel):
    """Одна конкретная поисковая задача для агента анализа литературы."""

    id: str = Field(description="Идентификатор задачи, например LIT-01")
    task: str = Field(description="Формулировка задачи на русском")
    extract: List[str] = Field(
        default_factory=list, description="Какие данные нужно извлечь из источников"
    )


class LiteratureQueries(BaseModel):
    """Пакет поисковых задач, выведенных из структурированного ТЗ."""

    queries: List[LiteratureQuery] = Field(default_factory=list)


class TargetMolecule(BaseModel):
    """Целевая молекула заказчика — то, что передаётся в модуль дизайна.

    ``fixed`` = заказчик задал конкретное вещество, подбирать кандидатов не
    нужно. Когда ТЗ его задаёт, значения берутся из ТЗ, а не из литературы.
    """

    fixed: bool = Field(
        default=False, description="Задача с фиксированной молекулой (задана заказчиком)"
    )
    name: str = Field(default="", description="Название вещества")
    smiles: str = Field(default="", description="SMILES, если известен")
    cas: str = Field(default="", description="CAS, если известен")
    source: str = Field(
        default="не задано",
        description="Откуда значения: «ТЗ», «литература» или «не задано»",
    )


class NamedValue(BaseModel):
    """Свойство или условие: название, значение с единицами, условия измерения."""

    name: str = Field(description="Напр. «ККМ» или «Температура»")
    value: str = Field(description="Значение с единицами, напр. «1.2 ммоль/л»")
    conditions: str = Field(default="", description="Условия измерения, если указаны")


class Analogue(BaseModel):
    """Аналог целевого продукта, найденный в литературе."""

    name: str
    smiles: str = Field(default="", description="SMILES, если удалось установить")
    compound_class: str = Field(default="", description="Химический класс")
    properties: List[NamedValue] = Field(default_factory=list)
    relevance: str = Field(default="", description="Чем аналог полезен для ТЗ")
    sources: List[str] = Field(default_factory=list, description="Ссылки / DOI")


class RouteStep(BaseModel):
    """Одна операция маршрута синтеза.

    ``products`` и ``yield_value`` нужны для экономической оценки: сервер
    стоимости собирает маршрут по продуктам стадий и выводит расход реагентов
    обратным ходом от выхода.
    """

    operation: str
    reagents: List[str] = Field(default_factory=list)
    products: List[str] = Field(
        default_factory=list, description="Что получается на стадии (название / SMILES)"
    )
    yield_value: str = Field(
        default="", description="Выход стадии как в источнике, напр. «75 %»; пусто — не указан"
    )
    conditions: List[NamedValue] = Field(default_factory=list)


class LiteratureRoute(BaseModel):
    """Маршрут синтеза, описанный в литературе."""

    product: str = Field(description="Какое вещество получают (название / SMILES)")
    steps: List[RouteStep] = Field(default_factory=list)
    flow_suitability: str = Field(
        default="", description="Пригодность для проточного / микрофлюидного реактора"
    )
    sources: List[str] = Field(default_factory=list)


class LiteratureFact(BaseModel):
    """Факт из литературы, привязанный к поисковой задаче."""

    statement: str
    query_id: str = Field(default="", description="LIT-xx, по которой найден факт")
    sources: List[str] = Field(default_factory=list)


class LiteratureAnalysis(BaseModel):
    """Итог модуля A (ТЗ + литература) — вход модуля дизайна и отчёта."""

    target_molecule: TargetMolecule = Field(default_factory=TargetMolecule)
    analogues: List[Analogue] = Field(default_factory=list)
    synthesis_routes: List[LiteratureRoute] = Field(default_factory=list)
    facts: List[LiteratureFact] = Field(default_factory=list)
    gaps: List[str] = Field(
        default_factory=list, description="Что не удалось найти в литературе"
    )


# ── Module B hand-off: design and synthesis routes ───────────────────────────
# The shape the design system (ГПН) is expected to return, and the one the
# economics server costs: a step names its reactants, agents and products and
# carries a yield as a fraction — the fields rank_routes_by_cost chains a route by.

class Substance(BaseModel):
    """Вещество: название и, если известна, структура."""

    name: str = Field(default="", description="Название; английское, если известно")
    smiles: str = Field(default="", description="SMILES, если известен")
    amount: str = Field(
        default="",
        description="Только для растворителей и катализаторов: сколько закупать "
                    "на всю наработку, напр. «500 ml»; пусто — не учитывать",
    )


class DesignCandidate(BaseModel):
    """Кандидат на синтез (или сама целевая молекула заказчика)."""

    name: str
    smiles: str = Field(default="", description="SMILES; пусто — структура не установлена")
    compound_class: str = Field(default="", description="Химический класс")
    properties: List[NamedValue] = Field(default_factory=list)
    tz_fit: str = Field(default="", description="Какие требования ТЗ закрывает, какие нет")
    risks: str = Field(default="")
    source: str = Field(
        default="дизайн", description="Откуда кандидат: «ТЗ», «дизайн» или «литература»"
    )
    sources: List[str] = Field(default_factory=list, description="Источники литературных свойств")
    derivation: str = Field(default="", description="Происхождение структуры; не маршрут синтеза")
    stub: bool = Field(default=False, description="Данные получены от заглушки")


class DesignCandidates(BaseModel):
    """Выход стадии 3 — кого синтезировать."""

    fixed_target: bool = Field(
        default=False, description="Заказчик задал молекулу — подбора не было"
    )
    candidates: List[DesignCandidate] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list, description="Каких данных не хватает")


class ProcessStep(BaseModel):
    """Стадия маршрута в форме, которую принимает сервер стоимости."""

    operation: str
    reactants: List[Substance] = Field(
        default_factory=list,
        description="Исходные вещества стадии; продукт предыдущей стадии — name «@prev»",
    )
    agents: List[Substance] = Field(
        default_factory=list, description="Растворители, катализаторы, среды"
    )
    products: List[Substance] = Field(default_factory=list)
    conditions: List[NamedValue] = Field(default_factory=list)
    yield_fraction: Optional[float] = Field(
        default=None, gt=0, le=1, description="Выход стадии, доля 0–1; нет данных — null"
    )
    flow_notes: str = Field(
        default="", description="Как стадия переносится на проточный реактор"
    )


class SynthesisRoute(BaseModel):
    """Маршрут синтеза одного продукта."""

    route_id: str = Field(description="GPN-1, GPN-2… — ретросинтез; LIT-1… — из литературы")
    product: Substance
    source: str = Field(default="ретросинтез", description="«ретросинтез» или «литература»")
    steps: List[ProcessStep] = Field(
        min_length=1, description="Все операции маршрута по порядку; обязательное непустое поле"
    )
    flow_suitability: str = Field(default="")
    bottlenecks: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list, description="Ссылки / DOI")
    stub: bool = Field(default=False, description="Маршрут получен от заглушки")


class SynthesisRoutes(BaseModel):
    """Выход стадии 4 — как синтезировать."""

    routes: List[SynthesisRoute] = Field(
        description="Полные маршруты с операциями. Обязательное поле; [] только если маршруты не найдены."
    )
    gaps: List[str] = Field(default_factory=list)


__all__ = [
    "Analogue",
    "CANONICAL_BLOCKS",
    "DesignCandidate",
    "DesignCandidates",
    "FieldStatus",
    "LiteratureAnalysis",
    "LiteratureFact",
    "LiteratureQueries",
    "LiteratureQuery",
    "LiteratureRoute",
    "NamedValue",
    "OPEN_STATUSES",
    "ProcessStep",
    "RouteStep",
    "StructuredTZ",
    "Substance",
    "SynthesisRoute",
    "SynthesisRoutes",
    "TargetMolecule",
    "TZBlock",
    "TZFieldRow",
]
