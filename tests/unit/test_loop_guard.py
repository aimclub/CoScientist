"""An agent must not be able to repeat one identical tool call forever."""
import asyncio
import types

from CoScientist.agents.loop_guard_plugin import RepeatCallGuardPlugin


def _call(guard, tool, args, agent="DatasetCollectorAgent"):
    return asyncio.run(guard.before_tool_callback(
        tool=types.SimpleNamespace(name=tool), tool_args=args,
        tool_context=types.SimpleNamespace(agent_name=agent)))


def test_identical_call_is_blocked_after_the_limit():
    guard = RepeatCallGuardPlugin()
    args = {"query": "same thing"}
    allowed = [_call(guard, "tavily_search", args) for _ in range(4)]
    blocked = _call(guard, "tavily_search", args)
    assert all(r is None for r in allowed)
    assert blocked and blocked["blocked_by"] == "repeat_call_guard"
    assert "Change approach" in blocked["message"]


def test_different_arguments_are_never_blocked():
    guard = RepeatCallGuardPlugin()
    for i in range(10):
        assert _call(guard, "tavily_search", {"query": f"q{i}"}) is None


def test_polling_the_same_job_is_exempt():
    """Waiting on a long job is the sanctioned pattern, not a loop."""
    guard = RepeatCallGuardPlugin()
    for _ in range(12):
        assert _call(guard, "check_job", {"job_id": "j1"}) is None


def test_counts_are_per_agent():
    guard = RepeatCallGuardPlugin()
    args = {"query": "x"}
    for _ in range(5):
        _call(guard, "tavily_search", args, agent="A")
    assert _call(guard, "tavily_search", args, agent="B") is None


def test_waiting_on_a_sandbox_job_is_never_mistaken_for_a_loop():
    """`check_sandbox_task` takes no arguments, so every call is identical.

    The sandbox it asks about is the one bound to the session, and the job
    behind it runs for minutes or hours. Counting those calls as thrashing cut
    the coder off from the only tool that tells it whether its own work has
    finished — after four questions, on a job that had not started answering.
    """
    guard = RepeatCallGuardPlugin()
    verdicts = [_call(guard, "check_sandbox_task", {}, agent="CoderAgent")
                for _ in range(40)]
    assert all(v is None for v in verdicts)


def test_the_refusal_names_a_tool_the_agent_could_actually_have():
    """In the sandbox setup the local coder toolset is not attached at all.

    Telling that agent to "poll it with check_job" sends it at a tool it does
    not have, which reads as a second dead end rather than a way out.
    """
    guard = RepeatCallGuardPlugin()
    args = {"command": "sleep 600"}
    for _ in range(4):
        _call(guard, "execute_bash", args, agent="CoderAgent")
    blocked = _call(guard, "execute_bash", args, agent="CoderAgent")

    assert blocked is not None
    assert "check_sandbox_task" in blocked["message"]


def test_waiting_on_the_same_mcp_build_is_exempt_too():
    """Polling one build means the same job_id every time.

    The guard's own docstring promises that repeated polling of a single job is
    allowed; `check_mcp_build` had simply never been added to the list, so the
    promise did not hold for the builds that take longest.
    """
    guard = RepeatCallGuardPlugin()
    verdicts = [_call(guard, "check_mcp_build", {"job_id": "j1"},
                      agent="McpBuilderAgent")
                for _ in range(40)]
    assert all(v is None for v in verdicts)


def test_a_lookup_that_takes_no_arguments_is_still_guarded():
    """`list_mcp_builds` recovers a lost job_id; asking twice is a loop.

    Exemption follows from what a tool is for, not from whether its arguments
    happen to be empty.
    """
    guard = RepeatCallGuardPlugin()
    for _ in range(4):
        _call(guard, "list_mcp_builds", {}, agent="McpBuilderAgent")
    assert _call(guard, "list_mcp_builds", {}, agent="McpBuilderAgent") is not None
