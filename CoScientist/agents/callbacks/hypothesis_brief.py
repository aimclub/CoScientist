"""Что известно про инструменты к моменту, когда выдвигаются гипотезы.

Генератор гипотез просят судить, «насколько гипотеза проверяема имеющимися
инструментами», но инвентаря он не видит: тулов поиска у него нет, а срез графа
показывает узлы Tool одной строкой без описания. Между тем к этому моменту
инвентарь обычно уже собран — планировщик и ретривер MCP отработали раньше и
положили его в состояние сессии.

Этот колбэк берёт то, что там лежит, и превращает в одну короткую вводную:

* инструменты под задачу есть — формулируй гипотезу так, чтобы именно они её и
  подтверждали: измеримый исход, который эти инструменты дают напрямую;
* инструментов нет — проверка будет стоить перебора и разработки, поэтому
  вложись в ОЦЕНКУ: сравни кандидатов по разрешающей силе и объясни выбор.

Вводная детерминирована: она пересказывает инвентарь, а не додумывает его. Если
инвентаря нет вовсе, колбэк молчит — пустая строка лучше, чем утверждение о
средствах, которых никто не считал.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

#: Ключ состояния, который читает промпт через ADK-подстановку {hypothesis_brief?}.
BRIEF_STATE_KEY = "hypothesis_brief"

#: Сколько имён инструментов показать. Список нужен, чтобы гипотеза
#: формулировалась под конкретный измеряемый исход, а не «под инструменты
#: вообще»; но полтора десятка имён — это уже не вводная, а шум.
_SHOW = 8


def _rows(state: Any) -> List[Dict[str, Any]]:
    """Инвентарь инструментов сессии, если модуль экспериментов его собрал."""
    try:
        from CoScientist.experiments.runtime.shared import session_inventory_rows

        rows = session_inventory_rows(state)
    except Exception as exc:  # noqa: BLE001 — профиль без EM это норма
        logger.debug("гипотезы: инвентарь недоступен (%s)", exc)
        return []
    return [r for r in (rows or []) if isinstance(r, dict)]


def _names(rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for row in rows:
        name = str(row.get("tool") or row.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


#: По этим ключам видно, что поиск инструментов УЖЕ состоялся. Разница важна:
#: «искали и не нашли» и «ещё не искали» — это разные указания агенту, а пустой
#: инвентарь выглядит одинаково в обоих случаях.
_SEARCH_MARKERS = (
    "retrieval_queries",                    # retrieve_tools отработал
    "executor_tool_match",                  # реранкер вынес вердикт
    "experiment_retrieved_capabilities",
    "experiment_discovered_capabilities",
    "filtered_tools",
)


def _rejected_all(state: Any) -> bool:
    """Реранкер судил кандидатов и не оставил ни одного.

    Важно именно это, а не пустота инвентаря: `accumulated_tools` и
    `experiment_retrieved_capabilities` переживают отбор и продолжают
    перечислять кандидатов, которых реранкер только что отверг. Прочитанные как
    «вот чем это можно измерить», они уводят гипотезу к инструменту, который
    никто не собирается запускать.
    """
    getter = getattr(state, "get", None)
    if not callable(getter):
        return False
    try:
        from CoScientist.agents.callbacks.tool_callbacks import UNJUDGED_REASONS

        verdict = getter("executor_tool_match") or {}
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(verdict, dict) or not verdict:
        return False
    # Вердикта не было (разбор упал, ранжирование пустое) — это не отказ.
    if verdict.get("reason") in UNJUDGED_REASONS:
        return False
    return not verdict.get("matched")


def _searched(state: Any) -> bool:
    getter = getattr(state, "get", None)
    if not callable(getter):
        return False
    for key in _SEARCH_MARKERS:
        try:
            if getter(key):
                return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _compose(names: List[str], searched: bool = True) -> Tuple[str, str]:
    """Текст вводной и короткая метка режима для лога."""
    if names:
        shown = ", ".join(names[:_SHOW])
        more = f" (+{len(names) - _SHOW} more)" if len(names) > _SHOW else ""
        # «the inventory holds», а не «retrieved for this task»: инвентарь живёт
        # в сессии и мог быть собран под предыдущий запрос. Указать на него
        # честно можно, выдать за поиск именно под эту задачу — нет.
        return (
            "### WHAT THIS RUN CAN ALREADY MEASURE\n"
            f"The tool inventory of this session holds {len(names)} ready "
            f"tools: {shown}{more}.\n"
            "The study can therefore be settled by RUNNING them — so formulate "
            "the hypothesis as the claim these tools come closest to settling: "
            "its outcome must be a number (or a named check) that one of them "
            "produces directly, and its ConfirmationCriteria must threshold "
            "exactly that output. Do not propose a claim whose measurement "
            "none of them yields; do not invent a tool when one of these "
            "already answers the question.",
            f"tools:{len(names)}",
        )
    judging = (
        "So spend the effort on JUDGING the candidates before you commit: write "
        "out the alternatives you considered, compare them by how sharply a "
        "single run could separate them and by how much the answer would change "
        "what happens next, drop those that no single measurement can decide, "
        "and state in the rationale why the one you commit survived. A claim "
        "that cannot be measured at all is not a hypothesis here, however "
        "interesting."
    )
    if searched:
        return (
            "### NO READY TOOL HAS BEEN FOUND FOR THIS TASK\n"
            "The inventory was searched and nothing in it measures this outcome, "
            "so verifying whatever you propose will cost a search, an adaptation "
            "or new code — an expensive branch, and the wrong claim is expensive "
            "twice.\n" + judging,
            "tools:none",
        )
    return (
        "### THE TOOL INVENTORY HAS NOT BEEN TAKEN YET\n"
        "Nothing has looked for instruments for this task, so assume neither "
        "that they exist nor that they do not. What follows from that: name the "
        "MEASUREMENT your hypothesis needs — the quantity, its unit, the data it "
        "is taken on — because that name is what the planner will search for, "
        "and a claim whose measurement is unnamed cannot be equipped at all.\n"
        + judging,
        "tools:unknown",
    )


def brief_hypotheses_regime(callback_context) -> None:
    """before_agent: положить вводную о режиме туда, откуда её читает промпт.

    Промпт рендерится один раз при сборке дерева, а инвентарь свой у каждой
    сессии — поэтому вводная едет через состояние и подстановку
    `{hypothesis_brief?}`.
    """
    try:
        state = callback_context.state
        names = [] if _rejected_all(state) else _names(_rows(state))
        text, mode = _compose(names, _searched(state))
        state[BRIEF_STATE_KEY] = text
        logger.info("гипотезы: режим %s", mode)
    except Exception as exc:  # noqa: BLE001 — без вводной агент просто работает как раньше
        logger.warning("гипотезы: вводная не собрана (%s)", exc)
        try:
            callback_context.state[BRIEF_STATE_KEY] = ""
        except Exception:  # noqa: BLE001
            pass
    return None


__all__ = ["BRIEF_STATE_KEY", "brief_hypotheses_regime"]
