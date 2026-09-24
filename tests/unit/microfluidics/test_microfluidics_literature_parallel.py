from types import SimpleNamespace

from CoScientist.microfluidics.literature import collect_literature_finding


def _context(request: str, result: str, state=None):
    state = {} if state is None else state
    state["search_results"] = result
    return SimpleNamespace(
        state=state,
        user_content=SimpleNamespace(parts=[SimpleNamespace(text=request)]),
    )


def test_findings_use_distinct_state_keys_for_parallel_merge():
    first = _context("LIT-01 find surfactants", "answer one")
    second = _context("LIT-02 find synthesis routes", "answer two")

    collect_literature_finding(first)
    collect_literature_finding(second)

    # These are the independent deltas ADK can safely merge after concurrent
    # AgentTool calls.  Neither result depends on reading the other's list.
    assert first.state["literature_finding_LIT_01"]["result"] == "answer one"
    assert second.state["literature_finding_LIT_02"]["result"] == "answer two"


def test_sequential_compatibility_list_is_still_accumulated():
    state = {}
    collect_literature_finding(_context("LIT-01 first", "one", state))
    collect_literature_finding(_context("LIT-02 second", "two", state))

    assert [item["query_id"] for item in state["literature_findings"]] == [
        "LIT-01",
        "LIT-02",
    ]
