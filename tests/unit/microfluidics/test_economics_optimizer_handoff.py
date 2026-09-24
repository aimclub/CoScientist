"""The economics → experiment hand-off (ModuleB_Design → ModuleC_Reactor).

Regression for the run where ReactorAgent got
``optimization_start → invalid_input: economics_ranking: nonempty object
required`` and then looped: the operator answered "fill every value with 1",
but nothing could store that answer. The chain under test:

1. ``collect_economics_result`` files a ``rank_routes_by_cost`` answer as
   ``economics_ranking`` (its large-answer case is in test_truncation_plugin);
2. ``prepare_inputs`` accepts a usable ranking and raises
   ``EconomicsRankingError`` — and only it — when the ranking is the one gap;
3. ``optimization_start`` then asks the operator for the route costs in a
   form, stores a contract-valid ranking and submits the task.

Offline: the A2A client and the HITL handler are fakes.
"""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from CoScientist.hitl.models import HITLAction, HITLResponse
from CoScientist.microfluidics.a2a_optimization import adapter
from CoScientist.microfluidics.a2a_optimization.contracts import (
    EconomicsRankingError,
    prepare_inputs,
    validate_economics_ranking,
)
from CoScientist.microfluidics.a2a_optimization.operator_ranking import (
    MAX_ATTEMPTS,
    PARAMS_BLOCK,
    parse_amount,
    ranking_form,
    ranking_from_form,
    route_block_title,
)
from CoScientist.microfluidics.economics import collect_economics_result
"""
ROUTE_IDS = ["LIT-ROUTE-01", "LIT-ROUTE-02", "LIT-ROUTE-03", "LIT-ROUTE-04"]
VANILLIN = "COc1cc(C=O)ccc1O"
BARBITURIC = "O=C1CC(=O)NC(=O)N1"
MALONONITRILE_DIMER = "N#CC(C#N)=C(N)CC#N"


def _route(route_id):
    return {
        "route_id": route_id, "product": {"name": "vanillin-barbituric acid adduct"},
        "overall_status": "eligible",
        "steps": [{"operation": "Knoevenagel condensation",
                   "reactants": [{"name": "vanillin"}, {"name": "barbituric acid"}],
                   "products": [{"name": "vanillin-barbituric acid adduct"}],
                   "conditions": [{"name": "Среда", "value": "water"}],
                   "yield_fraction": 0.8}],
    }


def base_state(route_ids=ROUTE_IDS):
    routes = [_route(route_id) for route_id in route_ids]
    return {
        "structured_tz": {"original_request": "phenolic antioxidant additive, 1 g"},
        "literature_analysis": {"facts": [{"statement": "fixture fact", "sources": ["fixture"]}]},
        "synthesis_routes": {"routes": routes},
        "qualified_routes": {"status": "ok", "routes": copy.deepcopy(routes)},
        "economics": "Итоговая экономика маршрута LIT-ROUTE-01 (текст агента)",
    }


def _starting(*smiles):
    return [{"smiles": s, "qty": "1.160440" if s == VANILLIN else "0.976920", "unit": "g",
             "molar_mass": "152.149" if s == VANILLIN else "128.087"} for s in smiles]


def unpriceable_answer():
    """The shape the live server gave in the failing run: the price lists do
    not index vanillin / barbituric acid by structure, so nothing is priced."""
    def unpriceable(route_id, *smiles):
        missing = [{"smiles": s, "reason": "no_match", "detail": ""} for s in smiles]
        return {
            "route_id": route_id, "status": "unpriceable", "rank": None, "currency": None,
            "cost_packs": None, "cost_per_unit": None, "starting_materials": _starting(*smiles),
            "missing": missing, "warnings": [f"оценить не удалось: {len(smiles)} позиц. не сопоставлено"],
            "estimate": {"line_items": [], "total_by_currency": {}, "missing": missing},
        }
    return {
        "preferred_currency": "RUB", "rank_by": "per_unit",
        "routes": [
            unpriceable("LIT-ROUTE-01", BARBITURIC, VANILLIN),
            unpriceable("LIT-ROUTE-02", BARBITURIC, VANILLIN),
            {"route_id": "LIT-ROUTE-03", "status": "invalid", "rank": None, "currency": None,
             "cost_packs": None, "cost_per_unit": None, "starting_materials": [], "missing": [],
             "warnings": ["шаг 1: 'GDF10': ни словарь, ни OPSIN, ни PubChem/CIR не знают такого имени"],
             "estimate": None},
            unpriceable("LIT-ROUTE-04", MALONONITRILE_DIMER, VANILLIN),
        ],
    }


def priced_answer():
    return {
        "preferred_currency": "RUB", "rank_by": "per_unit",
        "routes": [
            {"route_id": route_id, "status": "ok" if i else "partial", "rank": i + 1, "currency": "RUB",
             "cost_per_unit": f"{40 + i}.10", "cost_packs": f"{50 + i}.00",
             "starting_materials": [], "missing": [], "warnings": []}
            for i, route_id in enumerate(ROUTE_IDS)
        ],
    }


def collect(state, answer, **args):
    collect_economics_result(
        tool=SimpleNamespace(name="rank_routes_by_cost"),
        args={"target_qty": 1, "target_unit": "g", "default_yield": 0.5, **args},
        tool_context=SimpleNamespace(state=state),
        tool_response={"content": [{"type": "text", "text": json.dumps(answer)}], "isError": False},
    )
    return state


def ones(route_ids=ROUTE_IDS):
    """What the operator asked for in the run: every value = 1."""
    return {
        PARAMS_BLOCK: {"target_qty": "1", "target_unit": "g", "preferred_currency": "RUB", "rank_by": "per_unit"},
        **{route_block_title(r): {"cost_per_unit": "1", "cost_packs": "1"} for r in route_ids},
    }


def sent_inputs(client):
    return json.loads(client.send_message.call_args.kwargs["text"].split("\n\n", 1)[1])


@pytest.fixture
def client(monkeypatch):
    fake = Mock()
    fake.send_message.return_value = {"jsonrpc": "2.0", "result": {"task": {
        "id": "task-1", "status": {"state": "TASK_STATE_SUBMITTED", "message": {"parts": [{"text": "ok"}]}},
    }}}
    monkeypatch.setattr(adapter, "_client", lambda: fake)
    return fake


@pytest.fixture
def operator(monkeypatch):
    """A reachable operator who answers the queued form values in order
    (None = the form was skipped)."""
    from CoScientist.agents import common

    queue, requests = [], []

    async def handle_request(request):
        requests.append(request)
        values = queue.pop(0)
        return HITLResponse(action=HITLAction.EDIT, approved=values is not None, form_values=values)

    monkeypatch.setattr(common.hitl_handler, "handle_request", handle_request)
    monkeypatch.setattr(adapter, "_operator_reachable", lambda ctx: True)
    return SimpleNamespace(answers=queue, requests=requests)


def start(state, **kwargs):
    ctx = SimpleNamespace(state=state)
    return ctx, asyncio.run(adapter.optimization_start(ctx, **kwargs))


# ── 1. collection ───────────────────────────────────────────────────────────

def test_collected_priced_answer_is_handed_off_as_is(client):
    state = collect(base_state(), priced_answer())
    ctx, result = start(state)
    assert result["state"] == "submitted"
    sent = sent_inputs(client)["economics_ranking"]
    assert sent["routes"]["LIT-ROUTE-01"] == state["economics_ranking"]["routes"]["LIT-ROUTE-01"]
    assert sent["routes"]["LIT-ROUTE-01"]["cost_per_unit"] == "40.10"
    assert "source" not in sent  # the server's numbers, not the operator's


def test_collected_unpriceable_answer_keeps_every_route_and_reasons():
    state = collect(base_state(), unpriceable_answer())
    ranking = state["economics_ranking"]
    assert sorted(ranking["routes"]) == ROUTE_IDS
    assert ranking["target_qty"] == 1 and ranking["preferred_currency"] == "RUB"
    assert ranking["routes"]["LIT-ROUTE-03"]["status"] == "invalid"
    route = ranking["routes"]["LIT-ROUTE-01"]
    # The project's fixed vanillin price is applied, barbituric acid stays missing.
    assert route["status"] == "unpriceable"
    assert route["cost_per_unit"] == "3.48"
    assert [m["smiles"] for m in route["missing"]] == [BARBITURIC]


def test_collector_ignores_transport_errors_and_foreign_route_sets():
    state = base_state()
    collect_economics_result(tool=SimpleNamespace(name="rank_routes_by_cost"), args={},
                             tool_context=SimpleNamespace(state=state), tool_response={"error": "timeout"})
    answer = priced_answer()
    answer["routes"] = answer["routes"][:2]
    collect(state, answer)
    assert "economics_ranking" not in state


# ── 2. contract ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ranking", [
    None, {}, "", "not json", {"routes": {}},
])
def test_missing_ranking_is_an_economics_error(ranking):
    state = base_state()
    state["economics_ranking"] = ranking
    with pytest.raises(EconomicsRankingError) as err:
        prepare_inputs(state)
    assert err.value.route_ids == ROUTE_IDS


def test_unpriceable_ranking_is_an_economics_error():
    state = collect(base_state(), unpriceable_answer())
    with pytest.raises(EconomicsRankingError, match="at least one costed route"):
        prepare_inputs(state)


def test_ranking_for_other_routes_is_an_economics_error():
    state = collect(base_state(ROUTE_IDS[:2]), {**priced_answer(), "routes": priced_answer()["routes"][:2]})
    state["qualified_routes"]["routes"].append(_route("LIT-ROUTE-09"))
    state["synthesis_routes"]["routes"].append(_route("LIT-ROUTE-09"))
    with pytest.raises(EconomicsRankingError, match="LIT-ROUTE-09"):
        prepare_inputs(state)


@pytest.mark.parametrize("key", ["structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes"])
def test_other_gaps_are_not_economics_errors(key):
    state = base_state()
    del state[key]
    with pytest.raises(ValueError) as err:
        prepare_inputs(state)
    assert not isinstance(err.value, EconomicsRankingError)


def test_planning_only_never_needs_a_ranking():
    state = base_state()
    handoff = prepare_inputs(state, planning_only=True)
    assert handoff["handoff_mode"] == "screening"


# ── 3. operator form ────────────────────────────────────────────────────────

def test_form_is_prefilled_from_the_collected_ranking():
    state = collect(base_state(), unpriceable_answer())
    form = ranking_form(state, ROUTE_IDS, "no costed route")
    params = {f["name"]: f for f in form["blocks"][0]["fields"]}
    assert form["blocks"][0]["title"] == PARAMS_BLOCK
    assert params["target_qty"]["value"] == "1" and not params["target_qty"]["open"]
    assert params["preferred_currency"]["value"] == "RUB"
    assert [b["title"] for b in form["blocks"][1:]] == [route_block_title(r) for r in ROUTE_IDS]
    route = form["blocks"][1]
    assert all(f["open"] for f in route["fields"])  # unpriced: nothing to prefill
    assert "no_match" in route["usage"] and "3.48" in route["usage"]
    assert "no costed route" in form["intro"]


def test_form_prefills_server_costs_of_priced_routes():
    state = collect(base_state(), priced_answer())
    fields = {f["name"]: f for f in ranking_form(state, ROUTE_IDS, "e")["blocks"][1]["fields"]}
    assert fields["cost_per_unit"]["value"] == "40.10" and not fields["cost_per_unit"]["open"]


def test_form_without_any_ranking_asks_for_the_target_quantity():
    fields = {f["name"]: f for f in ranking_form(base_state(), ROUTE_IDS, "e")["blocks"][0]["fields"]}
    assert fields["target_qty"]["open"]
    assert fields["target_unit"]["value"] == "g"


def test_all_ones_gives_a_valid_ranking_with_unique_ranks():
    state = collect(base_state(), unpriceable_answer())
    ranking = ranking_from_form(ones(), ROUTE_IDS, state, "no costed route")
    assert [ranking["routes"][r]["rank"] for r in ROUTE_IDS] == [1, 2, 3, 4]  # ties: route order
    assert {row["status"] for row in ranking["routes"].values()} == {"ok"}
    assert {row["cost_source"] for row in ranking["routes"].values()} == {"operator"}
    assert ranking["source"] == "operator" and ranking["operator_confirmed"] is True
    assert ranking["server_ranking_error"] == "no costed route"
    # The server's findings travel with the operator's numbers.
    assert ranking["routes"]["LIT-ROUTE-01"]["server_status"] == "unpriceable"
    assert ranking["routes"]["LIT-ROUTE-01"]["missing"][0]["smiles"] == BARBITURIC
    state["economics_ranking"] = ranking
    assert prepare_inputs(state)["economics_ranking"] == json.loads(json.dumps(ranking))


def test_ranks_follow_the_chosen_cost():
    values = ones()
    for route_id, per_unit, packs in [("LIT-ROUTE-01", "30", "5"), ("LIT-ROUTE-02", "10", "50"),
                                      ("LIT-ROUTE-03", "20", "40"), ("LIT-ROUTE-04", "", "")]:
        values[route_block_title(route_id)] = {"cost_per_unit": per_unit, "cost_packs": packs}
    by_unit = ranking_from_form(values, ROUTE_IDS, base_state())
    assert {r: by_unit["routes"][r]["rank"] for r in ROUTE_IDS} == {
        "LIT-ROUTE-01": 3, "LIT-ROUTE-02": 1, "LIT-ROUTE-03": 2, "LIT-ROUTE-04": None}
    assert by_unit["routes"]["LIT-ROUTE-04"]["status"] == "unpriceable"
    values[PARAMS_BLOCK]["rank_by"] = "packs"
    by_packs = ranking_from_form(values, ROUTE_IDS, base_state())
    assert by_packs["routes"]["LIT-ROUTE-01"]["rank"] == 1


def test_unpriced_route_keeps_the_servers_invalid_status():
    state = collect(base_state(), unpriceable_answer())
    values = ones()
    values[route_block_title("LIT-ROUTE-03")] = {}
    assert ranking_from_form(values, ROUTE_IDS, state)["routes"]["LIT-ROUTE-03"]["status"] == "invalid"


def test_one_cost_fills_the_other():
    values = ones()
    values[route_block_title("LIT-ROUTE-01")] = {"cost_packs": "7"}
    row = ranking_from_form(values, ROUTE_IDS, base_state())["routes"]["LIT-ROUTE-01"]
    assert row["cost_per_unit"] == row["cost_packs"] == "7"


def test_kept_server_numbers_keep_the_server_status():
    state = collect(base_state(), priced_answer())
    values = {PARAMS_BLOCK: {}}
    for route_id in ROUTE_IDS:
        row = state["economics_ranking"]["routes"][route_id]
        values[route_block_title(route_id)] = {"cost_per_unit": row["cost_per_unit"], "cost_packs": row["cost_packs"]}
    ranking = ranking_from_form(values, ROUTE_IDS, state)
    first = ranking["routes"]["LIT-ROUTE-01"]
    assert first["status"] == "partial" and first["cost_source"] == "server"
    assert ranking["target_qty"] == 1  # empty parameters keep the server's


def test_empty_parameters_fall_back_to_defaults_and_currency_is_normalised():
    values = ones()
    values[PARAMS_BLOCK] = {"target_qty": "2,5", "preferred_currency": "rub"}
    ranking = ranking_from_form(values, ROUTE_IDS, base_state())
    assert ranking["target_qty"] == 2.5 and ranking["target_unit"] == "g"
    assert ranking["preferred_currency"] == "RUB" and ranking["rank_by"] == "per_unit"
    assert ranking["routes"]["LIT-ROUTE-01"]["currency"] == "RUB"


@pytest.mark.parametrize("raw,expected", [
    ("1", "1"), ("42.5", "42.5"), ("42,5", "42.5"), ("1 000,50", "1000.50"),
    ("1 000", "1000"), ("42 руб", "42"), ("0", "0"), (3, "3"), (2.5, "2.5"),
])
def test_amounts_accept_operator_formats(raw, expected):
    assert str(parse_amount(raw, "x")) == expected


@pytest.mark.parametrize("raw", ["", "  ", None])
def test_empty_amount_is_none(raw):
    assert parse_amount(raw, "x") is None


@pytest.mark.parametrize("raw", ["-1", "abc", "1-2", "NaN", "inf", True, "1,000.50"])
def test_bad_amounts_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_amount(raw, "x")


@pytest.mark.parametrize("mutate,match", [
    (lambda v: v.update({route_block_title(r): {} for r in ROUTE_IDS}), "хотя бы одного"),
    (lambda v: v[PARAMS_BLOCK].update(target_qty="0"), "target_qty"),
    (lambda v: v[PARAMS_BLOCK].update(target_unit="l"), "target_unit"),
    (lambda v: v[PARAMS_BLOCK].update(rank_by="cheapest"), "rank_by"),
    (lambda v: v[route_block_title("LIT-ROUTE-02")].update(cost_per_unit="-5"), "LIT-ROUTE-02"),
])
def test_unusable_answers_are_rejected(mutate, match):
    values = ones()
    mutate(values)
    with pytest.raises(ValueError, match=match):
        ranking_from_form(values, ROUTE_IDS, base_state())


def test_target_quantity_is_required_without_a_server_ranking():
    values = ones()
    values[PARAMS_BLOCK] = {}
    with pytest.raises(ValueError, match="target_qty"):
        ranking_from_form(values, ROUTE_IDS, base_state())


def test_every_built_ranking_passes_the_contract():
    state = collect(base_state(), unpriceable_answer())
    for costs in (["1", "1", "1", "1"], ["5", "", "", ""], ["", "", "", "0"], ["3", "3", "1", "2"]):
        values = ones()
        for route_id, cost in zip(ROUTE_IDS, costs):
            values[route_block_title(route_id)] = {"cost_per_unit": cost} if cost else {}
        validate_economics_ranking(ranking_from_form(values, ROUTE_IDS, state), ROUTE_IDS)


# ── 4. optimization_start ───────────────────────────────────────────────────

def test_the_failing_run_now_starts_after_the_operator_fills_ones(client, operator):
    """ModuleB left no usable ranking; the operator fills every value with 1."""
    state = collect(base_state(), unpriceable_answer())
    operator.answers.append(ones())
    ctx, result = start(state)

    assert result["state"] == "submitted"
    assert len(operator.requests) == 1
    request = operator.requests[0]
    assert request.agent_name == "ReactorAgent" and request.form["kind"] == "economics_ranking"
    assert "at least one costed route" in request.form["intro"]
    assert state["economics_ranking"]["source"] == "operator"
    sent = sent_inputs(client)
    assert sent["economics_ranking"] == state["economics_ranking"]
    assert "стоимости задал оператор" in client.send_message.call_args.kwargs["text"]
    client.send_message.assert_called_once()
    # The same task on a repeated call; no second form, no second submission.
    assert asyncio.run(adapter.optimization_start(ctx)) == result
    assert len(operator.requests) == 1
    client.send_message.assert_called_once()


def test_no_ranking_at_all_is_also_filled_by_the_operator(client, operator):
    operator.answers.append(ones())
    _, result = start(base_state())
    assert result["state"] == "submitted"
    assert "nonempty object required" in operator.requests[0].form["intro"]


def test_a_usable_ranking_never_asks_the_operator(client, operator):
    _, result = start(collect(base_state(), priced_answer()))
    assert result["state"] == "submitted"
    assert operator.requests == []


def test_other_input_gaps_never_ask_for_costs(client, operator):
    state = collect(base_state(), unpriceable_answer())
    del state["structured_tz"]
    _, result = start(state)
    assert result["state"] == "invalid_input"
    assert "economics_ranking_required" not in result
    assert operator.requests == []
    client.send_message.assert_not_called()


def test_planning_only_never_asks_for_costs(client, operator):
    _, result = start(base_state(), planning_only=True)
    assert result["state"] == "submitted"
    assert operator.requests == []


def test_skipped_form_stops_without_submitting(client, operator):
    operator.answers.append(None)
    state = collect(base_state(), unpriceable_answer())
    server_ranking = copy.deepcopy(state["economics_ranking"])
    _, result = start(state)
    assert result["state"] == "invalid_input"
    assert result["economics_ranking_required"] and result["operator_declined"]
    assert state[adapter.RESULT_KEY] == result
    assert state["economics_ranking"] == server_ranking  # nothing invented
    client.send_message.assert_not_called()


def test_bad_answer_is_asked_again_with_the_reason(client, operator):
    bad = ones()
    bad.update({route_block_title(r): {} for r in ROUTE_IDS})
    operator.answers.extend([bad, ones()])
    _, result = start(collect(base_state(), unpriceable_answer()))
    assert result["state"] == "submitted"
    assert len(operator.requests) == 2
    assert "хотя бы одного" in operator.requests[1].form["intro"]


def test_repeatedly_bad_answers_end_with_the_reason(client, operator):
    bad = ones()
    bad[PARAMS_BLOCK]["target_unit"] = "bucket"
    operator.answers.extend([bad] * MAX_ATTEMPTS)
    _, result = start(collect(base_state(), unpriceable_answer()))
    assert result["state"] == "invalid_input"
    assert result["operator_declined"] is False and "target_unit" in result["operator_error"]
    assert len(operator.requests) == MAX_ATTEMPTS
    client.send_message.assert_not_called()


def test_without_an_operator_the_gap_is_reported_not_invented(client, monkeypatch):
    monkeypatch.setattr(adapter, "_operator_reachable", lambda ctx: False)
    state = collect(base_state(), unpriceable_answer())
    _, result = start(state)
    assert result == {
        "state": "invalid_input", "error": result["error"],
        "economics_ranking_required": True, "operator_available": False,
    }
    assert "at least one costed route" in result["error"]
    assert state["economics_ranking"].get("source") is None
    client.send_message.assert_not_called()


def test_a_bare_context_is_never_treated_as_interactive():
    assert adapter._operator_reachable(SimpleNamespace(state={})) is False


# ── 5. the session does not loop on a gap it cannot close ───────────────────

def _feedback(state):
    from CoScientist.microfluidics.a2a_optimization.session_agent import OptimizationSessionAgent

    agent = OptimizationSessionAgent.model_construct()
    return agent._unfinished_feedback(SimpleNamespace(session=SimpleNamespace(state=state)))


def test_session_finishes_after_the_operator_declined(client, operator):
    operator.answers.append(None)
    state = collect(base_state(), unpriceable_answer())
    start(state)
    assert _feedback(state) is None


def test_session_still_pushes_on_other_invalid_inputs():
    feedback = _feedback({adapter.RESULT_KEY: {"state": "invalid_input", "error": "structured_tz: nonempty object required"}})
    assert feedback and "optimization_start" in feedback


def test_session_keeps_polling_a_running_task():
    assert "optimization_get_status" in _feedback({adapter.ACTIVE_KEY: {"state": "working"}})


def test_prompt_tells_the_model_the_tool_owns_the_ranking():
    from CoScientist.agents.prompts.templates import microfluidics_optimizer

    prompt = microfluidics_optimizer(SimpleNamespace(render_tools=lambda: "", render_hitl=lambda: ""))
    assert "economics_ranking_required" in prompt
    assert "САМ" in prompt
"""