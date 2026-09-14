"""PromptContext — everything a prompt template needs to render itself.

Templates receive one :class:`PromptContext` and render the unified sections:

  <<TOOLS>>    the agent's available tools — generated from the ToolDocs of the
               tools that are ACTUALLY attached (incl. HITL tools when attached),
               so prompts can never drift from the wiring
  <<AGENTS>>   bullet list of the agent's enabled subordinates
  <<ROUTING>>  routing guidance ("which subordinate for which job")
  <<HITL>>     usage guidance for the HITL tools (empty when not attached)

plus helpers for conditional sections (``has_tool``, ``is_enabled``,
``sibling_roster`` for the planner).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from CoScientist.assembly.registry import ToolDoc, ToolEntry, render_tool_docs
from CoScientist.assembly.schema import AgentConfig, SystemConfig

TOOLS_GUARD = (
    "IMPORTANT: ONLY call the tools listed above. Never call any other tool name —\n"
    "if a capability isn't in this list, you do not have it."
)

_HITL_SECTION = """\
### Human-in-the-loop

A human supervises this work — treat them as a collaborator, not a rubber stamp.
Two ways to involve them:
- `request_approval(agent_name, message)` — a yes / no question. The human may
  answer plainly OR reply with free-text ("other") — that free-text is an
  instruction, follow it. Returns {approved, feedback}.
- `request_selection(agent_name, message, options)` — offer 2–4 concrete options
  and let the human choose (e.g. among hypotheses, plans, thresholds). The human
  may pick one of the options OR give their own answer in the feedback ("other");
  honor whichever they provide. Returns {selected, approved, feedback}.

Pass your own name as `agent_name`. If a request is denied, don't retry the same
thing — adjust using the feedback.

