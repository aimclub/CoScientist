"""Toolset module."""
# Must run before any MCP toolset is used: fail-fast backport for truncated SSE
# frames from remote MCP servers (see mcp_patches docstring).
import CoScientist.tools.mcp_patches  # noqa: F401

from CoScientist.tools.fedotmas_tools import FedotMASToolset, fedot_toolset_instance
from CoScientist.tools.research_tools import websearch_toolset_instance, paper_analysis_toolset_instance, papers_search_toolset_instance
from CoScientist.tools.economics_tools import economics_toolset_instance
from CoScientist.tools.retrieval_tools import RetrievalToolSet, retrieval_toolset_instance
from CoScientist.tools.servers_web_search import search_mcp_servers
from CoScientist.tools.med_tools import med_toolset_instance
from CoScientist.tools.coder_tools import CoderToolset, coder_toolset_instance
from CoScientist.tools.task_tracker import TaskTrackerToolset, task_tracker_instance

__all__ = [
    "FedotMASToolset",
    "fedot_toolset_instance",
    "websearch_toolset_instance",
    "paper_analysis_toolset_instance",
    "papers_search_toolset_instance",
    "economics_toolset_instance",
    "RetrievalToolSet",
    "retrieval_toolset_instance",
    "search_mcp_servers",
    "med_toolset_instance",
    "CoderToolset",
    "coder_toolset_instance",
    "TaskTrackerToolset",
    "task_tracker_instance"
]
