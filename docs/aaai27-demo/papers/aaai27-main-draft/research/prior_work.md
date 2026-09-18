# Prior-work review (round 2) — verified

_All arXiv ids verified during search; no fabricated citations. Blog/announcement/Nature-only items flagged._

## Headline
Thesis claims 1, 2, 4 are well-supported; claim 3 ("frozen catalogue removes limited-tools + stochasticity + cost") is **partially contested** (costs are falling; catalogues already exist). **The single biggest risk is NOVELTY, not correctness:** Paper2Agent (2509.06917), ToolMaker (2502.11705, ACL-25) and ToolUniverse (2509.23426) — all 2025 — already occupy "auto-convert repos/papers → verified, served, reproducible MCP tools" and "growing scientific-tool catalogue." **We must state a crisp delta or risk a desk-reject.**

**Defensible delta:** the generalising **planner → action-graph → executor system that *consumes* a growing verified catalogue across domains/studies**, with quantified conversion+verification cost and reproducibility gains — that integration/consumption angle is the un-taken ground. Not "we convert repos."

## Two strategic corrections to the framing
1. **Lead claim 1 with determinism/reproducibility, NOT cost.** Token cost is collapsing (Stanford AI Index 2025: ~280× drop in ~18 mo) — "expensive" is a live counterargument. But nondeterminism is *architectural* (Thinking Machines, `he2025nondeterminism`): temp-0 inference still varies run-to-run. That argument survives cheaper tokens.
2. **Frame hybrid, not catalogue-only:** catalogue-first with coder-agent fallback for genuinely novel experiments. Otherwise claim 3 overclaims and "frozen tools ossify" bites.

## Evidence by claim
- **C1 (coder execution stochastic & expensive):** `he2025nondeterminism` (temp-0 nondeterminism, core), `pimentel2024notebooks` (~8.5% of biomedical Jupyter notebooks reproduce), SWE-bench Pro cost/pass collapse, `lu2024aiscientist`, `google2025coscientist`.
- **C2 (scientific tool coverage too sparse):** `boiko2023coscientist` (small fixed toolset), `bran2024chemcrow` (18 hand-built tools), `swanson2025virtuallab` (bespoke pipeline); MCP quality studies `mcpquality2025`/`hou2025mcpsurvey` (many servers low-quality → *reliable* coverage sparse). Nuance: `gao2025tooluniverse` (600+ tools) challenges "no ecosystem" → reframe C2 as *coverage of arbitrary domain repos*.
- **C3 (freeze → removes limited-tools+stochasticity+cost):** `cai2024latm` (freeze made tool ↓cost/variance), `yuan2024craft` (reusable *validated* toolset), `wang2023voyager` (growing verified skill library). Contested by falling costs + existing catalogues → soften to hybrid.
- **C4 (open reusable ecosystem for scientific code):** `wang2023voyager`, `yuan2024craft`, RSE/reproducibility movement (WSSSPE, ReScience). `gao2025tooluniverse` both supports (ecosystems valuable) and competes.

## Closest competitors (must position against, related work)
- **`miao2025paper2agent` (Paper2Agent, 2509.06917):** paper+code → MCP server, iteratively tested, tools *locked to reproduce reference results*. Almost verbatim our "verified/served/reproducible." **Delta:** we operate from arbitrary repos (not paper-anchored), integrate into a general planning system, and grow a cross-domain catalogue; honest cost/failure accounting.
- **`wolflein2025toolmaker_acl` (ToolMaker, ACL-25):** repo+task → tool via closed-loop unit-test self-correction; 15 tasks/80%. **Delta:** we serve as MCP + code-enforced gates + split-env determinism + catalogue reuse; we *use TM-Bench as the gold eval* rather than propose a rival converter.
- **`gao2025tooluniverse` (ToolUniverse):** 600+ tool ecosystem, creates tools from NL. **Delta:** repo-grounded verified conversion vs NL-spec tools; determinism via frozen code.
- **`code2mcp2025`, `toolrosella2026`:** repo→MCP but validation is import-smoke / LLM-judge (no gold) — weaker verification; we cite as converters and contrast our live-invocation-on-held-out-gold validation.

## Counterarguments to preempt (Discussion)
1. Coder agents getting cheap → rebut with determinism, not cost.
2. Mechanism already published (Paper2Agent/ToolMaker) → rebut with system-consumption + cross-domain generalisation delta.
3. Ecosystem already exists (ToolUniverse) → reframe C2 to arbitrary-repo coverage.
4. Conversion/verification cost may dominate → quantify it honestly (our audit: 0/81 hallucinated, but hollow-validation & incomplete conversions real).
5. Frozen tools ossify → hybrid catalogue-first + coder-fallback.

## Cite list: see references.bib keys
boiko2023coscistient/bran2024chemcrow/lu2024aiscientist/google2025coscientist/swanson2025virtuallab/
he2025nondeterminism/pimentel2024notebooks/cai2024latm/yuan2024craft/wang2023voyager/schick2023toolformer/
wolflein2025toolmaker_acl/miao2025paper2agent/gao2025tooluniverse/code2mcp2025/toolrosella2026/
mcp2024/hou2025mcpsurvey/mcpquality2025.
