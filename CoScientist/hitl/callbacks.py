import json
import re
from typing import Any, Dict, Iterable, Optional
from google.genai import types as genai_types

from CoScientist.config import get_settings
from CoScientist.hitl.models import HITLRequest, HITLAction
from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.graph.session_scope import session_key


def _parse_options(text: str) -> list[str]:
    """Extract numbered options from agent output text.
    
    Matches patterns like:
    1. Option one
    2) Option two
    """
    if not text:
        return []
    # Match lines starting with a number followed by . or )
    options = re.findall(r'^\d+[.)]\s*(.+)$', str(text), re.MULTILINE)
    return [opt.strip() for opt in options if opt.strip()]


def make_hitl_after_callback(handler: AbstractHITLHandler, action_type: HITLAction):
    """Factory for after_agent_callback that intercepts agent output and requests HITL.

    Usage:
        hypotheses_agent = LlmAgent(
            name="HypothesesAgent",
            ...
            after_agent_callback=make_hitl_after_callback(handler, HITLAction.SELECT),
        )

    Args:
        handler: HITL handler instance (Console, Callback, etc.)
        action_type: Type of HITL action to request (APPROVE, SELECT, etc.)

    Returns:
        An async callback function compatible with ADK's after_agent_callback.
    """

    async def after_agent_callback(callback_context) -> Optional[genai_types.Content]:
        if not get_settings().web.hitl_enabled:
            return None

        agent_name = callback_context.agent_name
        # In ADK Context, agent is accessible via _invocation_context.agent
        agent = getattr(callback_context, "_invocation_context", None).agent if hasattr(callback_context, "_invocation_context") else None
        
        if not agent:
            return None

        output_key = getattr(agent, "output_key", None)
        if not output_key:
            return None

        state = callback_context.state
        agent_output = state.get(output_key, "")
        if not agent_output:
            return None  # No output to review

        user_id, session_id = session_key(callback_context)
        request = HITLRequest(
            agent_name=agent_name,
            action_type=action_type,
            message=f"[CALLBACK: AFTER_AGENT] Agent '{agent_name}' proposes the following output. Please review.",
            context={
                "output": str(agent_output),
                "_session": {
                    "user_id": user_id,
                    "session_id": session_id,
                },
            },
            options=_parse_options(str(agent_output)) if action_type == HITLAction.SELECT else [],
            invoked_via="callback"
        )

        response = await handler.handle_request(request)

        if not response.approved:
            # Override agent output with rejection feedback
            feedback = response.instructions or response.free_input or "No feedback provided"
            return genai_types.Content(
                role="model",
                parts=[genai_types.Part(
                    text=f"Human rejected the proposal. Feedback: {feedback}"
                )],
            )

        '''if response.action == HITLAction.PROVIDE_INPUT and response.free_input:
            # Override agent output entirely with user's free input
            return genai_types.Content(
                role="model",
                parts=[genai_types.Part(
                    text=response.free_input
                )],
            )'''

        if action_type == HITLAction.SELECT and response.selected_option:
            # Override agent output with human's selection
            return genai_types.Content(
                role="model",
                parts=[genai_types.Part(
                    text=f"Human selected the following option among proposed:\n{response.selected_option}"
                )],
            )

        # None = agent output is accepted as-is
        return None

    return after_agent_callback


def make_hitl_before_callback(handler: AbstractHITLHandler):
    """Factory for before_agent_callback that asks for confirmation before agent runs.

    Usage:
        experiment_agent = LlmAgent(
            name="ExperimentAgent",
            ...
            before_agent_callback=make_hitl_before_callback(handler),
        )
    """

    async def before_agent_callback(callback_context, llm_request=None) -> Optional[genai_types.Content]:
        if not get_settings().web.hitl_enabled:
            return None

        agent_name = callback_context.agent_name

        # Add more context for the human
        user_query = ""
        if hasattr(callback_context, "user_content") and callback_context.user_content:
             try:
                 user_query = callback_context.user_content.parts[0].text
             except (AttributeError, IndexError):
                 pass

        msg = f"Agent '{agent_name}' is about to execute."
        if user_query:
            msg += f"\nContext (User Query): {user_query}"
        msg += "\nApprove?"

        user_id, session_id = session_key(callback_context)
        request = HITLRequest(
            agent_name=agent_name,
            action_type=HITLAction.APPROVE,
            message=f"[CALLBACK: BEFORE_AGENT] {msg}",
            context={
                "_session": {
                    "user_id": user_id,
                    "session_id": session_id,
                }
            },
            invoked_via="callback"
        )

        response = await handler.handle_request(request)

        if not response.approved:
            # Return a content that "cancels" the agent execution by providing a mock model response
            reason = response.instructions or response.free_input or 'No reason given'
            return genai_types.Content(
                role="model",
                parts=[genai_types.Part(
                    text=f"Execution of agent '{agent_name}' was blocked by human. Reason: {reason}"
                )],
            )

        return None  # Proceed normally

    return before_agent_callback


