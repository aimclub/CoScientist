"""
MooseChemMCPTool — connects to the MooseChem MCP server via HTTP.

Replaces the simplified MooseChemTool with the original MOOSE-Chem EA pipeline
(evolutionary algorithm, multi-round screening, self-refinement) running in a
Docker container exposed via MCP protocol.

Pipeline:
    1. build_corpus  — collect PubMed + OpenAlex corpus
    2. run_moosechem — run original MOOSE-Chem EA pipeline (bash main.sh)
    3. get_hypotheses — read evaluation results + LLM-extracted tools
    4. Return rich Hypothesis objects for HypothesisLoopCoordinator

BaseHypothesisTool contract is fully preserved:
    - validate_query(HypothesisQuery) -> bool
    - invoke(HypothesisQuery) -> ToolResult
    - strategy_type: str
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from CoScientist.config import get_settings
from CoScientist.hypothesis_subsystem.base_tool import BaseHypothesisTool
from CoScientist.hypothesis_subsystem.models import (
    Hypothesis,
    HypothesisQuery,
    HypothesisStatus,
    Provenance,
    Reference,
    ScaleType,
    ToolResult,
    ValidationToolInfo,
    Variable,
    Variables,
)

_settings = get_settings()

# NOTE: deliberately a TOP-LEVEL logger name. ``CoScientist.*`` loggers are
# configured by the app with their own handlers and ``propagate=False``, so a
# ``CoScientist.hypothesis_subsystem.moosechem_mcp_tool`` logger never reaches
# the root console handler the integration test attaches — which is why the MCP
# progress was invisible. A top-level name propagates to root exactly like the
# ``hypothesis_subsystem`` audit logger, so it shows up live in the console and
# in the per-case captured log.
logger = logging.getLogger("moosechem_mcp")

# ---------------------------------------------------------------------------
# Online trace file (for offline analysis / ground-truth comparison)
# ---------------------------------------------------------------------------
# When MOOSECHEM_TRACE_DIR is set, every MCP request/response and every
# hypothesis the pipeline produces (BEFORE the critic runs — so rejected ones
# are kept too) is appended, one JSON object per line, flushed immediately.
_TRACE_DIR_ENV = "MOOSECHEM_TRACE_DIR"
_TRACE_RESULT_LIMIT = 40000  # chars — cap huge MCP payloads in the trace


def _truncate_json(value: Any, limit: int = _TRACE_RESULT_LIMIT) -> Any:
    """JSON-safe, size-capped rendering of a value for the trace file."""
    try:
        s = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        s = repr(value)
    if len(s) > limit:
        return {"_truncated": True, "_chars": len(s), "preview": s[:limit]}
    return value


def _write_trace(event: str, payload: Dict[str, Any]) -> None:
    """Append one trace record (flushed) when a trace dir is configured."""
    trace_dir = os.getenv(_TRACE_DIR_ENV)
    if not trace_dir:
        return
    try:
        os.makedirs(trace_dir, exist_ok=True)
        path = os.path.join(trace_dir, "moosechem_trace.jsonl")
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()
    except Exception:  # noqa: BLE001 — tracing must never break a run
        pass

# MCP server URL from settings or fallback to localhost
MOOSECHEM_MCP_URL: str = (
    getattr(getattr(_settings, "mcp", None), "moosechem_url", None)
    or "http://localhost:7335/mcp"
)

# Polling intervals and timeouts
POLL_INTERVAL_CORPUS = 10       # seconds between corpus status checks
POLL_INTERVAL_MOOSECHEM = 30    # seconds between moosechem job checks
MAX_CORPUS_WAIT = 300           # 5 minutes max for corpus build
MAX_MOOSECHEM_WAIT = 5400       # 90 minutes max for MOOSE-Chem EA pipeline


def _parse_mcp_response(raw_text: str) -> Dict[str, Any]:
    """Parse MCP response — handles both plain JSON and SSE (event/data) format."""
    raw_text = raw_text.strip()
    if not raw_text:
        return {}
    # SSE format: lines like "event: message\ndata: {...}"
    if raw_text.startswith("event:") or "\ndata:" in raw_text or raw_text.startswith("data:"):
        for line in raw_text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        return {}
    # Plain JSON
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {}


def _build_variables(raw_vars: Dict[str, Any]) -> Variables:
    """Build a Variables object from the MCP-provided dict (already validated
    server-side, but we defensively re-validate scale and required fields)."""
    valid_scales = {"nominal", "ordinal", "interval", "ratio"}

    def _mk(lst):
        out = []
        for v in (lst or []):
            if not isinstance(v, dict):
                continue
            name = str(v.get("name") or "variable").strip()
            desc = str(v.get("description") or name).strip()
            unit = v.get("unit")
            unit = str(unit) if unit not in (None, "", "null") else None
            scale = str(v.get("scale") or "nominal").strip().lower()
            if scale not in valid_scales:
                scale = "nominal"
            out.append(Variable(name=name, description=desc, unit=unit, scale=ScaleType(scale)))
        return out

    if not isinstance(raw_vars, dict):
        raw_vars = {}
    return Variables(
        independent=_mk(raw_vars.get("independent")),
        dependent=_mk(raw_vars.get("dependent")),
        covariates=_mk(raw_vars.get("covariates")),
    )


def checkpoint_dir_for_query(research_question: str, background_survey: str = "") -> str:
    """Stable per-query checkpoint dir that does not collapse non-ASCII text.

    The previous slug ``re.sub(r'[^a-z0-9_]', '_', question[:40]) + "_mcp"``
    stripped every Cyrillic character, so every Russian prompt hashed to the
    same directory ``_mcp`` and MOOSE-Chem reused another user's cached run.
    """
    key = "\n".join([
        unicodedata.normalize("NFC", research_question or "").strip(),
        unicodedata.normalize("NFC", background_survey or "").strip(),
    ])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"hyp_{digest}_mcp"


def _split_claim_and_plan(text: str) -> tuple[str, str]:
    """Split hypothesis text into claim (before first '1.') and verification plan."""
    match = re.search(r'\n\s*1\.', text)
    if match:
        claim = text[:match.start()].strip()
        plan = text[match.start():].strip()
    else:
        # No numbered list found — use first 300 chars as claim
        claim = text.strip()  # full text when no numbered plan section found
        plan = text
    # Full plan preserved — hypotheses now bypass the LLM round-trip (read
    # from state), so the critic sees the complete MOOSE-Chem methodology.
    # No truncation — hypotheses bypass the LLM round-trip (read from state),
    # so the critic receives the complete MOOSE-Chem claim and plan.
    return claim, plan


class MooseChemMCPTool(BaseHypothesisTool):
    """
    Hypothesis generation via the original MOOSE-Chem EA pipeline.

    Connects to the MooseChem MCP server (Docker) via HTTP JSON-RPC.
    Returns rich Hypothesis objects with claim, verification_plan,
    LLM-extracted tools, and evidence_basis (inspiration title + abstract)
    — everything required by HypothesisLoopCoordinator and HypothesisCriticAgent.
    """

    strategy_type = "MooseChem"

    def __init__(self, mcp_url: Optional[str] = None):
        self._mcp_url = mcp_url or MOOSECHEM_MCP_URL
        self._session_id: Optional[str] = None
        logger.info("[MooseChemMCP] client initialised -> %s", self._mcp_url)

    # ------------------------------------------------------------------ #
    # BaseHypothesisTool contract                                          #
    # ------------------------------------------------------------------ #

    def validate_query(self, query: HypothesisQuery) -> bool:
        return bool(query.research_question.strip())

    async def invoke(self, query: HypothesisQuery) -> ToolResult:
        """Run the full MOOSE-Chem pipeline via MCP and return ToolResult."""
        start_time = time.monotonic()
        self._session_id = None
        logger.info(
            "[MooseChemMCP] invoke START q='%s' max_hypotheses=%s url=%s",
            query.research_question[:160], query.max_hypotheses, self._mcp_url,
        )
        _write_trace("invoke_start", {
            "research_question": query.research_question,
            "background_survey": query.background_survey,
            "max_hypotheses": query.max_hypotheses,
            "mcp_url": self._mcp_url,
        })

        try:
            async with aiohttp.ClientSession() as session:
                await self._init_session(session)

                # Step 1: build PubMed + OpenAlex corpus
                corpus_job_id = await self._build_corpus(session, query)
                if not corpus_job_id:
                    return self._error("Failed to start corpus build.", start_time)

                corpus_meta = await self._wait_corpus(session, corpus_job_id)
                if not corpus_meta:
                    return self._error("Corpus build failed or timed out.", start_time)

                # Step 2: run MOOSE-Chem EA pipeline
                job_id = await self._run_moosechem(
                    session, query, corpus_meta, corpus_job_id=corpus_job_id
                )
                if not job_id:
                    return self._error("Failed to start MOOSE-Chem job.", start_time)

                if not await self._wait_moosechem(session, job_id):
                    return self._error("MOOSE-Chem job failed or timed out.", start_time)

                # Step 3: fetch hypotheses for THIS job only (never the
                # container-global latest success — that leaks other users).
                raw_hypotheses = await self._get_hypotheses(
                    session, query.max_hypotheses, job_id=job_id
                )

            # ---- Tool catalog: match hypotheses to available validation tools ----
            tool_catalog = query.tool_catalog
            hypotheses = [
                self._to_hypothesis(h, tool_catalog) for h in raw_hypotheses
            ]
            duration_ms = (time.monotonic() - start_time) * 1000

            logger.info(
                "[MooseChemMCP] invoke DONE hyps=%d corpus_job=%s moosechem_job=%s %.0fms",
                len(hypotheses), corpus_job_id, job_id, duration_ms,
            )
            # Persist EVERY generated hypothesis (before the critic runs), so
            # rejected/deferred ones are available for offline analysis too.
            _write_trace("raw_hypotheses", {
                "corpus_job_id": corpus_job_id,
                "moosechem_job_id": job_id,
                "count": len(hypotheses),
                "hypotheses": [
                    h.model_dump(mode="json") if hasattr(h, "model_dump") else h
                    for h in hypotheses
                ],
            })
            return ToolResult(
                strategy_type=self.strategy_type,
                hypotheses=hypotheses,
                metadata={
                    "corpus_job_id": corpus_job_id,
                    "moosechem_job_id": job_id,
                    "total_hypotheses": len(hypotheses),
                    "duration_ms": round(duration_ms, 1),
                },
                success=True,
            )

        except Exception as exc:
            logger.exception("[MooseChemMCP] invoke FAILED: %s", exc)
            _write_trace("invoke_error", {"error": str(exc)})
            return self._error(str(exc), start_time)

    # ------------------------------------------------------------------ #
    # MCP JSON-RPC helpers                                                 #
    # ------------------------------------------------------------------ #

    async def _init_session(self, session: aiohttp.ClientSession) -> None:
        """Initialize MCP session and capture session-id from response headers."""
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "MooseChemMCPTool", "version": "1.0"},
            },
            "id": 0,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with session.post(
            self._mcp_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]

    async def _call_tool(
        self,
        session: aiohttp.ClientSession,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_sec: int = 30,
    ) -> Dict[str, Any]:
        """Call a tool on the MCP server via JSON-RPC and return parsed response."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 1,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        logger.info(
            "[MooseChemMCP] -> call tool=%s args=%s (url=%s)",
            tool_name, _redact_args(arguments), self._mcp_url,
        )
        _write_trace("mcp_request", {
            "tool": tool_name,
            "arguments": _truncate_json(arguments, 4000),
        })
        _t0 = time.monotonic()
        async with session.post(
            self._mcp_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]
            raw_text = await resp.text()
            data = _parse_mcp_response(raw_text)

        # FastMCP returns content as list of {type, text} objects
        result = data.get("result", {})
        content = result.get("content", [])
        parsed: Dict[str, Any]
        if content and isinstance(content, list):
            text = content[0].get("text", "{}")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"answer": text}
        else:
            parsed = result
        logger.info(
            "[MooseChemMCP] <- tool=%s ok=%.0fms status=%s",
            tool_name, (time.monotonic() - _t0) * 1000.0, _summarize_mcp_result(tool_name, parsed),
        )
        _write_trace("mcp_response", {
            "tool": tool_name,
            "elapsed_ms": round((time.monotonic() - _t0) * 1000.0, 1),
            "response": _truncate_json(parsed),
        })
        return parsed

    # ------------------------------------------------------------------ #
    # Pipeline steps                                                       #
    # ------------------------------------------------------------------ #

    async def _build_corpus(
        self, session: aiohttp.ClientSession, query: HypothesisQuery
    ) -> str:
        """Start corpus build job. Returns corpus_job_id immediately."""
        result = await self._call_tool(
            session,
            "build_corpus",
            {
                "research_question": query.research_question,
                "background_survey": query.background_survey or "",
            },
        )
        meta = result.get("metadata", result)
        return meta.get("corpus_job_id", meta.get("job_id", ""))

    async def _wait_corpus(
        self, session: aiohttp.ClientSession, corpus_job_id: str
    ) -> Optional[Dict[str, Any]]:
        """Poll corpus status until success or failure.

        Returns the job metadata (including corpus_path / background_path) on
        success so the subsequent run_moosechem call is bound to this corpus,
        not the container-global default files.
        """
        t0 = time.monotonic()
        deadline = t0 + MAX_CORPUS_WAIT
        logger.info("[MooseChemMCP] corpus build polling started (job=%s, max=%ds)",
                    corpus_job_id, MAX_CORPUS_WAIT)
        while time.monotonic() < deadline:
            result = await self._call_tool(
                session, "check_corpus_status", {"corpus_job_id": corpus_job_id}
            )
            meta = result.get("metadata", result)
            status = meta.get("status", "")
            logger.info("[MooseChemMCP] corpus heartbeat elapsed=%.0fs status=%s",
                        time.monotonic() - t0, status or "?")
            if status == "success":
                return meta if isinstance(meta, dict) else {}
            if status == "failed":
                return None
            await asyncio.sleep(POLL_INTERVAL_CORPUS)
        logger.warning("[MooseChemMCP] corpus build timed out after %ds", MAX_CORPUS_WAIT)
        return None

    async def _run_moosechem(
        self,
        session: aiohttp.ClientSession,
        query: HypothesisQuery,
        corpus_meta: Optional[Dict[str, Any]] = None,
        corpus_job_id: Optional[str] = None,
    ) -> str:
        """Start MOOSE-Chem EA pipeline. Returns job_id immediately."""
        arguments: Dict[str, Any] = {
            "checkpoint_dir": checkpoint_dir_for_query(
                query.research_question, query.background_survey or ""
            ),
        }
        if corpus_job_id:
            arguments["corpus_job_id"] = corpus_job_id
        if corpus_meta:
            if corpus_meta.get("corpus_path"):
                arguments["corpus_path"] = corpus_meta["corpus_path"]
            if corpus_meta.get("background_path"):
                arguments["background_path"] = corpus_meta["background_path"]
        result = await self._call_tool(
            session,
            "run_moosechem",
            arguments,
        )
        meta = result.get("metadata", result)
        return meta.get("job_id", "")

    async def _wait_moosechem(
        self, session: aiohttp.ClientSession, job_id: str
    ) -> bool:
        """Poll MOOSE-Chem job status until success or failure."""
        t0 = time.monotonic()
        deadline = t0 + MAX_MOOSECHEM_WAIT
        logger.info(
            "[MooseChemMCP] MOOSE-Chem generation polling started (job=%s, max=%ds)",
            job_id, MAX_MOOSECHEM_WAIT,
        )
        while time.monotonic() < deadline:
            result = await self._call_tool(
                session, "check_moosechem_status", {"job_id": job_id}
            )
            meta = result.get("metadata", result) or {}
            status = meta.get("status", "")
            logger.info(
                "[MooseChemMCP] moosechem heartbeat elapsed=%.0fs status=%s (alive)",
                time.monotonic() - t0, status or "?",
            )
            if status == "success":
                return True
            if status == "failed":
                logger.error("[MooseChemMCP] moosechem job FAILED: %s",
                             meta.get("error") or meta)
                return False
            await asyncio.sleep(POLL_INTERVAL_MOOSECHEM)
        logger.error("[MooseChemMCP] moosechem job timed out after %ds", MAX_MOOSECHEM_WAIT)
        return False

    async def _get_hypotheses(
        self,
        session: aiohttp.ClientSession,
        max_hypotheses: int,
        job_id: str,
    ) -> List[Dict[str, Any]]:
        # Cap at 3 (reverted from the 5-hypothesis experiment).
        max_hypotheses = min(max_hypotheses, 3)
        logger.info("[MooseChemMCP] fetching hypotheses (job=%s, top_n=%d)",
                    job_id, max_hypotheses)
        """Fetch top hypotheses from the completed MOOSE-Chem job."""
        # [experiment: increased hypothesis budget] get_hypotheses now does
        # an LLM call (tools + variables extraction) per hypothesis on the
        # server side, with untruncated abstracts. At 5 hypotheses this can
        # exceed the default 30s client timeout -> raised to 180s here only.
        result = await self._call_tool(
            session,
            "get_hypotheses",
            {"job_id": job_id, "top_n": max_hypotheses, "min_score": 0.0},
            timeout_sec=180,
        )
        return result.get("metadata", {}).get("hypotheses", [])

    # ------------------------------------------------------------------ #
    # Conversion to Hypothesis Pydantic model                             #
    # ------------------------------------------------------------------ #

    def _match_tools(self, hypothesis_tools: List[str], catalog) -> List[dict]:
        """Match hypothesis tools against the available validation tool catalog.

        Returns a list of matching ValidationToolInfo dicts (serialisable).
        """
        if catalog is None or not catalog.tools:
            return []
        matches = []
        for ht in hypothesis_tools:
            ht_lower = ht.lower()
            for vt in catalog.tools:
                if ht_lower in vt.name.lower() or ht_lower in vt.description.lower():
                    matches.append(vt.model_dump(mode="json"))
                    break
        return matches

    def _to_hypothesis(
        self, raw: Dict[str, Any], tool_catalog: "ToolCatalog | None" = None
    ) -> Hypothesis:
        """
        Convert a raw dict from MCP get_hypotheses into a rich Hypothesis object.

        raw fields:
            text               — full MOOSE-Chem hypothesis text
            score              — MOOSE-Chem score (0-4)
            criteria_scores    — [novelty, plausibility, falsifiability, utility]
            inspiration        — title of the inspiration paper
            inspiration_abstract — abstract of the inspiration paper from corpus
            tools              — methods extracted by LLM inside MCP server
        """
        full_text = raw.get("text", "")

        # Split text into claim (short assertion) and verification_plan (methodology)
        claim, verification_plan = _split_claim_and_plan(full_text)

        # Tools were extracted by LLM inside MCP server — use directly
        tools: List[str] = raw.get("tools") or []

        # Build reasoning with MOOSE-Chem score and criteria
        reasoning = full_text  # full MOOSE-Chem reasoning (no truncation)
        if raw.get("score") is not None:
            criteria = raw.get("criteria_scores", [])
            reasoning += (
                f"\n\n[MooseChem Score: {raw['score']}/4"
                + (f", criteria: {criteria}" if criteria else "")
                + "]"
            )

        # Evidence basis: inspiration paper with full title and abstract
        evidence_basis: List[Reference] = []
        inspiration_title = raw.get("inspiration", "")
        inspiration_abstract = raw.get("inspiration_abstract")
        if inspiration_title and inspiration_title not in ("None", ""):
            evidence_basis.append(Reference(
                title=inspiration_title,
                description=inspiration_abstract if inspiration_abstract else None,  # no truncation
            ))

        # Variables extracted by LLM inside MCP server (validated format)
        variables = _build_variables(raw.get("variables", {}))

        # Match hypothesis tools against available validation tools
        validation_matches = self._match_tools(tools, tool_catalog)

        return Hypothesis(
            claim=claim or full_text[:300],
            domain="chemistry",
            variables=variables,
            reasoning=reasoning,
            strategy_type=self.strategy_type,
            verification_plan=verification_plan,
            tools=tools,
            refutation_conditions=(
                "MOOSE-Chem score below threshold "
                "or critic rejection after 3 refinement rounds"
            ),
            evidence_basis=evidence_basis,
            status=HypothesisStatus.PROPOSED,
            provenance=Provenance(creator="MooseChemMCPTool"),
            validation_tool_matching=[
                ValidationToolInfo(**m) for m in validation_matches
            ],
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _error(self, message: str, start_time: float) -> ToolResult:
        """Return a failed ToolResult with duration metadata."""
        duration_ms = (time.monotonic() - start_time) * 1000
        return ToolResult(
            strategy_type=self.strategy_type,
            hypotheses=[],
            metadata={"duration_ms": round(duration_ms, 1)},
            success=False,
            error_message=message,
        )


# --------------------------------------------------------------------------- #
# Module-level logging helpers (kept OUT of the class body).                   #
# --------------------------------------------------------------------------- #

def _redact_args(arguments: Dict[str, Any]) -> str:
    """Compact, log-safe rendering of MCP tool arguments."""
    try:
        shown = {
            k: (v if not isinstance(v, str) or len(v) <= 200 else v[:200] + "...")
            for k, v in arguments.items()
        }
        return json.dumps(shown, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — logging must never break a call
        return repr(arguments)[:300]


def _summarize_mcp_result(tool_name: str, parsed: Dict[str, Any]) -> str:
    """One-line, log-safe summary of an MCP tool response."""
    try:
        meta = parsed.get("metadata", parsed) if isinstance(parsed, dict) else {}
        if tool_name == "get_hypotheses":
            hyps = (meta or {}).get("hypotheses", []) if isinstance(meta, dict) else []
            return f"hypotheses={len(hyps)}"
        if isinstance(meta, dict):
            status = meta.get("status")
            job = meta.get("job_id") or meta.get("corpus_job_id")
            if status or job:
                return f"status={status} job={job}"
        return "ok"
    except Exception:  # noqa: BLE001
        return "ok"
