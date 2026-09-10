"""Section-by-section assembly of the structured ТЗ — the TZSpecAgent's tools.

TZSpecAgent does not answer with the whole ТЗ in one JSON any more. It fills
the document ONE SECTION PER TOOL CALL, strictly in the order of
``CANONICAL_BLOCKS``:

    fill_tz_section("Тип задачи", …)       -> ok, 1/16, next: «Целевой продукт»
    fill_tz_section("Целевой продукт", …)  -> ok, 2/16, next: «Область применения»
    …
    fill_tz_section("Форма результата", …) -> complete, 16/16

Every answer states the progress and names the NEXT section together with its
recommended fields, so the model always knows where it is. A rejected call
saves nothing and says exactly what is wrong: the step, the section, the
field's number and name, the offending value and what is allowed instead.

State:
  ``structured_tz``        the ТЗ itself (a ``StructuredTZ`` dump), rewritten
                           by every accepted section — downstream readers and
                           the review see the same shape the one-shot JSON had;
  ``structured_tz_build``  which invocation the edition belongs to. A new
                           invocation, or a cleared marker (the session agent
                           clears it when a reviewer asks for a rewrite),
                           starts a new edition from section 1.

After the operator's review (a web form, see ``tz_review.py``) the fields the
operator left EMPTY go to the agent: ``fill_agent_fields`` fills them the same
way — one section per call, in order, with the progress and the next section in
every answer — and marks them «заполнено агентом» so the UI can highlight them
for the next review round. ``structured_tz_agent_fill`` holds what is left.

``edit_tz_section`` rewrites ONE section of an already assembled ТЗ. It is
registered (``edit_tz_section`` in assembly/bindings.py) but deliberately not
attached to any agent yet.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple, get_args

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

from CoScientist.hitl.field_status import AGENT_FILLED_STATUS
from CoScientist.microfluidics.models import (
    CANONICAL_BLOCKS,
    FieldStatus,
    OPEN_STATUSES,
    StructuredTZ,
    TZBlock,
    TZFieldRow,
)

logger = logging.getLogger(__name__)

TZ_STATE_KEY = "structured_tz"
TZ_BUILD_STATE_KEY = "structured_tz_build"
AGENT_FILL_STATE_KEY = "structured_tz_agent_fill"
FILL_TOOL_NAME = "fill_tz_section"
AGENT_FILL_TOOL_NAME = "fill_agent_fields"

TOTAL_SECTIONS = len(CANONICAL_BLOCKS)
# What the model may put in a field. «заполнено агентом» is not among them:
# only fill_agent_fields sets it, for fields the operator handed over.
ALLOWED_STATUSES: tuple[str, ...] = tuple(
    s for s in get_args(FieldStatus) if s != AGENT_FILLED_STATUS
)
_FIELD_KEYS = ("name", "value", "status")
# Values that mean "nothing here" — not acceptable under a status that claims one.
_EMPTY_VALUES = {"", "-", "—", "не задано", "не задан", "не задана", "нет данных"}

# Recommended fields per section: shown in the prompt for the whole document
# and repeated in every tool answer for the section that comes next.
SECTION_GUIDE: dict[str, str] = {
    "Тип задачи": (
        "тип задачи; целевой объект; задача с фиксированной молекулой (да/нет); "
        "допускается подбор молекул-кандидатов; допускается подбор структурных "
        "аналогов; требуется оценка маршрутов синтеза; требуется экономическая "
        "оценка; требуется план экспериментальной проверки; требуется наработка "
        "образца."
    ),
    "Целевой продукт": (
        "функция продукта; конкретное целевое вещество; CAS; SMILES; торговый "
        "аналог; предпочтительный структурный класс; обязательные и желательные "
        "структурные признаки; возможность предложить новую структуру."
    ),
    "Область применения": (
        "область применения; рабочая среда; требуется совместимость со средой; "
        "модельная среда для первичной проверки."
    ),
    "Требуемые свойства": (
        "каждое свойство отдельным полем, при возможности — отдельные поля для "
        "метода оценки, численного значения и условий проверки (например: IFT "
        "нефть/вода; ККМ (CMC); солеустойчивость; термостабильность; "
        "стабильность эмульсии; антиокислительная активность)."
    ),
    "Критерии качества": (
        "минимальная чистота образца; минимальная масса образца; подтверждение "
        "структуры; подтверждение чистоты; допустимые примеси."
    ),
    "Масштаб результата": (
        "масштаб текущего результата; минимальная масса образца; масштаб "
        "следующей проверки; перспективный производственный масштаб; требуется "
        "ли оценка масштабируемости."
    ),
    "Ограничения по сырью": (
        "разрешённые исходные вещества; минимальная чистота реагентов и "
        "растворителей; желательные вещества; запрещённые заказчиком вещества; "
        "базовый список исключений; допустимые растворители."
    ),
    "Ограничения по поставкам": (
        "география поиска поставщиков; максимальный срок поставки; минимальное "
        "число независимых поставщиков; максимальная минимальная партия "
        "закупки; наличие цены."
    ),
    "Ограничения по себестоимости": (
        "предельная себестоимость; требуется ли расчёт себестоимости по сырью; "
        "единица расчёта; требуется ли сравнение маршрутов."
    ),
    "Ограничения по технологии": (
        "предпочтительная схема проверки (проточная/микрофлюидная установка); "
        "допустимое и предпочтительное число стадий; минимальный литературный "
        "выход ключевой стадии; осадки; газовыделение; экзотермические стадии; "
        "коррозионные реагенты; требования к промывке."
    ),
    "Доступное оборудование": (
        "тип установки; диапазон расходов; рабочее давление; диапазон "
        "температур; число каналов; работа с инертным газом; материалы "
        "контактирующих частей."
    ),
    "Аналитические методы": (
        "каждый метод отдельным полем, значение = назначение (ЯМР; ВЭЖХ; ГХ; "
        "ГХ-МС; ИК; ТСХ; тензиометрия; ККМ по проводимости; ...)."
    ),
    "Известные данные заказчика": (
        "статьи; патенты; внутренние отчёты; методики; данные о неудачных опытах."
    ),
    "Безопасность и регуляторика": (
        "ограничения заказчика; списки запрещённых веществ; базовое правило "
        "безопасности; оценка токсичности/пожароопасности."
    ),
    "Приоритеты отбора": (
        "ранжированный список — name = порядковый номер («1», «2», …), "
        "value = критерий."
    ),
    "Форма результата": (
        "основной результат этапа; дополнительные результаты; итоговый формат "
        "(отчёт, таблицы, списки кандидатов и условий)."
    ),
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _norm(text: Any) -> str:
    return " ".join(str(text).split()).lower()


def is_empty_value(value: Any) -> bool:
    """True for a value that says nothing («», «—», «Не задано», …)."""
    return value is None or _norm(value) in _EMPTY_VALUES


def _canonical_index(title: str) -> Optional[int]:
    wanted = _norm(title)
    for i, canonical in enumerate(CANONICAL_BLOCKS):
        if _norm(canonical) == wanted:
            return i
    return None


def _section_ref(index: int) -> str:
    """«раздел 4 «Требуемые свойства»» — 0-based index to the reader's numbering."""
    return f"раздел {index + 1} «{CANONICAL_BLOCKS[index]}»"


