"""A few lines on what one agent did, written on request by a small model.

The execution log shows an agent's task, its final report, its tool calls and
its artifacts — everything, which is more than a reader wants when the
question is only "what happened here". The panel offers a button; this module
turns the agent's trace into a short prompt, asks a cheap model, and remembers
the answer so a second click (or another reader) costs nothing.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

_TRACE_LIMIT = 14_000          # characters of trace handed to the model
_ARGS, _RESULT, _REPORT = 300, 400, 1_500
_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_CACHE_SIZE = 256

_LANGUAGE = {"ru": "Russian", "en": "English"}

_SYSTEM = (
    "You summarize one agent's run inside a multi-agent research system for a "
    "human reader. You are given the agent's task, the tool calls it made in "
    "order (with arguments and results, cut for length), the files and links "
    "it produced, and its final report. Write in {language}, at most 160 words, "
    "as a short markdown document:\n"
    "- first line: one bold sentence saying what this run achieved;\n"
    "- then '### {h_done}' with 2-4 bullets on what was done;\n"
    "- then '### {h_tools}' with one bullet per tool used, saying what for;\n"
    "- then '### {h_result}' with the outcome: numbers, files, links;\n"
    "- then '### {h_issues}' only if something failed or was left undone.\n"
    "State only what the trace shows; do not guess or pad. Use inline code "
    "for tool names, file names and commands. No preamble, no closing line."
)

_HEADINGS = {
    "ru": {"h_done": "Что сделано", "h_tools": "Инструменты", "h_result": "Результат", "h_issues": "Проблемы"},
    "en": {"h_done": "What was done", "h_tools": "Tools", "h_result": "Outcome", "h_issues": "Issues"},
}


def _cut(value: Any, limit: int) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _secs(node: Dict[str, Any]) -> str:
    start, end = node.get("t_start"), node.get("t_end")
    if start is None or end is None:
        return ""
    s = end - start
    return f"{s:.1f}s" if s < 60 else f"{int(s // 60)}m {int(s % 60)}s"


def trace_of(node: Dict[str, Any]) -> str:
    """The agent's run as plain text a small model can read in one go."""
    name = node.get("executor_agent") or node.get("label") or "agent"
    lines: List[str] = [f"AGENT: {name}"]
    if node.get("runs", 1) > 1:
        lines.append(f"RUN: {node.get('run')} of {node.get('runs')} in this request")
    if node.get("status"):
        lines.append(f"STATUS: {node['status']}" + (f" ({_secs(node)})" if _secs(node) else ""))
    if node.get("input"):
        lines.append("TASK: " + _cut(node["input"], _REPORT))
    calls = node.get("calls") or []
    if calls:
        lines.append(f"TOOL CALLS ({len(calls)}):")
        for i, c in enumerate(calls, 1):
            head = f"{i}. {c.get('tool') or 'call'} [{c.get('status') or '?'}"
            if c.get("duration") is not None:
                head += f", {c['duration']:.1f}s"
            head += "]"
            lines.append(head)
            if c.get("input"):
                lines.append("   args: " + _cut(c["input"], _ARGS))
            if c.get("output"):
                lines.append("   result: " + _cut(c["output"], _RESULT))
            files = list(c.get("output_files") or [])
            if files:
                lines.append("   files: " + ", ".join(files[:6]))
    else:
        lines.append("TOOL CALLS: none")
    artifacts = [a.get("uri") for a in (node.get("artifacts") or []) if a.get("uri")]
    if artifacts:
        lines.append("ARTIFACTS: " + ", ".join(artifacts[:12]))
    if node.get("output"):
        lines.append("FINAL REPORT: " + _cut(node["output"], _REPORT))
    text = "\n".join(lines)
    if len(text) > _TRACE_LIMIT:
        text = text[:_TRACE_LIMIT] + "\n… [trace cut for length]"
    return text


def model_name() -> Tuple[Optional[str], Optional[str]]:
    """(model, api_base): the dedicated small model, else the one named in
    ``summary_url`` ("base;model"), else the main model."""
    from CoScientist.config import get_settings
    s = get_settings().llm
    if s.agent_summary_model:
        return s.agent_summary_model, s.main_url
    if s.summary_url and ";" in s.summary_url:
        base, model = s.summary_url.split(";", 1)
        return model.strip() or s.main_model, base.strip() or s.main_url
    return s.main_model, s.main_url


async def _complete(system: str, user: str) -> Tuple[str, str]:
    import litellm
    from CoScientist.config import get_settings
    s = get_settings().llm
    model, base = model_name()
    if not model:
        raise RuntimeError("no model configured: set LLM__AGENT_SUMMARY_MODEL or LLM__MAIN_MODEL")
    resp = await litellm.acompletion(
        model=model, api_base=base, api_key=s.openai_api_key,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0, timeout=s.request_timeout,
    )
    try:
        from CoScientist.logging.metrics import record_completion
        record_completion(resp, model=model, agent="AgentSummary")
    except Exception:  # noqa: BLE001 — accounting must not fail the answer
        pass
    return (resp.choices[0].message.content or "").strip(), model


def _key(scope: str, trace: str, lang: str) -> str:
    return hashlib.sha1(f"{scope}|{lang}|{trace}".encode("utf-8")).hexdigest()


async def summarize(node: Dict[str, Any], *, lang: str = "ru",
                    scope: str = "", force: bool = False) -> Dict[str, Any]:
    """``{"summary", "model", "cached"}`` for one agent node of the execution
    tree. Cached on the trace itself, so a node that has not changed is never
    sent twice and a running agent gets a fresh summary once it moved on;
    ``force`` asks the model again regardless (the panel's "regenerate")."""
    lang = lang if lang in _LANGUAGE else "ru"
    trace = trace_of(node)
    key = _key(scope, trace, lang)
    hit = None if force else _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return dict(hit, cached=True)
    system = _SYSTEM.format(language=_LANGUAGE[lang], **_HEADINGS[lang])
    summary, model = await _complete(system, trace)
    entry = {"summary": summary, "model": model, "cached": False}
    _CACHE[key] = entry
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return entry
