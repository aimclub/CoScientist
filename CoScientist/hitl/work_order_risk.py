"""Risk tiers for Work Order tools and tool calls.

A Work Order is confirmed by risk (see hitl/work_order_tools.py):

  read         looking things up — the human is informed, the run goes on;
  compute      doing work in a sandbox or on a shared resource — a veto window;
  side_effect  something that outlives the run or leaves the machine (installs,
               pushes, deletions, long jobs, sharing links) — a blocking review.

Tiers are keyed by the REAL tool names the bindings attach. An unknown tool is
treated as ``compute``: guessing "read" for a tool nobody classified would let it
through without a human ever seeing it.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable, Optional, Tuple


class Tier(str, Enum):
    READ = "read"
    COMPUTE = "compute"
    SIDE_EFFECT = "side_effect"


_RANK = {Tier.READ: 0, Tier.COMPUTE: 1, Tier.SIDE_EFFECT: 2}


def max_tier(tiers: Iterable[Tier]) -> Tier:
    return max(tiers, key=lambda t: _RANK[t], default=Tier.READ)


class SideEffectKind(str, Enum):
    PACKAGE_INSTALL = "package_install"
    NETWORK_DOWNLOAD = "network_download"
    GIT_WRITE = "git_write"
    LONG_JOB = "long_job"
    FILE_DELETE = "file_delete"
    EXTERNAL_SHARE = "external_share"


TOOL_TIERS: dict[str, Tier] = {
    # web / literature
    "tavily_search": Tier.READ,
    "tavily_extract": Tier.READ,
    "tavily_crawl": Tier.COMPUTE,
    "search_papers": Tier.READ,
    "download_papers_from_search": Tier.COMPUTE,
    "explore_chemistry_database": Tier.READ,
    "explore_my_papers": Tier.READ,
    # medical
    "search_pubmed": Tier.READ,
    "get_pico": Tier.READ,
    "get_study_taxonomy": Tier.READ,
    "analyze_medical_image": Tier.COMPUTE,
    # graphs / tasks
    "get_active_tasks": Tier.READ,
    "update_task_status": Tier.READ,
    "read_research_graph": Tier.READ,
    "get_graph_history": Tier.READ,
    "get_agents_info": Tier.READ,
    "research_context_slice": Tier.READ,
    "research_overview": Tier.READ,
    "research_provenance": Tier.READ,
    "research_prior": Tier.READ,
    "research_triggers": Tier.READ,
    "research_init": Tier.COMPUTE,
    "research_set_focus": Tier.COMPUTE,
    "research_commit": Tier.COMPUTE,
    # sandbox / coder
    "read_file": Tier.READ,
    "list_directory": Tier.READ,
    "check_job": Tier.READ,
    "list_sandbox_files": Tier.READ,
    "check_sandbox_task": Tier.READ,
    "execute_bash": Tier.COMPUTE,
    "write_file": Tier.COMPUTE,
    "run_sandbox_task": Tier.COMPUTE,
    "validate_dataset": Tier.COMPUTE,
    "validate_training": Tier.COMPUTE,
    "get_download_link": Tier.READ,
    "install_package": Tier.SIDE_EFFECT,
    "get_upload_link": Tier.SIDE_EFFECT,
}

# Side effect a tool has by its very nature, whatever its arguments.
TOOL_SIDE_EFFECTS: dict[str, SideEffectKind] = {
    "install_package": SideEffectKind.PACKAGE_INSTALL,
    "get_upload_link": SideEffectKind.EXTERNAL_SHARE,
}

# Reading the agent's own context — allowed before a Work Order is declared, so
# the agent can orient itself and plan from what is already known.
ORIENTATION_TOOLS = frozenset({
    "get_active_tasks",
    "read_research_graph",
    "get_graph_history",
    "get_agents_info",
    "research_context_slice",
    "research_overview",
    "research_provenance",
    "research_prior",
    "research_triggers",
    "list_directory",
    "list_sandbox_files",
})

# Never blocked: the Work Order protocol itself, the human channel, and task
# status bookkeeping.
EXEMPT_TOOLS = frozenset({
    "declare_work_order",
    "update_work_order",
    "update_work_step",
    "request_approval",
    "request_selection",
    "update_task_status",
})

# Shell commands with an effect beyond the sandbox's scratch work. Order matters
# only for which kind is reported when a command matches several.
_BASH_PATTERNS: Tuple[Tuple[re.Pattern, SideEffectKind], ...] = (
    (re.compile(r"\bgit\s+(?:push|commit)\b"), SideEffectKind.GIT_WRITE),
    (re.compile(r"\b(?:pip3?|uv\s+pip|conda|mamba|apt(?:-get)?|npm)\s+install\b"),
     SideEffectKind.PACKAGE_INSTALL),
    (re.compile(r"\brm\s+-[a-zA-Z]*[rf]"), SideEffectKind.FILE_DELETE),
    (re.compile(r"\b(?:wget|curl|huggingface-cli\s+download|aria2c)\b"),
     SideEffectKind.NETWORK_DOWNLOAD),
    (re.compile(r"\b(?:nohup|sbatch|setsid)\b|&\s*$"), SideEffectKind.LONG_JOB),
)

_BASH_ARG_KEYS = ("command", "cmd", "script")


def tool_tier(tool_name: str) -> Tier:
    return TOOL_TIERS.get(tool_name, Tier.COMPUTE)


def _bash_side_effect(args: Any) -> Optional[SideEffectKind]:
    if not isinstance(args, dict):
        return None
    command = next((args[k] for k in _BASH_ARG_KEYS if isinstance(args.get(k), str)), "")
    for pattern, kind in _BASH_PATTERNS:
        if pattern.search(command):
            return kind
    return None


def classify_call(tool_name: str, args: Any) -> Tuple[Tier, Optional[SideEffectKind]]:
    """Tier and side effect of ONE concrete call (arguments considered)."""
    kind = TOOL_SIDE_EFFECTS.get(tool_name)
    if kind is None and tool_name == "execute_bash":
        kind = _bash_side_effect(args)
    if kind is not None:
        return Tier.SIDE_EFFECT, kind
    return tool_tier(tool_name), None


def order_tier(planned_tools: Iterable[str], side_effect_kinds: Iterable[Any]) -> Tier:
    """The tier a Work Order is confirmed at: its riskiest declared element."""
    tiers = [tool_tier(t) for t in planned_tools]
    if any(True for _ in side_effect_kinds):
        tiers.append(Tier.SIDE_EFFECT)
    return max_tier(tiers)
