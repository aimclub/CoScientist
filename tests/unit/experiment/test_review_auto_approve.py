"""Auto-approval of the experiment reviews, from the Approvals tab.

Observed 2026-09-21 on a live Heracleum run: the plan went up for review at
13:36:26 with a 300 s window, nobody answered, and at 13:41:26 the fail-closed
policy rejected it — "an experiment plan is never approved because nobody was
watching". The run then wrote its report without running a single experiment.
The only way through was an environment variable, which means restarting the
server, which the operator of a running session cannot do.

So both reviews get their own switch, each read at call time. Two properties
matter beyond "the flag works":

* the switches are per kind. Approving a plan unseen spends the run; accepting
  whatever came out of it spends the conclusions. One switch for both would
  make the cheaper choice buy the dearer one.
* they do NOT hang off the global "ask for my approval" switch. The experiment
  reviewer overrides ``_should_run_review`` and asks even when that switch is
  off, so if the UI greyed these out with it, the one way past a paused plan
  would be hidden exactly when it is needed. The last test pins that.
"""
from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from CoScientist.config import get_settings
from CoScientist.experiments import review as review_mod
from CoScientist.experiments.review import ExperimentReviewSessionAgent, _auto_approve
from CoScientist.hitl.models import HITLAction, HITLResponse
from CoScientist.hitl.session_agent import SessionAgent

from .helpers import _inventory, _plan, _task

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "CoScientist" / "web" / "static" / "js"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """The legacy one-switch override off, and the flags back as they were."""
    monkeypatch.delenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE", raising=False)
    exp = get_settings().experiments
    before = (exp.plan_auto_approve, exp.result_auto_approve,
              exp.plan_review_timeout_s, exp.result_review_timeout_s)
    exp.plan_auto_approve = False
    exp.result_auto_approve = False
    yield exp
    (exp.plan_auto_approve, exp.result_auto_approve,
     exp.plan_review_timeout_s, exp.result_review_timeout_s) = before


def _review_plan(monkeypatch, state=None):
    plan = _plan(_task("EXP-1"))
    state = state if state is not None else {}
    state.setdefault("experiment_context", {
        "experiment_run_id": plan.experiment_run_id,
        "source_request": plan.source_request,
        "available_mcp_capabilities": _inventory(),
    })
    asked = []
    monkeypatch.setattr(review_mod, "approve_plan", lambda _s: None)
    monkeypatch.setattr(review_mod, "_publish_approved_plan_to_graph", lambda *_a, **_k: None)
    agent = ExperimentReviewSessionAgent(name="Reviewer", review_kind="plan")

    # A console that records the question and answers yes. Whether it was
    # reached at all is what these tests are about.
    async def _console(request):
        asked.append(request)
        return HITLResponse(action=HITLAction.APPROVE, approved=True, instructions="")

    agent.hitl_handler = SimpleNamespace(handle_request=_console)
    ctx = SimpleNamespace(session=SimpleNamespace(state=state), invocation_id="inv-1")
    response = asyncio.run(agent._review_plan(ctx, plan.model_dump_json()))
    return response, asked, state


def test_the_plan_switch_does_not_accept_the_result_as_well(_clean_env, monkeypatch):
    _clean_env.plan_auto_approve = True
    response, asked, _ = _review_plan(monkeypatch)

    assert response.approved and not asked, "the plan was still put up for review"
    assert _auto_approve("plan") is True
    assert _auto_approve("result") is False, "one switch bought both reviews"


def test_a_plan_nobody_switched_on_is_still_put_up_for_review(_clean_env, monkeypatch):
    """The default: the operator is asked, and silence is not consent."""
    _, asked, _ = _review_plan(monkeypatch)
    assert len(asked) == 1, "the plan was approved without asking anyone"
    assert _auto_approve("plan") is False and _auto_approve("result") is False


def test_the_environment_switch_still_covers_both(_clean_env, monkeypatch):
    """`scripts/test_lanes.py` and the headless smokes set one variable and
    expect both reviews to pass; the tab must not have narrowed that."""
    monkeypatch.setenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE", "1")
    assert _auto_approve("plan") and _auto_approve("result")
    assert review_mod._approval_mode() == "headless_auto"

    monkeypatch.delenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE")
    _clean_env.result_auto_approve = True
    assert review_mod._approval_mode() == "settings_auto"


