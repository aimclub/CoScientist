"""Require observed tool calls for the isolated Synapse scientific pilot.

The pilot's model can answer in prose after tool discovery while merely saying
it delegated work. Limit each model turn to the next required tool and fail the
invocation if the provider ignores ``tool_choice=required``. Ordinary agent
profiles do not install these callbacks.
"""

from google.genai import types


_ORDER = ("retrieve_tools", "ResearchAgent", "TaskExecutorAgent")


def _next_tool(callback_context):
    invocation = callback_context._invocation_context
    observed = set()
    for event in invocation.session.events:
        if event.invocation_id != invocation.invocation_id:
            continue
        observed.update(
            response.name
            for response in event.get_function_responses()
            if not (response.response or {}).get("error")
        )
    return next((name for name in _ORDER if name not in observed), None)


def require_pilot_tool(callback_context, llm_request):
    """Offer only the next missing pilot tool and require a function call."""
    name = _next_tool(callback_context)
    if name is None:
        return None
    declarations = [
        declaration
        for tool in llm_request.config.tools or []
        for declaration in tool.function_declarations or []
        if declaration.name == name
    ]
    if len(declarations) != 1:
        raise RuntimeError(f"Pilot delegation contract: {name} is unavailable")
    llm_request.config.tools = [types.Tool(function_declarations=declarations)]
    llm_request.config.tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY
        )
    )
    return None


def require_pilot_tool_call(callback_context, llm_response):
    """Fail closed if a provider returns prose while a real call is required."""
    if llm_response.partial:
        return None
    name = _next_tool(callback_context)
    if name is None:
        return None
    parts = getattr(llm_response.content, "parts", None) or []
    calls = [part.function_call.name for part in parts if part.function_call]
    if calls != [name]:
        raise RuntimeError(
            f"Pilot delegation contract: expected {name} call, got {calls or 'prose'}"
        )
    return None