def load_tz(value: Any) -> Optional[StructuredTZ]:
    """The ТЗ held in state as a model, or None when absent or unreadable."""
    if value is None or value == "":
        return None
    if isinstance(value, StructuredTZ):
        return value
    try:
        if isinstance(value, str):
            return StructuredTZ.model_validate_json(value)
        return StructuredTZ.model_validate(value)
    except Exception:  # noqa: BLE001 — an unreadable ТЗ is treated as absent
        return None


def _edition(state: Any, invocation_id: str) -> Optional[StructuredTZ]:
    """The ТЗ being assembled in THIS invocation's current edition, if any."""
    build = state.get(TZ_BUILD_STATE_KEY)
    if not isinstance(build, dict) or build.get("invocation_id") != invocation_id:
        return None
    return load_tz(state.get(TZ_STATE_KEY))


def _request_text(tool_context: Any) -> str:
    """The customer's request verbatim — the user turn this invocation answers."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(p, "text", None) or "" for p in parts).strip()


def _batch_position(tool_context: Any) -> Tuple[int, int]:
    """(position, count) of this call among the fill_tz_section calls made in
    the same model response. (0, 1) when that cannot be told."""
    call_id = getattr(tool_context, "function_call_id", None)
    session = getattr(tool_context, "session", None)
    if not call_id or session is None:
        return 0, 1
    # The model response is appended to the session before its calls execute.
    for event in reversed(list(getattr(session, "events", None) or [])[-5:]):
        try:
            calls = event.get_function_calls()
        except Exception:  # noqa: BLE001
            continue
        ids = [c.id for c in calls if c.name == FILL_TOOL_NAME]
        if call_id in ids:
            return ids.index(call_id), len(ids)
    return 0, 1


def validate_section_fields(
    fields: Any, *, where: str
) -> Tuple[List[TZFieldRow], List[str]]:
    """Check one section table; return its rows and the errors, each prefixed
    with ``where`` (the step and the section) and naming the field it is about."""
    errors: List[str] = []
    rows: List[TZFieldRow] = []

    if not isinstance(fields, list) or not fields:
        errors.append(
            f"{where}: список fields пуст — в разделе должно быть хотя бы одно "
            "поле (поля без значения передавайте со статусом «не задано»)."
        )
        return rows, errors

    seen: dict[str, int] = {}
    for num, raw in enumerate(fields, 1):
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            errors.append(
                f"{where}, поле №{num}: ожидался объект с ключами name, value, "
                f"status, а получено {type(raw).__name__} ({str(raw)[:80]!r})."
            )
            continue

        name = str(raw.get("name") or "").strip()
        label = f"{where}, поле №{num}" + (f" «{name}»" if name else "")
        field_errors: List[str] = []

        extra = sorted(str(k) for k in raw if k not in _FIELD_KEYS)
        if extra:
            field_errors.append(
                f"{label}: лишние ключи {', '.join(extra)} — у поля есть только "
                "name, value, status."
            )
        if not name:
            field_errors.append(f"{label}: не указано имя поля (name).")
        elif _norm(name) in seen:
            field_errors.append(
                f"{label}: имя повторяет поле №{seen[_norm(name)]} — имена полей "
                "внутри раздела не должны повторяться."
            )
        else:
            seen[_norm(name)] = num

        value = raw.get("value")
        if isinstance(value, (dict, list)):
            field_errors.append(
                f"{label}: value должно быть строкой, а передан "
                f"{type(value).__name__} — перечисления записывайте одной строкой."
            )
            value = ""
        value = "" if value is None else str(value).strip()

        status = str(raw.get("status") or "не задано").strip()
        normalized = next((s for s in ALLOWED_STATUSES if _norm(s) == _norm(status)), None)
        if normalized is None:
            field_errors.append(
                f"{label}: недопустимый статус «{status}»; допустимо одно из: "
                + ", ".join(f"«{s}»" for s in ALLOWED_STATUSES) + "."
            )
        elif normalized not in OPEN_STATUSES and _norm(value) in _EMPTY_VALUES:
            field_errors.append(
                f"{label}: статус «{normalized}» означает, что значение известно, "
                f"но value {'пустое' if not value else f'«{value}»'} — укажите "
                "конкретное значение или поставьте статус «не задано»."
            )

        if field_errors:
            errors.extend(field_errors)
            continue
        rows.append(TZFieldRow(name=name, value=value or "Не задано", status=normalized))
    return rows, errors


def unfinished_feedback(state: Any, invocation_id: str) -> Optional[str]:
    """Feedback for an agent that ended its turn before the ТЗ was complete
    (None when it is complete): where it stopped and which section is next."""
    tz = _edition(state, invocation_id)
    filled = len(tz.blocks) if tz is not None else 0
    if filled >= TOTAL_SECTIONS:
        return None
    if filled == 0:
        return (
            f"Вы завершили ход, не сохранив ни одного раздела ТЗ (0/{TOTAL_SECTIONS}). "
            f"ТЗ заполняется только через {FILL_TOOL_NAME} — по одному разделу за "
            f"вызов. Начните с раздела 1 «{CANONICAL_BLOCKS[0]}»."
        )
    return (
        f"Вы завершили ход, заполнив только {filled}/{TOTAL_SECTIONS} разделов ТЗ — "
        f"ТЗ не собрано. Продолжайте: теперь вы должны заполнить "
        f"{_section_ref(filled)} (вызов {FILL_TOOL_NAME}). Уже сохранённые "
        "разделы повторять не нужно."
    )


def _rejected(step: int, filled: int, errors: List[str], hint: str = "") -> dict:
    expected = CANONICAL_BLOCKS[step - 1]
    message = (
        f"Раздел НЕ сохранён (ошибок: {len(errors)}). Исправьте ошибки и повторите "
        f"вызов {FILL_TOOL_NAME} для раздела {step} «{expected}». "
        f"Заполнено по-прежнему {filled}/{TOTAL_SECTIONS}."
    )
    if hint:
        message += " " + hint
    logger.info("fill_tz_section rejected at step %d/%d: %s", step, TOTAL_SECTIONS, errors)
    return {
        "status": "error",
        "step": f"{step}/{TOTAL_SECTIONS}",
        "expected_section": expected,
        "errors": errors,
        "message": message,
    }


# ── tools ────────────────────────────────────────────────────────────────────

def fill_tz_section(
    section: str,
    usage: str,
    fields: list[TZFieldRow],
    tool_context: ToolContext,
) -> dict:
    """Save the NEXT section of the structured ТЗ — one section per call, in order.

    Args:
        section: title of the section being filled — exactly the section the
            previous answer named as next (the first call: «Тип задачи»).
        usage: one phrase — how this section is used further down the pipeline.
        fields: the rows of the section table, each
            {"name": ..., "value": ..., "status": ...}; status is one of
            «задано заказчиком», «уточнено оператором», «не задано»,
            «свободный комментарий», «рассчитывается агентом».

    Returns:
        status "ok" with the progress (k/N) and the section to fill next;
        "complete" once the last section is saved; "error" naming the exact
        step, section and field that were rejected — nothing is saved then.
    """
    state = tool_context.state
    invocation_id = tool_context.invocation_id
    tz = _edition(state, invocation_id)
    filled = len(tz.blocks) if tz is not None else 0

    if filled >= TOTAL_SECTIONS:
        return {
            "status": "error",
            "step": f"{TOTAL_SECTIONS}/{TOTAL_SECTIONS}",
            "errors": [
                f"ТЗ уже собрано полностью ({TOTAL_SECTIONS}/{TOTAL_SECTIONS}) — "
                f"раздел «{section}» не сохранён."
            ],
            "message": (
                f"Больше вызывать {FILL_TOOL_NAME} не нужно: ответьте одной "
                "короткой фразой, что ТЗ собрано."
            ),
        }

    step = filled + 1
    expected = CANONICAL_BLOCKS[filled]
    # A marker cleared to None (not merely absent or from another invocation)
    # = a reviewer asked for a rewrite of the ТЗ still in state.
    hint = ""
    if (
        TZ_BUILD_STATE_KEY in state
        and state.get(TZ_BUILD_STATE_KEY) is None
        and load_tz(state.get(TZ_STATE_KEY)) is not None
    ):
        hint = (
            "После правок ревью ТЗ собирается заново — с раздела 1, со всеми "
            "разделами по порядку."
        )

    position, batch = _batch_position(tool_context)
    if position > 0:
        # Only the first call of the batch runs; what is next depends on it.
        return {
            "status": "error",
            "errors": [
                f"В одном ответе вызвано {batch} {FILL_TOOL_NAME}, а разделы "
                f"заполняются по одному: выполняется только первый вызов, этот "
                f"(вызов №{position + 1}, раздел «{section}») отклонён и не сохранён."
            ],
            "message": (
                "Смотрите ответ на первый вызов — он называет раздел, который "
                "нужно заполнить следующим. Делайте один вызов за ответ."
            ),
        }

    index = _canonical_index(section)
    if index is None:
        return _rejected(step, filled, [
            f"Шаг {step}/{TOTAL_SECTIONS}: раздела «{section}» нет в структуре ТЗ. "
            f"Сейчас нужно заполнить {_section_ref(filled)} — передайте в section "
            "именно это название."
        ], hint)
    if index < filled:
        return _rejected(step, filled, [
            f"Шаг {step}/{TOTAL_SECTIONS}: {_section_ref(index)} уже сохранён на шаге "
            f"{index + 1}/{TOTAL_SECTIONS}, повторно его заполнять нельзя. Сейчас "
            f"нужно заполнить {_section_ref(filled)}."
        ], hint)
    if index > filled:
        return _rejected(step, filled, [
            f"Шаг {step}/{TOTAL_SECTIONS}: передан {_section_ref(index)}, но разделы "
            f"заполняются строго по порядку — сейчас нужно заполнить "
            f"{_section_ref(filled)}."
        ], hint)

    where = f"Шаг {step}/{TOTAL_SECTIONS}, раздел «{expected}»"
    rows, errors = validate_section_fields(fields, where=where)
    if not str(usage or "").strip():
        errors.insert(0, (
            f"{where}: не указан usage — одна фраза о том, как раздел "
            "используется дальше по пайплайну."
        ))
    if errors:
        return _rejected(step, filled, errors, hint)

    if tz is None:  # the first section opens a new edition
        tz = StructuredTZ(original_request=_request_text(tool_context))
    tz.blocks.append(TZBlock(title=expected, usage=str(usage).strip(), fields=rows))
    state[TZ_STATE_KEY] = tz.model_dump()
    state[TZ_BUILD_STATE_KEY] = {"invocation_id": invocation_id}
    filled += 1

    open_count = sum(1 for r in rows if r.status in OPEN_STATUSES)
    saved = f"раздел «{expected}» сохранён (полей: {len(rows)}, из них открытых: {open_count})"
    logger.info("fill_tz_section: %d/%d — %s", filled, TOTAL_SECTIONS, saved)

    if filled == TOTAL_SECTIONS:
        return {
            "status": "complete",
            "progress": f"{filled}/{TOTAL_SECTIONS}",
            "message": (
                f"Вы заполнили {filled}/{TOTAL_SECTIONS}: {saved}. Все разделы ТЗ "
                "заполнены — ТЗ собрано. Ответьте одной короткой фразой, что ТЗ "
                f"готово; {FILL_TOOL_NAME} больше не вызывайте."
            ),
        }

    next_section = CANONICAL_BLOCKS[filled]
    return {
        "status": "ok",
        "progress": f"{filled}/{TOTAL_SECTIONS}",
        "message": (
            f"Вы заполнили {filled}/{TOTAL_SECTIONS}: {saved}. Продолжайте — "
            f"теперь вы должны заполнить {_section_ref(filled)}."
        ),
        "next_section": next_section,
        "next_section_fields": SECTION_GUIDE[next_section],
    }


def edit_tz_section(
    section: str,
    fields: list[TZFieldRow],
    tool_context: ToolContext,
    usage: str = "",
) -> dict:
    """Rewrite ONE section of the already assembled ТЗ; the others stay as they are.

    Args:
        section: title of an existing section of the ТЗ.
        fields: the complete new table of the section — it REPLACES the old
            rows; each row is {"name": ..., "value": ..., "status": ...}.
        usage: new usage phrase; leave empty to keep the current one.

    Returns:
        status "ok" with what changed, or "error" naming the exact field that
        was rejected — nothing is saved then.
    """
    state = tool_context.state
    tz = load_tz(state.get(TZ_STATE_KEY))
    if tz is None or not tz.blocks:
        return {
            "status": "error",
            "errors": ["ТЗ ещё не создано — редактировать нечего."],
            "message": "Сначала ТЗ должно быть собрано через fill_tz_section.",
        }

    wanted = _norm(section)
    index = next((i for i, b in enumerate(tz.blocks) if _norm(b.title) == wanted), None)
    if index is None:
        existing = ", ".join(f"«{b.title}»" for b in tz.blocks)
        return {
            "status": "error",
            "errors": [f"Раздела «{section}» нет в ТЗ. Есть разделы: {existing}."],
            "message": "Ничего не изменено. Передайте в section название существующего раздела.",
        }

    block = tz.blocks[index]
    rows, errors = validate_section_fields(
        fields, where=f"Редактирование, раздел «{block.title}»"
    )
    if errors:
        return {
            "status": "error",
            "section": block.title,
            "errors": errors,
            "message": (
                f"Раздел «{block.title}» НЕ изменён (ошибок: {len(errors)}). "
                "Исправьте ошибки и повторите вызов."
            ),
        }

    before = len(block.fields)
    new_usage = str(usage or "").strip() or block.usage
    tz.blocks[index] = TZBlock(title=block.title, usage=new_usage, fields=rows)
    state[TZ_STATE_KEY] = tz.model_dump()
    logger.info("edit_tz_section: «%s» rewritten (%d -> %d fields)", block.title, before, len(rows))
    return {
        "status": "ok",
        "section": block.title,
        "message": (
            f"Раздел «{block.title}» обновлён: полей было {before}, стало "
            f"{len(rows)}. Остальные разделы не изменены."
        ),
    }


# ── fields the operator left to the agent ────────────────────────────────────

class AgentFieldValue(BaseModel):
    """One value the agent supplies for a field the operator left empty."""

    name: str = Field(description="Имя поля — ровно как в запросе на дозаполнение")
    value: str = Field(description="Конкретное рабочее значение")


def agent_fill_request(
    invocation_id: str, pending: List[Tuple[str, List[str]]]
) -> Optional[dict]:
    """State value asking the agent to fill ``pending`` [(section, [fields])];
    None when there is nothing to fill."""
    pending = [(s, list(f)) for s, f in pending if f]
    if not pending:
        return None
    return {
        "invocation_id": invocation_id,
        "total": len(pending),
        "pending": [{"section": s, "fields": f} for s, f in pending],
    }


def agent_fill_pending(state: Any, invocation_id: str) -> Optional[dict]:
    """This invocation's unfinished request to fill operator-left fields."""
    request = state.get(AGENT_FILL_STATE_KEY)
    if (
        not isinstance(request, dict)
        or request.get("invocation_id") != invocation_id
        or not request.get("pending")
    ):
        return None
    return request


