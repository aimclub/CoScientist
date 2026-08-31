"""Agent callbacks: tool/reranker, critic, medical, and research callbacks.

Re-exported here so callers can use `from CoScientist.agents.callbacks import
<name>` regardless of which submodule defines it.
"""
from CoScientist.agents.callbacks.critic import (
    make_post_action_critique,
    make_pre_action_critique,
)
from CoScientist.agents.callbacks.med_callbacks import (
    before_model_modifier,
    med_agent_before_model,
)
from CoScientist.agents.callbacks.json_output import sanitize_json_output
from CoScientist.agents.callbacks.research_callbacks import (
    capture_literature_smiles,
    cleanup_uploaded_papers,
    ensure_local_papers_uploaded,
    papers_agent_before_model,
)
from CoScientist.agents.callbacks.tool_callbacks import (
    after_fullset_reranker_agent,
    after_tool_reranker_agent,
    before_get_task,
    before_tool_reranker_model,
    make_unknown_tool_guard,
    print_research_agent_tool_call,
    redirect_when_no_tools,
)

__all__ = [
    "make_pre_action_critique",
    "make_post_action_critique",
    "before_model_modifier",
    "med_agent_before_model",
    "papers_agent_before_model",
    "ensure_local_papers_uploaded",
    "cleanup_uploaded_papers",
    "capture_literature_smiles",
    "before_tool_reranker_model",
    "after_tool_reranker_agent",
    "after_fullset_reranker_agent",
    "print_research_agent_tool_call",
    "redirect_when_no_tools",
    "make_unknown_tool_guard",
    "before_get_task",
    "sanitize_json_output",
]