**When to ask.** State your intended course of action and get it approved BEFORE
you carry it out — not only for expensive or irreversible steps. Concretely, ask
whenever you have decided:
- which approach, method or tool you will use, where another was available;
- what you will build, change or run next, in enough detail that the human can
  disagree with it ("I will rebuild the dataset from the GOLEM trajectories with
  the corrected fitness, then retrain from scratch — proceed?");
- that something is finished, refuted, or good enough to hand on;
- that you will skip, drop or defer something you were asked to do.

Ask once per decision, not once per tool call: a plan of action is one question,
and the calls that carry it out are not. Do not ask about routine reads, or
about anything a previous answer in this session already settled — a human who
is asked to confirm the obvious stops reading the questions."""


_HITL_RESEARCH_COOP = """\
#### Co-building the research graph with the human
The research graph is built by BOTH the agents and the human. Pause at each
epistemic checkpoint, let the human validate and extend it, then record their
input in the graph:
- When Hypotheses are proposed, ask the human to validate them (keep / drop /
  edit) via `request_selection` or `request_approval`.
- A Hypothesis MUST have acceptance criteria — the metric + threshold that would
  confirm or refute it — BEFORE it is verified. If the human did not provide any,
  you MUST ask for them explicitly ("what result would confirm or refute this
  hypothesis?") and record the answer as its ConfirmationCriteria. Never start
  verification on a hypothesis that has no criteria.
- Likewise invite the human to confirm or adjust the verification methods, the
  question's scope, and the final conclusion.
Find the gaps (e.g. a hypothesis with no criteria) and resolve them by asking the
human — not by inventing the answer. Commit the human's input with
`research_commit`; if your role may not create that node type, state their
decision in your text answer so the orchestrator records it."""

# No curly braces in this text: the instruction goes through ADK's session-state
# injection, which treats a braced identifier as a state key.
_WORK_ORDER_SECTION = """\
### Work Order — declare what you will do before you do it

The human must be able to see your plan and the assumptions behind it BEFORE
you act. Protocol:
1. Orient yourself first if you need to: reading your own context (research
   context, active tasks, directory listings) is allowed before declaring.
2. Call `declare_work_order` before your first external action (search, download,
   code run, graph write). State: the goal; how you will know you are done; EVERY
   assumption the plan relies on (append "(confidence: low)" when unsure); ordered
   steps with the tools each uses and what you expect it to produce; all tools you
   plan to call; side effects (package_install, network_download, git_write,
   long_job, file_delete, external_share); a budget of calls per tool; the
   concrete outcome you expect; and your fallback.
3. Read the result:
   - `approved` — proceed. Assumptions the human rejected are listed: do not rely
     on them. Operator notes are instructions: follow them.
   - `revise` — declare again, taking the feedback into account.
   - `rejected` — do not act; finish and report why the task was not done.
4. As you work, mark steps with `update_work_step` (in_progress, then done or
   skipped with a short note on what came out).
5. A call outside the approved order (undeclared tool, budget used up, undeclared
   side effect) is BLOCKED. Do not retry it: if you really need it, call
   `update_work_order` with the reason — what you learned that the plan did not
   foresee — and what you need added. Otherwise continue within the order.

Keep the order honest and specific: a human who reads "search the literature"
learns nothing; "search PubMed for RCTs on X since 2015, exclude case reports" is
something they can correct. This work order replaces separate approval requests
for the plan itself — use `request_approval` only for decisions that come up
along the way."""

_WORK_ORDER_HINTS = (
    (("websearch",),
     "For searches, the query formulations and the source selection criteria "
     "(recency, study types, venues) are assumptions — list them."),
    (("papers_search",),
     "For paper downloads, state which papers or how many you will fetch, and why those."),
    (("medical",),
     "For clinical evidence, state the population, study designs and date range "
     "you will accept as assumptions."),
    (("coder", "sandbox"),
     "For data work, the data sources, filters, units and expected volumes are "
     "assumptions; downloads and installs are side effects."),
    (("research_graph",),
     "If you will write the research graph, name in the steps which nodes you will "
     "create or change."),
)


# The orchestrator alone holds `research_triggers`, so only its copy of the
# protocol may name it. Naming it for every writer told worker agents to call a
# tool they are not given, which is exactly the kind of instruction that makes a
# model invent a call and then apologise for it.
_HITL_RESEARCH_COOP_ORCHESTRATOR = """Use `research_triggers` to find those gaps and resolve them by asking the
human."""


@dataclass
class PromptContext:
    config: AgentConfig
    system: SystemConfig
    # Tool entries actually attached to the agent, in attachment order
    # (includes the synthetic HITL entry when HITL tools are attached).
    tool_entries: List[ToolEntry] = field(default_factory=list)
    hitl_attached: bool = False
    work_order_attached: bool = False

    # ── queries ──────────────────────────────────────────────────────────────
    def has_tool(self, key: str) -> bool:
        return any(e.key == key for e in self.tool_entries)

    def is_enabled(self, agent_name: str) -> bool:
        return (
            agent_name in self.system.agents
            and self.system.agent(agent_name).is_enabled()
        )

    @property
    def subordinates(self) -> List[AgentConfig]:
        return self.system.enabled_subordinates(self.config.name)

    def has_subordinate(self, agent_name: str) -> bool:
        return any(s.name == agent_name for s in self.subordinates)

    def siblings(self) -> List[AgentConfig]:
        """Enabled co-subordinates: my parents' other enabled subordinates.

        For the planner this is exactly the roster the orchestrator can
        delegate to (minus the planner itself) — the agents a plan may assign
        steps to.
        """
        if self.config.name == "PlannerAgent":
            if "OrchestratorAgent" in self.system.agents:
                return self.system.enabled_subordinates("OrchestratorAgent")

        seen, out = set(), []
        for parent in self.system.parents_of(self.config.name):
            if not parent.is_enabled():
                continue
            for sub in self.system.enabled_subordinates(parent.name):
                if sub.name != self.config.name and sub.name not in seen:
                    seen.add(sub.name)
                    out.append(sub)
        return out

    @property
    def docs(self) -> List[ToolDoc]:
        return [d for e in self.tool_entries for d in e.resolved_docs()]

    # ── section renderers ────────────────────────────────────────────────────
    def render_tools(self) -> str:
        """The standard 'available tools' section (header + bullets + guard)."""
        if not self.docs:
            return ""
        return (
            "You have access to the following tools:\n\n"
            f"{render_tool_docs(self.docs)}\n\n"
            f"{TOOLS_GUARD}"
        )

    def render_agents(self) -> str:
        return "\n".join(
            f"* **{a.name}** — {a.description}" for a in self.subordinates
        )

    def render_routing(self) -> str:
        return "\n".join(
            f"    - {a.name} — {a.routing}" for a in self.subordinates if a.routing
        )

    def render_critic_roster(self, agents: Optional[List[AgentConfig]] = None) -> str:
        """Compact `name: description` roster for a critic prompt.

        Defaults to the agent's own subordinates — the orchestrator's critics
        judge which sub-agent it picked. Pass an explicit roster for a critic
        that judges someone else's targets: the plan critic checks assignees,
        which are the planner's SIBLINGS (`ctx.siblings()`), not its own.
        """
        roster = self.subordinates if agents is None else agents
        return "\n".join(f"  - {a.name}: {a.description}" for a in roster)

    def render_hitl(self) -> str:
        if not self.hitl_attached:
            return ""
        section = _HITL_SECTION
        # Agents that also write the research graph get the co-building protocol
        # (validate hypotheses with the human; a hypothesis needs acceptance
        # criteria before verification — ask for them if the human didn't give any).
        if self.has_tool("research_graph") or self.has_tool("research_graph_orchestrator"):
            section += "\n\n" + _HITL_RESEARCH_COOP
            if self.has_tool("research_graph_orchestrator"):
                section += "\n" + _HITL_RESEARCH_COOP_ORCHESTRATOR
        if self.work_order_attached:
            section += "\n\n" + _WORK_ORDER_SECTION
            hints = [
                hint for keys, hint in _WORK_ORDER_HINTS
                if any(self.has_tool(key) for key in keys)
            ]
            if hints:
                section += "\n\n" + "\n".join(f"- {hint}" for hint in hints)
        return section

    def render_sibling_roster(self) -> str:
        """Planner-style roster of co-subordinates, from their `planning` text."""
        blocks = []
        for a in self.siblings():
            blocks.append(f"- {a.name} – {(a.planning or a.description).strip()}")
        return "\n\n".join(blocks)


__all__ = ["PromptContext", "TOOLS_GUARD"]
