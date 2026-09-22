"""
CoScientist - Main entry point

Runs the multi-agent scientific discovery pipeline:
- Hypothesis generation
- Research
- Experimentation (FEDOT)
- Orchestration
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
from typing import Optional
import logging

from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.genai import types

from CoScientist.config import get_settings
from CoScientist.checkpoints.runner import CheckpointRunner as Runner
from CoScientist.agents import orchestrator_agent, root_agent
from CoScientist.agents.callbacks import cleanup_uploaded_papers
from CoScientist.hitl.tool import hitl_toolset
from CoScientist.hitl import (
    AbstractHITLHandler,
    HITLRequest,
    HITLResponse,
)

settings = get_settings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _compaction_config():
    """Build the events-compaction config: when an agent's prompt grows past the
    token threshold, ADK summarizes older events (with the agent's own model),
    keeping the last N raw events. Disable with AGENT_CONTEXT_TOKEN_THRESHOLD=0.
    """
    try:
        from google.adk.apps.app import EventsCompactionConfig
        threshold = int(os.getenv("AGENT_CONTEXT_TOKEN_THRESHOLD", "150000"))
        if threshold <= 0:
            return None
        return EventsCompactionConfig(
            compaction_interval=int(os.getenv("AGENT_COMPACTION_INTERVAL", "15")),
            overlap_size=int(os.getenv("AGENT_COMPACTION_OVERLAP", "2")),
            token_threshold=threshold,
            event_retention_size=int(os.getenv("AGENT_CONTEXT_RETENTION", "12")),
        )
    except Exception:  # noqa: BLE001 — compaction is best-effort, never block startup
        return None


def reset_session_state() -> None:
    """Clear PER-SESSION state on a fresh start / interrupt: the planner's task
    tracker (persisted to disk, so it would otherwise leak across runs) and the
    in-process execution graph. The cross-run knowledge MEMORY is preserved."""
    try:
        from CoScientist.tools import task_tracker_instance
        task_tracker_instance.reset()
    except Exception:  # noqa: BLE001
        pass
    try:
        from CoScientist.graph.memory import knowledge_graph
        knowledge_graph.reset_session()
    except Exception:  # noqa: BLE001
        pass
    # The research context graph outlives a single chat session by default (a
    # research spans many prompts), so it is NOT reset here unless explicitly
    # configured. When RESEARCH_GRAPH__RESET_ON_SESSION=true, archive + clear it.
    try:
        from CoScientist.config import get_settings
        if get_settings().research_graph.reset_on_session:
            from CoScientist.graph.research.store import research_graph
            research_graph.reset(archive=True)
    except Exception:  # noqa: BLE001
        pass


def _s3_csv_preview(url: str, max_rows: int = 10, max_bytes: int = 200_000) -> str:
    """Best-effort: download a presigned-S3 CSV and return a small text preview
    (header + first rows of Smiles + key property columns). Returns '' on any failure.

    Lets the final answer be formed from the ACTUAL S3 file contents rather than a bare
    link or unverified prose (F010.A6).
    """
    import urllib.request
    import csv
    import io
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            raw = resp.read(max_bytes).decode("utf-8", "replace")
        rows = list(csv.reader(io.StringIO(raw)))
        if not rows:
            return ""
        hdr = rows[0]
        prefer = ("Smiles", "QED", "LogP", "Synthetic Accessibility", "Validity")
        keep = [i for i, h in enumerate(hdr) if h in prefer] or list(range(min(5, len(hdr))))
        out = [" | ".join(hdr[i] for i in keep)]
        for row in rows[1:1 + max_rows]:
            out.append(" | ".join(row[i] if i < len(row) else "" for i in keep))
        extra = len(rows) - 1 - max_rows
        if extra > 0:
            out.append(f"… (+{extra} more rows)")
        return "\n".join(out)
    except Exception:
        return ""


class CoScientistManager:
    """
    Main manager for CoScientist (ADK-based execution).
    """

    def __init__(
        self,
        app_name: str = "coscientist_app",
        user_id: str = "user_1",
        session_id: str = "session_001",
        hitl_handler: Optional[AbstractHITLHandler] = None,
    ):
        self.app_name = app_name
        self.user_id = user_id
        self.session_id = session_id

        self.session_service: Optional[InMemorySessionService] = None
        self.runner: Optional[Runner] = None
        self._initialized = False

        # HITL setup
        self._hitl_handler = hitl_handler


    async def initialize(self):
        """Initialize session + runner."""
        if self._initialized:
            return

        # Fresh session: clear stale PER-SESSION state (planner tasks + the
        # execution graph) so a previous run's context never leaks in. The
        # cross-run knowledge MEMORY is intentionally kept.
        reset_session_state()

        # Session service
        self.session_service = InMemorySessionService()

        await self.session_service.create_session(
            app_name=self.app_name,
            user_id=self.user_id,
            session_id=self.session_id,
        )

        # Runner plugins:
        # - EventLoggerPlugin: same local-file + console trace as the A2A
        #   servers (a2a/server.py) and `adk web` (agent.py);
        # - GraphMemoryPlugin: grows the shared in-process knowledge graph so any
        #   agent can read the history/roster via the graph tools.
        # Toggle both with LOG_AGENT_EVENTS / AGENT_LOG_FILE.
        from google.adk.apps.app import App
        from CoScientist.logging.event_logger import EventLoggerPlugin
        from CoScientist.graph.plugin import GraphMemoryPlugin
        from CoScientist.graph.research.validator import background_validator_plugin
        from CoScientist.agents.truncation_plugin import ToolResultTruncationPlugin

        # An App carries the plugins + the events-compaction config (summarize the
        # context once it crosses the token threshold). ToolResultTruncationPlugin
        # MUST be last: ADK stops at the first non-None after_tool return, so the
        # logger/graph observe the full result first, then truncation bounds what
        # reaches the LLM context.
        # background_validator_plugin judges hypotheses asynchronously (fire-and-
        # forget) as evidence lands — before the truncation plugin so it sees the
        # full research_commit result. It never blocks the run loop.
        plugins = [EventLoggerPlugin(), GraphMemoryPlugin(),
                   background_validator_plugin, ToolResultTruncationPlugin()]
        if get_settings().checkpoints.enabled:
            from CoScientist.checkpoints import CheckpointPlugin
            # first, so it observes untruncated events; returns None everywhere,
            # so it never interferes with the other plugins.
            plugins.insert(0, CheckpointPlugin())

        app = App(
            name=self.app_name,
            root_agent=root_agent,
            plugins=plugins,
            events_compaction_config=_compaction_config(),
        )
        self.runner = Runner(app=app, session_service=self.session_service)

        if self._hitl_handler:
            hitl_toolset._handler = self._hitl_handler

        self._initialized = True

    async def run(self, query: str, verbose: bool = True) -> str:
        """
        Execute a query through the orchestrator agent.

        Args:
            query: user query
            verbose: whether to print events

        Returns:
            Final agent response
        """
        await self.initialize()

        content = types.Content(
            role="user",
            parts=[types.Part(text=query)]
        )

        final_response = "No response"
        run_error = None

        # Partial delivery (F015a.A4 #2): a mid-run failure — notably an MCP 300s
        # timeout / McpError on a slow tool — must NOT discard results already
        # captured at the tool boundary (state['fedot_artifacts']). Swallow it here
        # and fall through to the deterministic finalizer below, which surfaces those
        # artifacts so the user still gets the molecules produced before the stall.
        try:
            async for event in self.runner.run_async(
                user_id=self.user_id,
                session_id=self.session_id,
                new_message=content,
                # ADK caps a run at 500 LLM calls by default, which a long
                # autonomous research run overruns mid-work; lift the ceiling so
                # one prompt can drive the whole job (finite, as a cost backstop).
                run_config=RunConfig(
                    max_llm_calls=get_settings().orchestrator.max_llm_calls
                ),
            ):
                if verbose:
                    print(
                        f"[Event] {event.author} | {type(event).__name__} | Final={event.is_final_response()}"
                    )

                if event.is_final_response():
                    if event.content and event.content.parts:
                        parts = event.content.parts
                        # Thinking models emit a separate `thought` part before the
                        # answer; parts[0] is often that reasoning. Prefer the
                        # non-thought answer text, falling back to any text so we
                        # never drop the response entirely.
                        answer = "\n".join(
                            p.text for p in parts
                            if getattr(p, "text", None) and not getattr(p, "thought", False)
                        )
                        final_response = answer or "\n".join(
                            p.text for p in parts if getattr(p, "text", None)
                        ) or ""
                    elif event.actions and event.actions.escalate:
                        final_response = f"Escalation: {getattr(event, 'error_message', None) or 'Unknown error'}"
        except Exception as exc:
            run_error = exc
            logger.error(
                f"run loop raised ({type(exc).__name__}: {str(exc)[:200]}); "
                "attempting partial delivery from captured S3 artifacts."
            )

        # Deterministic finalizer (F010.A5/A6): the orchestrator LLM sometimes drops a
        # successfully-generated result. The real molecules live behind a presigned S3 URL
        # that fedot_tool captured into state['fedot_artifacts']. If that result is not
        # already in the answer, DOWNLOAD the file and append a preview of its contents (read
        # from S3, not fabricated) plus the link, so generated molecules always reach the user.
        try:
            session = await self.session_service.get_session(
                app_name=self.app_name, user_id=self.user_id, session_id=self.session_id,
            )
            arts = (getattr(session, "state", None) or {}).get("fedot_artifacts") if session else None
        except Exception:
            arts = None
        if arts:
            missing = [a for a in arts if a.get("url") and a["url"] not in (final_response or "")]
            if missing:
                blocks = []
                for a in missing:
                    url = a["url"]
                    cnt = a.get("generated_count")
                    tag = f" ({cnt} molecules)" if cnt else ""
                    preview = await asyncio.to_thread(_s3_csv_preview, url)
                    block = f"**Generated molecules{tag}** — [download full CSV]({url})"
                    if preview:
                        block += f"\n```\n{preview}\n```"
                    blocks.append(block)
                final_response = (final_response or "").rstrip() + "\n\n---\n" + "\n\n".join(blocks)

        if not (final_response or "").strip():
            if run_error is not None:
                final_response = (
                    f"The run stopped early ({type(run_error).__name__}) before producing a result, "
                    "and no partial artifacts were captured. This is usually a slow MCP tool hitting "
                    "its timeout or a transient model/network error — please retry."
                )
            else:
                final_response = (
                    "I couldn't complete this request within the available steps — the orchestrator "
                    "did not reach a tool that produced a result. Please retry or narrow the request."
                )

        return final_response

    async def close(self):
        """Cleanup session-related resources and uploaded paper artifacts."""
        try:
            await asyncio.to_thread(cleanup_uploaded_papers, self.user_id, self.session_id)
        except Exception as exc:
            logger.error(f"Warning: failed to cleanup uploaded papers for session {self.session_id}: {exc}")

# Convenience functions
async def create_manager() -> CoScientistManager:
    """Create and initialize a CoScientistManager."""
    manager = CoScientistManager()
    await manager.initialize()
    return manager


# Export public API
__all__ = [
    # Main classes
    "CoScientistManager",
    # Models
    # Functions
    "create_manager"
]

# CLI entrypoint — thin shim. Prefer: python -m CoScientist cli
if __name__ == "__main__":
    from CoScientist.cli import run_repl

    run_repl()