def _fill_target(request: dict) -> Tuple[int, int, str, List[str]]:
    """(step, total, section, fields) of the next section to fill."""
    total = int(request.get("total") or len(request["pending"]))
    head = request["pending"][0]
    return total - len(request["pending"]) + 1, total, head["section"], list(head["fields"])


def _names(fields: List[str]) -> str:
    return ", ".join(f"«{f}»" for f in fields)


def agent_fill_instruction(request: dict) -> str:
    """Where the agent stands in the fill request and what to fill next."""
    step, total, section, fields = _fill_target(request)
    return (
        f"Теперь вы должны заполнить раздел {step} из {total} — «{section}», "
        f"поля: {_names(fields)} (вызов {AGENT_FILL_TOOL_NAME})."
    )


def agent_fill_feedback(state: Any, invocation_id: str) -> Optional[str]:
    """Feedback for an agent that ended its turn with operator-left fields
    still empty (None when there are none)."""
    request = agent_fill_pending(state, invocation_id)
    if request is None:
        return None
    step, total, _section, _fields = _fill_target(request)
    return (
        f"Вы завершили ход, дозаполнив только {step - 1}/{total} разделов с "
        "полями, которые оператор оставил вам. Продолжайте. "
        + agent_fill_instruction(request)
    )


def fill_agent_fields(
    section: str,
    fields: list[AgentFieldValue],
    tool_context: ToolContext,
) -> dict:
    """Fill the fields the operator left EMPTY in ONE section — the next one named.

    Args:
        section: title of the section the previous answer (or the request)
            named as next.
        fields: a value for every field of that section left to you, each
            {"name": ..., "value": ...}; the status is set automatically
            («заполнено агентом»), other fields of the ТЗ cannot be changed.

    Returns:
        status "ok" with the progress (k/K) and the section to fill next;
        "complete" once every field left to you is filled; "error" naming the
        exact step, section and field that were rejected — nothing is saved then.
    """
    state = tool_context.state
    request = agent_fill_pending(state, tool_context.invocation_id)
    if request is None:
        return {
            "status": "error",
            "errors": ["Нет полей, которые оператор оставил заполнить агенту."],
            "message": f"Вызывать {AGENT_FILL_TOOL_NAME} сейчас не нужно.",
        }

    step, total, expected, wanted = _fill_target(request)
    where = f"Шаг {step}/{total}, раздел «{expected}»"

    def rejected(errors: List[str]) -> dict:
        logger.info("fill_agent_fields rejected at step %d/%d: %s", step, total, errors)
        return {
            "status": "error",
            "step": f"{step}/{total}",
            "expected_section": expected,
            "expected_fields": wanted,
            "errors": errors,
            "message": (
                f"Ничего не сохранено (ошибок: {len(errors)}). Исправьте ошибки и "
                f"повторите вызов {AGENT_FILL_TOOL_NAME} для раздела «{expected}», "
                f"поля: {_names(wanted)}. Дозаполнено по-прежнему {step - 1}/{total}."
            ),
        }

    if _norm(section) != _norm(expected):
        return rejected([
            f"Шаг {step}/{total}: передан раздел «{section}», а сейчас нужно "
            f"заполнить раздел «{expected}» — разделы идут строго по порядку."
        ])

    errors: List[str] = []
    values: dict[str, str] = {}
    wanted_by_norm = {_norm(n): n for n in wanted}
    if not isinstance(fields, list) or not fields:
        errors.append(f"{where}: список fields пуст — нужны значения полей {_names(wanted)}.")
        fields = []
    for num, raw in enumerate(fields, 1):
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            errors.append(
                f"{where}, поле №{num}: ожидался объект с ключами name, value, а "
                f"получено {type(raw).__name__} ({str(raw)[:80]!r})."
            )
            continue
        name = str(raw.get("name") or "").strip()
        label = f"{where}, поле №{num}" + (f" «{name}»" if name else "")
        extra = sorted(str(k) for k in raw if k not in ("name", "value"))
        if extra:
            errors.append(
                f"{label}: лишние ключи {', '.join(extra)} — передаются только name и "
                "value, статус ставится автоматически."
            )
            continue
        if not name:
            errors.append(f"{label}: не указано имя поля (name).")
            continue
        canonical = wanted_by_norm.get(_norm(name))
        if canonical is None:
            errors.append(
                f"{label}: этого поля нет среди оставленных вам ({_names(wanted)}) — "
                "остальные поля ТЗ менять нельзя."
            )
            continue
        if canonical in values:
            errors.append(f"{label}: поле передано повторно.")
            continue
        value = raw.get("value")
        if isinstance(value, (dict, list)) or is_empty_value(value):
            errors.append(
                f"{label}: пустое или неконкретное значение "
                f"{str(value)[:40]!r} — оператор оставил это поле, чтобы его заполнили "
                "вы: укажите конкретное рабочее значение одной строкой."
            )
            continue
        values[canonical] = str(value).strip()
    missing = [n for n in wanted if n not in values]
    if missing and not errors:
        errors.append(f"{where}: не заполнены поля {_names(missing)}.")
    elif missing:
        errors.append(f"{where}: без значения остались поля {_names(missing)}.")
    if errors:
        return rejected(errors)

    tz = load_tz(state.get(TZ_STATE_KEY))
    block = tz.block(expected) if tz is not None else None
    rows = {f.name: f for f in block.fields} if block is not None else {}
    lost = [n for n in values if n not in rows]
    if lost:
        return rejected([f"{where}: в ТЗ нет полей {_names(lost)} — ТЗ изменилось."])
    for name, value in values.items():
        rows[name].value = value
        rows[name].status = AGENT_FILLED_STATUS

    remaining = [dict(p) for p in request["pending"][1:]]
    state[TZ_STATE_KEY] = tz.model_dump()
    state[AGENT_FILL_STATE_KEY] = dict(request, pending=remaining)
    logger.info("fill_agent_fields: %d/%d — «%s» (%d field(s))", step, total, expected, len(values))

    saved = f"раздел «{expected}» дозаполнен (полей: {len(values)})"
    if not remaining:
        return {
            "status": "complete",
            "progress": f"{total}/{total}",
            "message": (
                f"Вы дозаполнили {total}/{total}: {saved}. Все поля, оставленные "
                "оператором, заполнены — ТЗ снова уйдёт оператору на проверку. "
                f"Ответьте одной короткой фразой; {AGENT_FILL_TOOL_NAME} больше не вызывайте."
            ),
        }
    nxt = state[AGENT_FILL_STATE_KEY]
    return {
        "status": "ok",
        "progress": f"{step}/{total}",
        "message": f"Вы дозаполнили {step}/{total}: {saved}. Продолжайте. "
                   + agent_fill_instruction(nxt),
        "next_section": nxt["pending"][0]["section"],
        "next_fields": list(nxt["pending"][0]["fields"]),
    }


__all__ = [
    "AGENT_FILL_STATE_KEY",
    "AGENT_FILL_TOOL_NAME",
    "ALLOWED_STATUSES",
    "AgentFieldValue",
    "FILL_TOOL_NAME",
    "agent_fill_feedback",
    "agent_fill_instruction",
    "agent_fill_pending",
    "agent_fill_request",
    "fill_agent_fields",
    "is_empty_value",
    "SECTION_GUIDE",
    "TOTAL_SECTIONS",
    "TZ_BUILD_STATE_KEY",
    "TZ_STATE_KEY",
    "edit_tz_section",
    "fill_tz_section",
    "load_tz",
    "unfinished_feedback",
    "validate_section_fields",
]
