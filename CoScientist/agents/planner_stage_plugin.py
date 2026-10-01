"""The planner stage runs once per session; after that the orchestrator leads.

In ``planner`` start mode the run root is ``PlanningPipelineAgent``
(PlannerAgent -> OrchestratorAgent), and every invocation walks it from the
top. So a follow-up message, or "continue the outstanding tasks" after a
roadmap pause, planned the study again: the planner clears the tracker view
and registers a fresh roadmap over the work already done.

Once a session has a roadmap, this plugin bypasses the planner STAGE and the
orchestrator starts the turn. The planner stays one of the orchestrator's
subordinates, so it can still be called on demand to re-plan from the current
state. That on-demand call must not be bypassed, and it runs the very same
agent instance through an AgentTool; what tells the two apart is the
invocation. The stage runs in the invocation its sequential parent started,
which the parent records here; an AgentTool runs the planner in a child runner
with an invocation of its own.
"""
from __future__ import annotations

import logging

from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

logger = logging.getLogger(__name__)

PLANNER_AGENT_NAME = "PlannerAgent"
#: Set when the planner stage first runs in a session.
PLANNER_STAGE_DONE_STATE_KEY = "_planner_stage_done"
#: The invocation in which the planner's sequential parent last started.
_STAGE_INVOCATION_STATE_KEY = "_planner_stage_invocation"


class PlannerStagePlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="planner_stage")

    async def before_agent_callback(self, *, agent, callback_context):
        state = callback_context.state
        invocation = str(getattr(callback_context, "invocation_id", "") or "")
        children = getattr(agent, "sub_agents", None) or []
        if any(getattr(child, "name", None) == PLANNER_AGENT_NAME for child in children):
            state[_STAGE_INVOCATION_STATE_KEY] = invocation
            return None
        if getattr(agent, "name", None) != PLANNER_AGENT_NAME:
            return None
        if not invocation or state.get(_STAGE_INVOCATION_STATE_KEY) != invocation:
            return None  # an on-demand call from the orchestrator
        # A roadmap from before this marker existed counts as a planned session.
        if state.get(PLANNER_STAGE_DONE_STATE_KEY) or state.get("_master_active_tasks"):
            logger.info("PLANNER_STAGE_BYPASSED invocation=%s", invocation)
            return types.Content(role="model", parts=[types.Part(text=(
                "Planner stage skipped: this session already has a roadmap. "
                "The orchestrator continues from the current state and calls "
                "the planner itself if the plan has to change."
            ))])
        state[PLANNER_STAGE_DONE_STATE_KEY] = True
        return None


__all__ = ["PLANNER_STAGE_DONE_STATE_KEY", "PlannerStagePlugin"]
