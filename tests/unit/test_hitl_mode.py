"""Три режима подтверждений — и отказ, который наконец останавливает модуль.

До этого «спрашивать или нет» и «сколько ждать» решались в четырёх местах
независимо, и решения расходились: 34 из 45 истёкших карточек в сохранённых
сессиях закончились автоматическим «одобрено», причём уровень `side_effect` —
самый опасный — был единственным с обратным отсчётом, а `read` и `compute`
ждали человека вечно. Предсказать поведение по настройкам было нельзя.

Отдельно — отказ от плана эксперимента. «Отклонить» и «Доработать» уходили в
один и тот же `_feed_back`, потому что ни одна из двух ветвей не ставила
`stop_review_loop`, и планировщик просто писал план заново. Сказать «прекрати»
было нечем: только «попробуй ещё раз».

Run from the repo root:  pytest tests/unit/test_hitl_mode.py -q
"""
import asyncio

import pytest
from dotenv import load_dotenv

load_dotenv()

from CoScientist.hitl import mode as mode_mod  # noqa: E402
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse  # noqa: E402


@pytest.fixture(autouse=True)
def _no_inherited_mode(monkeypatch):
    """Каждый тест называет режим сам: `.env` стенда не должен решать за него."""
    monkeypatch.delenv("HITL__MODE", raising=False)


# ── сами режимы ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("named,expected,wait", [
    ("auto", mode_mod.AUTO, 0.0),
    ("basic", mode_mod.BASIC, mode_mod.BASIC_WAIT_S),
    ("debug", mode_mod.DEBUG, None),
    ("AUTO", mode_mod.AUTO, 0.0),
    ("  basic  ", mode_mod.BASIC, mode_mod.BASIC_WAIT_S),
])
def test_the_named_mode_decides_the_wait(monkeypatch, named, expected, wait):
    monkeypatch.setenv("HITL__MODE", named)
    assert mode_mod.hitl_mode() == expected
    assert mode_mod.wait_seconds() == wait


def test_the_basic_wait_is_ten_minutes():
    assert mode_mod.BASIC_WAIT_S == 600.0


def test_silence_approves_in_no_mode():
    """Главное правило. Прогону, который должен идти без человека, назван
    отдельный режим — и он называется вслух, а не выводится из того, что никто
    не смотрел."""
    for named in mode_mod.MODES:
        assert mode_mod.silence_approves() is False, named


def test_a_misspelled_mode_falls_back_to_asking(monkeypatch):
    """Опечатка в настройке не должна молча включать автоподтверждение."""
    monkeypatch.setenv("HITL__MODE", "atuo")
    assert mode_mod.hitl_mode() == mode_mod.BASIC
    assert mode_mod.auto_approves() is False


# ── совместимость со стендами, настроенными до появления ручки ───────────────

def test_hitl_switched_off_reads_as_auto(monkeypatch):
    from CoScientist.config import get_settings

    monkeypatch.setattr(get_settings().web, "hitl_enabled", False)
    monkeypatch.setattr(get_settings().web, "hitl_mode", "")
    assert mode_mod.hitl_mode() == mode_mod.AUTO


def test_a_non_positive_legacy_timeout_reads_as_debug(monkeypatch):
    """`HITL_AUTO_APPROVE_TIMEOUT=-1` дословно означает «ждать сколько
    угодно» — это и есть debug, и стенд с такой настройкой не должен менять
    поведение от того, что появился режим."""
    from CoScientist.config import get_settings

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    monkeypatch.setattr(get_settings().web, "hitl_mode", "")
    monkeypatch.setattr(get_settings().web, "hitl_auto_approve_timeout", -1)
    assert mode_mod.hitl_mode() == mode_mod.DEBUG

    monkeypatch.setattr(get_settings().web, "hitl_auto_approve_timeout", 300)
    assert mode_mod.hitl_mode() == mode_mod.BASIC


# ── что видит обработчик ─────────────────────────────────────────────────────

def _ask(agent="CoderAgent", **kw):
    from CoScientist.web.handler import WebHITLHandler

    handler = WebHITLHandler()
    request = HITLRequest(agent_name=agent, action_type=HITLAction.APPROVE,
                          message="Approve", **kw)
    return handler, asyncio.run(handler.handle_request(request))