def test_the_tab_reaches_the_reviewer_without_a_restart(_clean_env):
    """What the browser POSTs has to land on the object the reviewer reads,
    and come back in the payload so the modal does not show a stale switch."""
    from CoScientist.web.app import _apply_frontend_settings, _current_settings

    _apply_frontend_settings({"experimentModule": {
        "planAutoApprove": True, "resultAutoApprove": False,
        "planReviewTimeoutS": 1800, "resultReviewTimeoutS": 900,
    }})
    assert _auto_approve("plan") is True and _auto_approve("result") is False
    assert _clean_env.plan_review_timeout_s == 1800

    echoed = _current_settings()["experimentModule"]
    assert echoed == {
        "planAutoApprove": True, "resultAutoApprove": False,
        "planReviewTimeoutS": 1800, "resultReviewTimeoutS": 900,
    }, echoed


@pytest.mark.parametrize("bad", [0, -1, "", "later", None])
def test_a_window_of_zero_does_not_become_wait_forever(_clean_env, bad):
    """`handler.py` reads a non-positive window as "no deadline", and these
    two reviews block the run while they wait. A field that fails validation
    must leave the previous window standing, not hand the run an open one."""
    from CoScientist.web.app import _apply_frontend_settings

    _clean_env.plan_review_timeout_s = 300.0
    _apply_frontend_settings({"experimentModule": {"planReviewTimeoutS": bad}})
    assert _clean_env.plan_review_timeout_s == 300.0


def test_the_experiment_review_asks_even_with_approvals_off(monkeypatch):
    """Why the two switches are not children of `general.hitlEnabled` in the
    modal: turning that off does not stop these reviews."""
    agent = ExperimentReviewSessionAgent(name="Reviewer", review_kind="plan")
    agent.hitl_handler = SimpleNamespace(handle_request=lambda req: None)
    monkeypatch.setattr(get_settings().web, "hitl_enabled", False)

    assert agent._should_run_review() is True
    # The behaviour it overrides, for contrast: every other SessionAgent stops
    # asking when the global switch is off.
    assert SessionAgent._should_run_review(agent) is False


# ── the tab itself ──────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _js_block(src: str, key: str) -> str:
    """The text of the `key: { … }` object literal, by brace counting."""
    start = src.index(f"{key}: {{")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"unbalanced braces after {key}")


def test_every_field_in_the_modal_has_a_label_and_a_home():
    """A field whose label key is missing renders its own key to the operator;
    a field whose path is not in `appSettings` is dropped by
    `mergeServerSettings`, which only copies keys it already knows — the
    switch would then read back as its default after every save."""
    modal = _read(WEB / "modals" / "settings.js")
    labels = set(re.findall(r"'settings\.f\.([A-Za-z0-9]+)\.label'",
                            _read(WEB / "i18n.js")))
    state = _read(WEB / "state.js")

    missing_label, missing_home = [], []
    for fid, path in re.findall(
            r"id: '([A-Za-z0-9]+)',\s*path: '([A-Za-z0-9.]+)'", modal):
        if fid not in labels:
            missing_label.append(fid)
        section, _, leaf = path.partition(".")
        if f"{leaf}:" not in _js_block(state, section):
            missing_home.append(path)

    assert not missing_label, f"no settings.f.<id>.label for: {missing_label}"
    assert not missing_home, f"not in appSettings: {missing_home}"


def test_the_two_experiment_switches_are_offered_in_the_approvals_tab():
    modal = _read(WEB / "modals" / "settings.js")
    approvals = modal[modal.index("id: 'approvals'"):modal.index("id: 'tools'")]
    for fid in ("experimentPlanAuto", "experimentResultAuto",
                "experimentPlanTimeout", "experimentResultTimeout"):
        assert f"id: '{fid}'" in approvals, f"{fid} is not in the Approvals tab"
    # Not parented: see test_the_experiment_review_asks_even_with_approvals_off.
    for fid in ("experimentPlanAuto", "experimentResultAuto"):
        row = approvals[approvals.index(f"id: '{fid}'"):]
        row = row[:row.index("},")]
        assert "parent:" not in row, f"{fid} was tied to the global switch"
