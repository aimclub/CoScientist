import asyncio
from types import SimpleNamespace

from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore
from CoScientist.integrations.codesynapse.trace import TraceRecorder
from CoScientist.integrations.codesynapse.trace_plugin import CodesynapseTracePlugin


def test_trace_plugin_marks_delegated_agent_calls_separately_from_tools():
    async def scenario():
        store = InMemoryIntegrationStore()
        recorder = TraceRecorder(store, run_id="run-1", tenant_id="tenant-1", project_id="project-1")
        plugin = CodesynapseTracePlugin(recorder, delegated_tool_names={"hypotheses"})
        tool = SimpleNamespace(name="hypotheses")
        context = SimpleNamespace(function_call_id="call-1", agent_name="manager")

        await plugin.before_tool_callback(tool=tool, tool_args={"query": "test"}, tool_context=context)
        await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=context, result={"answer": "ok"})

        assert [event.type for event in await store.replay_events("run-1")] == [
            "delegation.started", "delegation.completed"
        ]

    asyncio.run(scenario())