def test_auto_draws_no_card_and_answers_yes(monkeypatch):
    monkeypatch.setenv("HITL__MODE", "auto")
    handler, answer = _ask(timeout_seconds=600)
    assert answer.approved is True and answer.timed_out is False
    assert not handler._pending, "карточка не должна попадать в очередь ожидания"


def test_basic_refuses_when_nobody_answers(monkeypatch):
    monkeypatch.setenv("HITL__MODE", "basic")
    _, answer = _ask(timeout_seconds=0.001)
    assert answer.approved is False
    assert answer.timed_out is True, "и об этом сказано прямо"


def test_the_refusal_says_that_nobody_answered(monkeypatch):
    """`timed_out` без слов ниже по течению читается как решение человека."""
    monkeypatch.setenv("HITL__MODE", "basic")
    _, answer = _ask(timeout_seconds=0.001)
    assert "answer" in (answer.instructions or "").lower()


def test_the_handlers_window_speaks_the_modes_wait(monkeypatch):
    from CoScientist.web.handler import WebHITLHandler

    monkeypatch.setenv("HITL__MODE", "basic")
    assert WebHITLHandler().hitl_timeout_seconds == 600.0
    monkeypatch.setenv("HITL__MODE", "debug")
    # Вызывающие читают «<= 0» как «срока нет» — это их словарь.
    assert WebHITLHandler().hitl_timeout_seconds <= 0


# ── отказ от плана эксперимента ──────────────────────────────────────────────

def _response(action, **kw):
    return HITLResponse(action=action, approved=kw.pop("approved", False), **kw)


def test_a_rejection_is_told_apart_from_a_revision():
    from CoScientist.experiments.review import _is_refusal

    assert _is_refusal(_response(HITLAction.REJECT)) is True
    # «Доработать» приходит как EDIT — это просьба переписать, не отказ.
    assert _is_refusal(_response(HITLAction.EDIT, instructions="добавь контроль")) is False
    # Отказ С заметкой — всё равно отказ: заметка это причина, а не «ещё раз».
    assert _is_refusal(_response(HITLAction.REJECT, instructions="цель не та")) is True
    # Утверждение — не отказ ни в каком виде.
    assert _is_refusal(_response(HITLAction.APPROVE, approved=True)) is False


def test_a_timeout_is_not_the_operator_refusing():
    """Молчание теперь приходит как `reject`, но никто ничего не решал — у него
    своя ветка и своя причина паузы."""
    from CoScientist.experiments.review import _is_refusal

    assert _is_refusal(_response(HITLAction.REJECT, timed_out=True)) is False
    assert _is_refusal(_response(HITLAction.REJECT, stop_review_loop=True)) is False


def test_the_review_loop_stops_on_a_rejection_and_not_on_a_revision():
    """`SessionAgent` кормит обратно всё, что не утверждено, — значит «стоп»
    выражается единственным флагом, и обзор плана его не ставил."""
    import inspect

    from CoScientist.experiments.review import ExperimentReviewSessionAgent
    from CoScientist.hitl.session_agent import SessionAgent

    body = inspect.getsource(ExperimentReviewSessionAgent._review_plan)
    assert "_is_refusal(response)" in body
    assert 'stop_review_loop": True' in body
    assert "plan_rejected_by_operator" in body
    # И флаг действительно прекращает цикл.
    loop = inspect.getsource(SessionAgent._run_async_impl)
    assert "response.timed_out or response.stop_review_loop" in loop


def test_a_positive_answer_approves_even_with_notes():
    """У карточки плана есть отдельная кнопка «Доработать», поэтому сокращение
    «утвердил с заметкой = переписать» было чистым вредом: оператор жал
    «Утвердить», писал уточнение, и только что утверждённый план выбрасывался."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "CoScientist" / "web" / "static"
          / "js" / "hitl.js").read_text(encoding="utf-8")
    assert "function respondHITLApprove(requestId)" in js
    approve = js.split("function respondHITLApprove(requestId)")[1].split("\n}")[0]
    assert "action: 'approve'" in approve and "approved: true" in approve
    # Карточка плана эксперимента зовёт именно её, а не сокращение.
    assert "respondHITLApprove('${escJs(rid)}')" in js