def make_hitl_before_tool_callback(
    handler: AbstractHITLHandler,
    target_tools: Optional[Iterable[str]] = ("sandbox",),
):
    """Factory for before_tool_callback that intercepts tool calls and requests HITL approval.

    Usage:
        coder_agent = LlmAgent(
            name="CoderAgent",
            ...
            before_tool_callback=make_hitl_before_tool_callback(handler, target_tools=("sandbox",)),
        )

    Args:
        handler: HITL handler instance (Console, WebHITLHandler, etc.)
        target_tools: Optional collection of tool names or substrings (e.g. ("sandbox",)).
            When set, only tool calls matching one of these targets (exact match or
            substring in lower-case tool name, e.g. "run_sandbox_task") will trigger
            HITL approval. When None, all tool calls (except excluded HITL tools)
            require approval.

    Returns:
        An async callback function compatible with ADK's before_tool_callback.
    """
    excluded_tools = frozenset({
        "request_approval",
        "request_selection",
        "request_input",
    })
    targets = tuple(target_tools) if target_tools is not None else None

    async def before_tool_callback(
        tool=None,
        args=None,
        tool_context=None,
        *,
        tool_args=None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        if not get_settings().web.hitl_enabled:
            return None

        # Support both positional (tool, args, tool_context) and keyword calls from ADK
        actual_tool = tool if tool is not None else kwargs.get("tool")
        actual_args = (
            args
            if args is not None
            else tool_args
            if tool_args is not None
            else kwargs.get("tool_args", kwargs.get("args", {}))
        )
        actual_context = tool_context if tool_context is not None else kwargs.get("tool_context")

        tool_name = str(getattr(actual_tool, "name", "") or actual_tool or "unknown_tool")

        # Do not intercept HITL interaction tools to prevent recursive deadlocks
        if tool_name in excluded_tools:
            return None

        # Filter by target_tools if specified (e.g. only intercept sandbox tools)
        if targets is not None:
            tool_lower = tool_name.lower()
            if not any(t == tool_name or t.lower() in tool_lower for t in targets):
                return None

        inv_ctx = getattr(actual_context, "_invocation_context", None) or getattr(actual_context, "invocation_context", None)
        inv_agent = getattr(inv_ctx, "agent", None) if inv_ctx is not None else None
        agent_name = (
            getattr(actual_context, "agent_name", None)
            or getattr(inv_agent, "name", None)
            or "CoderAgent"
        )

        user_id, session_id = session_key(actual_context)

        args_formatted = (
            json.dumps(actual_args, indent=2, ensure_ascii=False, default=str)
            if isinstance(actual_args, (dict, list))
            else str(actual_args)
        )

        message = (
            f"Agent '{agent_name}' is about to execute tool '{tool_name}'.\n\n"
            f"Arguments:\n{args_formatted}\n\n"
            "Approve execution?"
        )

        proposed_output = f"Tool: {tool_name}\nArguments:\n{args_formatted}"

        request = HITLRequest(
            agent_name=agent_name,
            action_type=HITLAction.APPROVE,
            message=f"[CALLBACK: BEFORE_TOOL] {message}",
            context={
                "tool": tool_name,
                "args": actual_args,
                "output": proposed_output,
                "_session": {
                    "user_id": user_id,
                    "session_id": session_id,
                },
            },
            invoked_via="callback",
        )

        response = await handler.handle_request(request)

        if not response.approved:
            reason = response.instructions or response.free_input or "No reason provided"
            return {
                "status": "denied",
                "blocked_by": "human",
                "message": f"Execution of tool '{tool_name}' was rejected by human operator. Reason: {reason}",
            }

        return None  # Proceed normally

    return before_tool_callback

