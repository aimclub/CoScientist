"""Отчёт не пишется о работе, которой не было.

`ResultAggregatorAgent` — терминальная стадия конвейера (`pipeline.post`), и
запускается она независимо от того, выполнилось ли что-нибудь. Пока модуль
экспериментов доходил до конца, это было незаметно. Но у него есть ветка, в
которой он останавливается тихо: обзор плана не подтверждён, `initialize_runtime`
не вызван, `skip_executor_without_runtime` пропускает исполнителя — и дальше
агрегатор как ни в чём не бывало пишет полный научный отчёт.

По сохранённым сессиям это не редкость: **5 из 8 «завершённых» прогонов на
профиле experiments не имеют ни одного узла ExperimentTask**, а три из них —
`0a31978b`, `196dd0f7`, `236c0325` — прямо показывают связку «обзор плана истёк →
задач не возникло → написан отчёт на 8–12 тысяч знаков». Для читателя такой
прогон неотличим от успешного. Это хуже зависания: зависание видно, а это нет.

Решение детерминированное, без участия модели — просить агрегатор «не выдумывать»
значило бы лечить то же тем же:

* модуль не задействовали вовсе (чисто литературное исследование) — молчим,
  отчёт законен;
* модуль задействовали, и ничего не вышло — вместо отчёта короткая справка: что
  планировалось, почему не пошло, что нажать;
* модуль задействовали, часть прошла — отчёт пишется, но в промпт кладётся
  врезка о непройденном, и промпт обязан её воспроизвести.

«Что-то вышло» считается не по задачам модуля, а шире — по свидетельствам в
графе: оркестратор мог собрать литературу сам, и терять её описание из-за того,
что встал модуль экспериментов, неправильно.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from google.genai import types

logger = logging.getLogger(__name__)

#: Ключ состояния, который промпт агрегатора читает через ADK-подстановку
#: `{report_unexecuted_note?}`.
UNEXECUTED_NOTE_KEY = "report_unexecuted_note"

#: Исходы задачи, которые считаются сделанной работой. `partial` здесь наравне с
#: `success`: частичный результат — это всё-таки измерение, о котором есть что
#: написать. Совпадает с тем, что `result_tasks_ok` считает приемлемым.
_CARRIED_OUT = frozenset({"success", "partial"})


def _module_was_engaged(state: Any) -> bool:
    """Запускался ли модуль экспериментов в этом прогоне.

    Три следа, любой из которых означает «модуль трогали»: рантайм (даже
    неутверждённый), карточка плана для обзора и сообщение о пропуске
    исполнения. Ни одного — значит исследование шло без модуля, и отчёт по нему
    ничем не скомпрометирован.
    """
    runtime = state.get("experiment_runtime")
    if isinstance(runtime, dict) and runtime:
        return True
    return bool(state.get("experiment_plan_view")
                or state.get("experiment_execution_summary"))


def _carried_out(state: Any) -> int:
    """Сколько задач эксперимента реально дали результат."""
    done = 0
    for row in state.get("experiment_task_results") or []:
        if isinstance(row, dict) and str(row.get("status") or "") in _CARRIED_OUT:
            done += 1
    return done


def _planned(state: Any) -> int:
    """Сколько задач было в утверждённом плане."""
    runtime = state.get("experiment_runtime")
    if isinstance(runtime, dict):
        order = runtime.get("task_order")
        if isinstance(order, (list, tuple)):
            return len(order)
    view = state.get("experiment_plan_view")
    if isinstance(view, dict):
        tasks = view.get("tasks")
        if isinstance(tasks, (list, tuple)):
            return len(tasks)
    return 0


def _evidence_in_graph(callback_context: Any) -> int:
    """Свидетельства, записанные в граф кем угодно.

    Это и есть страховка от того, чтобы привратник не съел литературную часть
    прогона: `ResearchAgent` пишет свидетельства напрямую, без модуля.
    """
    try:
        from CoScientist.config import get_settings

        if not get_settings().research_graph.enabled:
            return 0
        from CoScientist.graph.research.store import get_research_graph

        nodes = get_research_graph(callback_context).overview().get("nodes") or []
        return sum(1 for n in nodes
                   if isinstance(n, dict) and n.get("type") == "Evidence")
    except Exception as exc:  # noqa: BLE001 — привратник не ломает прогон
        logger.warning("отчёт: граф недоступен, свидетельства не сочтены: %s", exc)
        return 0


def _why(state: Any) -> str:
    """Почему исполнение не состоялось, словами самой системы.

    Пустая строка, когда причины нет: фаза «execution» ничего не останавливала,
    и называть её причиной остановки значило бы придумать событие. Прогон, где
    часть задач просто не дошла очередь, — это не прогон, который встал.
    """
    said = str(state.get("experiment_execution_summary") or "").strip()
    if said:
        return said
    pause = str(state.get("experiment_review_pause_reason") or "").strip()
    runtime = state.get("experiment_runtime")
    phase = str(runtime.get("phase") or "") if isinstance(runtime, dict) else ""
    if pause and phase:
        return f"{pause} (phase={phase})"
    if pause:
        return pause
    return f"phase={phase}" if phase and phase != "execution" else ""


_INSTEAD_OF_A_REPORT = {
    "ru": (
        "## Отчёт не составлен: эксперимент не выполнялся\n\n"
        "План был подготовлен, но исполнение не состоялось, поэтому писать "
        "научный отчёт не о чем — любой текст здесь был бы описанием работы, "
        "которой не было.\n\n"
        "- **Задач в плане:** {planned}\n"
        "- **Выполнено:** 0\n"
        "- **Свидетельств в графе:** 0\n"
        "- **Причина остановки:** {why}\n\n"
        "Чтобы продолжить: подтвердите план эксперимента на карточке обзора и "
        "запустите прогон заново. Сам план сохранён в графе исследования."
    ),
    "en": (
        "## No report: the experiment was never executed\n\n"
        "A plan was prepared but execution never happened, so there is nothing "
        "to write a scientific report about — any text here would describe work "
        "that was not done.\n\n"
        "- **Tasks planned:** {planned}\n"
        "- **Carried out:** 0\n"
        "- **Evidence in the graph:** 0\n"
        "- **Why it stopped:** {why}\n\n"
        "To continue: approve the experiment plan on its review card and start "
        "the run again. The plan itself is kept in the research graph."
    ),
}

_PARTIAL_NOTE = {
    "ru": (
        "ВНИМАНИЕ — ПЛАН ВЫПОЛНЕН НЕ ПОЛНОСТЬЮ. Отчёт обязан открываться "
        "предупреждением об этом и не должен описывать результаты задач, "
        "которые не выполнялись.\n"
        "Задач в плане: {planned}. Выполнено: {done}.{why}"
    ),
    "en": (
        "WARNING — THE PLAN WAS NOT CARRIED OUT IN FULL. The report must open "
        "with a statement saying so, and must not describe results of tasks "
        "that never ran.\n"
        "Tasks planned: {planned}. Carried out: {done}.{why}"
    ),
}

#: Причина дописывается только когда она есть — см. `_why`. Прогон, где до части
#: задач просто не дошла очередь, ничем не «останавливался».
_WHY_TAIL = {"ru": " Причина остановки: {why}.", "en": " Why it stopped: {why}."}


def _language(state: Any) -> str:
    try:
        from CoScientist.agents.callbacks.report_language import (
            session_report_language,
        )

        return "ru" if str(session_report_language(state)).lower().startswith("ru") else "en"
    except Exception:  # noqa: BLE001
        return "ru"


def guard_report_without_execution(callback_context: Any) -> types.Content | None:
    """before_agent на агрегаторе: не дать написать отчёт о невыполненной работе.

    Возврат `Content` замыкает агента — тот же приём, которым
    `skip_executor_without_runtime` останавливает исполнителя без утверждённого
    плана. Ошибка внутри самого привратника не должна стоить прогону отчёта,
    поэтому всё обёрнуто: не смогли посчитать — пропускаем.
    """
    try:
        state = callback_context.state
        if not _module_was_engaged(state):
            return None

        done, planned = _carried_out(state), _planned(state)
        evidence = _evidence_in_graph(callback_context)
        lang, why = _language(state), _why(state)

        if done or evidence:
            # Что-то сделано. Отчёт законен, но обязан сказать, чего в нём нет.
            if planned and done < planned:
                tail = _WHY_TAIL[lang].format(why=why) if why else ""
                state[UNEXECUTED_NOTE_KEY] = _PARTIAL_NOTE[lang].format(
                    planned=planned, done=done, why=tail)
            else:
                state[UNEXECUTED_NOTE_KEY] = ""
            return None

        # Ничего. Ни результата задачи, ни свидетельства — писать не о чем.
        state[UNEXECUTED_NOTE_KEY] = ""
        logger.warning(
            "REPORT_WITHOUT_EXECUTION_REFUSED planned=%d done=0 evidence=0 why=%s",
            planned, why)
        unknown = "не записано" if lang == "ru" else "not recorded"
        return types.Content(
            role="model",
            parts=[types.Part(text=_INSTEAD_OF_A_REPORT[lang].format(
                planned=planned or unknown, why=why or unknown))],
        )
    except Exception as exc:  # noqa: BLE001 — привратник не ломает прогон
        logger.warning("проверка отчёта на пустое исполнение не выполнена: %s", exc)
        return None


__all__ = ["UNEXECUTED_NOTE_KEY", "guard_report_without_execution"]
