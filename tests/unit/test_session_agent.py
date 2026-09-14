"""Regression tests for the planner's durable fallback plan."""

from types import SimpleNamespace

from google.genai import types

from CoScientist.hitl.session_agent import SessionAgent


def test_planner_fallback_plan_uses_the_current_request():
    """A skipped create_plan call still has a valid executor assignment."""
    ctx = SimpleNamespace(
        user_content=types.Content(
            role="user", parts=[types.Part(text="Find a catalyst")]
        )
    )

    plan = SessionAgent._fallback_plan(ctx)

    assert plan[0]["assignee"] == "ResearchAgent"
    assert "Find a catalyst" in plan[0]["description"]
