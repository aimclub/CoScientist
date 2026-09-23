"""Техническое задание по ГОСТ 19.201-78, собранное из подтверждённой рамки.

Рамка описывает ПОСТАНОВКУ: вопрос, ограничения, бюджеты, инструменты,
критерии. ТЗ — это документ, который читает человек и по которому работу
принимают, поэтому у него другой набор разделов, заданный п. 1.4 стандарта:

    введение · основания для разработки · назначение разработки · требования к
    программе или программному изделию · требования к программной документации ·
    технико-экономические показатели · стадии и этапы разработки · порядок
    контроля и приёмки

Стандарт разрешает прямо: «в зависимости от особенностей программы или
программного изделия допускается уточнять содержание разделов, вводить новые
разделы или объединять отдельные из них» (п. 1.4). Этим и пользуемся —
исследование не программное изделие, и подразделы про маркировку, упаковку,
транспортирование и хранение (2.4.6, 2.4.7) к нему не применимы. Они не
выбрасываются молча: документ говорит, что они объединены и почему.

Сборка ДЕТЕРМИНИРОВАННАЯ. Каждый раздел собирается из полей рамки по
фиксированному правилу, и ничего сверх них не появляется: пустое поле даёт
«Не задано», а не правдоподобный текст. Связную прозу дописывает отдельный
проход модели (`tz_prose`), и ему на вход идут уже собранные значения — он
может переформулировать, но не может ввести факт, которого в рамке нет.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from CoScientist.context_init.models import ResearchFrame
from CoScientist.context_init.operations import OPS_FORM_BLOCK  # noqa: F401

#: Что печатается вместо значения, которого нет. Одна строка на весь документ —
#: читатель должен узнавать её с первого раза и не гадать, пусто ли это поле или
#: его забыли заполнить.
NOT_SET = "Не задано"

#: Заголовки разделов — дословно по п. 1.4 и п. 2 ГОСТ 19.201-78, кроме
#: четвёртого: «требования к программе или программному изделию» применительно к
#: исследованию названы тем, чем они являются. Стандарт это разрешает, а
#: заголовок «требования к программному изделию» над разделом о достоверности
#: измерений сбивал бы с толку сильнее, чем отступление от буквы.
SECTION_TITLES: Tuple[Tuple[str, str], ...] = (
    ("1", "Введение"),
    ("2", "Основания для разработки"),
    ("3", "Назначение разработки"),
    ("4", "Требования к результату исследования"),
    ("5", "Требования к отчётной документации"),
    ("6", "Технико-экономические показатели"),
    ("7", "Стадии и этапы разработки"),
    ("8", "Порядок контроля и приёмки"),
)

#: Подразделы четвёртого раздела. Номера сохранены от п. 2.4 стандарта, чтобы
#: соответствие читалось без сверки; 4.6 — то, во что объединены 2.4.6-2.4.8.
SUBSECTION_TITLES: Tuple[Tuple[str, str], ...] = (
    ("4.1", "Требования к составу выполняемых работ"),
    ("4.2", "Требования к достоверности результата"),
    ("4.3", "Условия проведения"),
    ("4.4", "Требования к составу и параметрам технических средств"),
    ("4.5", "Требования к исходным данным и совместимости"),
    ("4.6", "Специальные требования"),
)


class TZSection(BaseModel):
    """Один раздел ТЗ: номер, заголовок, текст и вложенные подразделы."""

    number: str = Field(description="Номер раздела по ГОСТ, напр. «4» или «4.1»")
    title: str = Field(description="Заголовок раздела")
    body: str = Field(default="", description="Текст раздела")
    rows: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Табличная часть: (что, значение). Пусто — таблицы нет.")
    subsections: List["TZSection"] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return (not self.rows and not self.subsections
                and self.body.strip() in ("", NOT_SET))


class TechnicalSpec(BaseModel):
    """Техническое задание целиком — то, из чего рендерятся .docx и .md."""

    topic: str = Field(default="", description="Наименование темы")
    customer: str = Field(default="", description="Заказчик")
    basis: str = Field(default="", description="Основание для работы")
    original_request: str = Field(
        default="", description="Исходный запрос пользователя дословно")
    sections: List[TZSection] = Field(default_factory=list)

    def section(self, number: str) -> Optional[TZSection]:
        for s in self.sections:
            if s.number == number:
                return s
        return None

    def unfilled(self) -> List[str]:
        """Номера разделов, которым рамка ничего не дала.

        Документ всё равно выпускается: «не задано» — это честный результат
        опроса, и оператор видит по нему, что дозаполнить.
        """
        out: List[str] = []
        for s in self.sections:
            for part in [s] + list(s.subsections):
                if part.is_empty():
                    out.append(part.number)
        return out


TZSection.model_rebuild()


# ── чтение рамки ────────────────────────────────────────────────────────────

def _fields(frame: ResearchFrame, title: str) -> Dict[str, str]:
    """Заполненные поля блока по его заголовку: {имя: значение}."""
    for b in frame.blocks:
        if b.title == title:
            return {f.name: f.value.strip() for f in b.set_fields()
                    if f.value and f.value.strip()}
    return {}


def _value(frame: ResearchFrame, title: str, name: str) -> str:
    return _fields(frame, title).get(name, "")


def _rows(frame: ResearchFrame, title: str,
          labels: Dict[str, str]) -> List[Tuple[str, str]]:
    """Табличная часть раздела: подпись поля и его значение, в порядке `labels`.

    Подписи берутся не из имён полей: «gpu_hours» в документе, который пойдёт
    заказчику, — это не название строки.
    """
    have = _fields(frame, title)
    return [(labels[name], have[name]) for name in labels if name in have]


def _joined(frame: ResearchFrame, titles: List[str]) -> str:
    """Тексты нескольких блоков подряд, каждый со своим заголовком.

    Для разделов, которые стандарт держит одним, а рамка разносит по нескольким
    блокам, — 4.6 собирает этику, стандарты, нормы и теоретические рамки.
    """
    parts: List[str] = []
    for title in titles:
        have = _fields(frame, title)
        said = "; ".join(v for v in have.values() if v)
        if said:
            parts.append(f"{title}: {said}.")
    return "\n".join(parts)


# ── сборка ──────────────────────────────────────────────────────────────────

_RESOURCE_LABELS = {
    "gpu_hours": "GPU-часы", "tokens": "Токены LLM", "money": "Денежный бюджет",
    "time": "Календарное время", "expert_hours": "Часы эксперта",
}
_TOOL_LABELS = {
    "computational": "Вычислительные", "laboratory": "Лабораторные",
    "analytical": "Аналитические", "informational": "Информационные",
}
_BASE_LABELS = {
    "datasets": "Наборы данных", "corpora": "Корпуса",
    "trusted_kb": "Доверенные базы знаний",
}
_CRITERIA_LABELS = {
    "threshold": "Порог подтверждения",
    "confirmations_needed": "Число подтверждений",
    "reproducibility": "Воспроизводимость",
}
_COST_LABELS = {
    "cost_rule": "Правило стоимости шага", "stop_rule": "Правило остановки",
    "expected_effect": "Ожидаемый эффект",
}


def spec_from_frame(frame: ResearchFrame,
                    original_request: str = "") -> TechnicalSpec:
    """Собрать ТЗ из подтверждённой рамки. Ничего не выдумывает."""
    frame = frame.normalized()
    q = _fields(frame, "Вопрос исследования")
    mode = _fields(frame, "Режим и завершение")
    basis = _fields(frame, "Основание и приёмка")

    def text(*parts: str) -> str:
        said = [p.strip() for p in parts if p and p.strip()]
        return " ".join(said) if said else NOT_SET

    intro = text(
        q.get("formulation", ""),
        f"Область применения: {q['domain']}." if q.get("domain") else "",
        f"Постановка: {q['target_setting']}." if q.get("target_setting") else "",
    )

    purpose = text(
        f"Функциональное назначение: получить ответ на вопрос исследования "
        f"средствами мультиагентной системы CoScientist."
        if q.get("formulation") else "",
        f"Закрываемый пробел в знаниях: {q['gap']}." if q.get("gap") else "",
        f"Режим применения ИИ: {mode['ai_application_model']}."
        if mode.get("ai_application_model") else "",
        f"Форма исследования: {q['research_form']}." if q.get("research_form") else "",
        f"Уровень готовности технологии: {q['trl']}." if q.get("trl") else "",
    )

    tasks = [(t.operation_id, t.statement) for t in frame.operations if t.statement]
    work = TZSection(
        number="4.1", title=SUBSECTION_TITLES[0][1],
        body=(q.get("decomposition") or "").strip() or NOT_SET,
        rows=[(f"Задача {i}", statement) for i, (_id, statement)
              in enumerate(tasks, 1)],
    )

    sections = [
        TZSection(number="1", title=SECTION_TITLES[0][1], body=intro),
        TZSection(
            number="2", title=SECTION_TITLES[1][1],
            body=NOT_SET if not basis else "",
            rows=[(label, basis[name]) for name, label in (
                ("basis_document", "Документ-основание"),
                ("customer", "Заказчик"),
                ("topic_name", "Наименование темы"),
            ) if basis.get(name)],
        ),
        TZSection(number="3", title=SECTION_TITLES[2][1], body=purpose),
        TZSection(
            number="4", title=SECTION_TITLES[3][1],
            body=("Раздел «Требования к программе или программному изделию» "
                  "ГОСТ 19.201-78, применённый к исследованию. Подразделы "
                  "2.4.6-2.4.8 стандарта (маркировка, упаковка, "
                  "транспортирование и хранение) к результату исследования не "
                  "применимы и объединены в 4.6 — п. 1.4 стандарта это "
                  "допускает."),
            subsections=[
                work,
                TZSection(number="4.2", title=SUBSECTION_TITLES[1][1],
                          rows=_rows(frame, "Условия подтверждения", _CRITERIA_LABELS),
                          body="" if _fields(frame, "Условия подтверждения") else NOT_SET),
                TZSection(number="4.3", title=SUBSECTION_TITLES[2][1],
                          rows=_rows(frame, "Ресурсы и бюджеты", _RESOURCE_LABELS),
                          body=_joined(frame, ["Роли участников"]) or NOT_SET),
                TZSection(number="4.4", title=SUBSECTION_TITLES[3][1],
                          rows=_rows(frame, "Инструменты", _TOOL_LABELS),
                          body="" if _fields(frame, "Инструменты") else NOT_SET),
                TZSection(number="4.5", title=SUBSECTION_TITLES[4][1],
                          rows=_rows(frame, "Эмпирическая база", _BASE_LABELS),
                          body="" if _fields(frame, "Эмпирическая база") else NOT_SET),
                TZSection(number="4.6", title=SUBSECTION_TITLES[5][1],
                          body=_joined(frame, [
                              "Этика и регуляторика", "Доменные стандарты",
                              "Методологические нормы", "Теоретические рамки",
                          ]) or NOT_SET),
            ],
        ),
        TZSection(number="5", title=SECTION_TITLES[4][1],
                  body=basis.get("deliverables") or NOT_SET),
        TZSection(number="6", title=SECTION_TITLES[5][1],
                  rows=_rows(frame, "Модель стоимости", _COST_LABELS),
                  body="" if _fields(frame, "Модель стоимости") else NOT_SET),
        TZSection(number="7", title=SECTION_TITLES[6][1],
                  body=basis.get("stages") or NOT_SET),
        TZSection(
            number="8", title=SECTION_TITLES[7][1],
            body=text(
                basis.get("acceptance", ""),
                f"Критерий завершения исследования: {mode['completion_criteria']}."
                if mode.get("completion_criteria") else "",
            ),
        ),
    ]

    return TechnicalSpec(
        topic=basis.get("topic_name") or q.get("formulation", "")[:200] or NOT_SET,
        customer=basis.get("customer") or NOT_SET,
        basis=basis.get("basis_document") or NOT_SET,
        original_request=(original_request or "").strip(),
        sections=sections,
    )


# ── проза от модели ─────────────────────────────────────────────────────────

def prose_request(spec: TechnicalSpec) -> Dict[str, Any]:
    """Что отдать модели, чтобы она дописала связный текст.

    Отдаются уже собранные значения, а не рамка: модель переформулирует то, что
    есть, и ей нечего добавить от себя. Разделы с таблицами не отдаются вовсе —
    там переписывать нечего, а перечисление, пересказанное прозой, теряет числа.
    """
    return {
        "тема": spec.topic,
        "исходный_запрос": spec.original_request[:2000],
        "разделы": [
            {"номер": s.number, "заголовок": s.title, "текст": s.body}
            for s in spec.sections if s.body and s.body != NOT_SET and not s.rows
        ],
    }


def apply_prose(spec: TechnicalSpec, prose: Dict[str, str]) -> TechnicalSpec:
    """Наложить переписанные абзацы на собранное ТЗ.

    Раздел принимает новый текст, только если он у него уже был: модель может
    улучшить формулировку, но не заполнить пустой раздел — иначе «Не задано»
    превратится в правдоподобный вымысел, а именно от этого документ и
    защищаем.
    """
    for section in spec.sections:
        said = str(prose.get(section.number) or "").strip()
        if said and section.body and section.body != NOT_SET:
            section.body = said
    return spec


__all__ = [
    "NOT_SET",
    "SECTION_TITLES",
    "SUBSECTION_TITLES",
    "TZSection",
    "TechnicalSpec",
    "apply_prose",
    "prose_request",
    "spec_from_frame",
]
