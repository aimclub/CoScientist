"""Semantic extraction for the knowledge graph (Option B).

ONE data-driven template — no class-per-entity. Everything the LLM pulls out of
an output text is an ``Entity`` (a typed thing) or a ``Relation`` (a typed link);
the *kind* of thing lives in a string ``type`` field, never in a Python subclass.
New entity/relation types therefore need zero code changes.

    Entity   : key (canonical id, for cross-run dedup) + type + name + attrs
    Relation : src key + dst key + type
    Extraction = {entities, relations}  ← exactly the LLM's JSON output schema

Extraction runs a small LLM over a final result. It is ON by default
(``KG_SEMANTIC_ENABLED=0`` turns it off) and fully best-effort — any failure
yields no new facts and never breaks a run.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

# Suggested vocabularies (open — the model may introduce others).
ENTITY_TYPES = ["target", "molecule", "metric", "property", "dataset",
                "method", "hypothesis", "paper", "finding", "organism", "gene"]
RELATION_TYPES = ["has_property", "about", "supports", "refutes", "generated_by",
                  "measured_by", "uses", "cites", "part_of", "compared_with"]


class Entity(BaseModel):
    key: str                       # canonical id for dedup, e.g. "molecule:CCO", "target:GSK-3beta"
    type: str                      # a known type (reused) or a new one
    name: str = ""                 # human-readable label
    description: str = ""           # one concise factual sentence about the entity
    attrs: Dict[str, Any] = Field(default_factory=dict)  # type-specific fields (smiles, value, unit, doi, …)


class Relation(BaseModel):
    src: str                       # source entity key
    dst: str                       # target entity key
    type: str                      # a SPECIFIC predicate (inhibits, treats, has_property, …)
    attrs: Dict[str, Any] = Field(default_factory=dict)  # qualifier of the fact (value, unit, assay, condition)


class Extraction(BaseModel):
    entities: List[Entity] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)


def semantic_enabled() -> bool:
    # On by default so the knowledge memory actually fills up and gets reused;
    # set KG_SEMANTIC_ENABLED=0 to turn the extraction LLM call off.
    return (os.getenv("KG_SEMANTIC_ENABLED") or "1") not in ("0", "false", "False", "")


_SYSTEM_PROMPT = (
    "You build a REUSABLE knowledge graph from an agent's output, for ANY domain "
    "(science, medicine, people, organizations, events, concepts). Capture the key entities and the "
    "factual CLAIMS the text actually states — concrete, informative things a FUTURE task could reuse.\n"
    "Return ONLY JSON: {\"entities\":[{\"key\",\"type\",\"name\",\"description\",\"attrs\"}],"
    "\"relations\":[{\"src\",\"dst\",\"type\",\"attrs\"}]}.\n"
    "TYPES — keep the schema small: PREFER the existing entity/relation types listed in the user message; "
    "introduce a NEW type ONLY when none of them fits. type = a short lowercase noun (entities) / predicate "
    "(relations).\n"
    "ENTITIES: any salient named thing. key='type:canonical-name' lowercase. Fill 'description' with ONE "
    "concise factual sentence, and put identifiers/values in attrs (smiles, doi, value, unit, date, role). "
    "Be informative — not just a bare name.\n"
    "RELATIONS: each is a CLAIM subject→predicate→object with a SPECIFIC predicate (inhibits, treats, "
    "has_property, measured_as, located_in, holds_position, founded, born_in, supports, compared_with, …). "
    "Put qualifiers/values in attrs. src/dst MUST be keys present in entities.\n"
    "EXCLUDE tautologies, taxonomy/'is-a' trivia, and vague 'about'/'related_to' links. Extract only what the "
    "text states; if nothing concrete, return empty lists.\n"
    "Example: 'paracetamol inhibits COX-2; logP 0.46' → entities [{key:'molecule:paracetamol',type:'molecule',"
    "name:'paracetamol',description:'A common analgesic/antipyretic drug.',attrs:{logP:0.46}},"
    "{key:'target:cox-2',type:'target',name:'COX-2',description:'Cyclooxygenase-2 enzyme.'}], "
    "relations [{src:'molecule:paracetamol',dst:'target:cox-2',type:'inhibits'}]."
)


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def parse_extraction(raw: str) -> Extraction:
    """Parse the model's JSON into the template; tolerant of noise/fences."""
    try:
        data = json.loads(_strip_json(raw))
    except Exception:
        try:
            from CoScientist.agents.llm_repair import repair_json  # type: ignore
            data = json.loads(repair_json(_strip_json(raw)))
        except Exception:
            return Extraction()
    try:
        return Extraction.model_validate(data)
    except Exception:
        # salvage entities/relations individually
        ents, rels = [], []
        for e in (data.get("entities") or []):
            try: ents.append(Entity.model_validate(e))
            except Exception: pass
        for r in (data.get("relations") or []):
            try: rels.append(Relation.model_validate(r))
            except Exception: pass
        return Extraction(entities=ents, relations=rels)


# Pluggable completion fn (text -> str), so tests can inject a fake LLM.
CompletionFn = Callable[[str, str], Any]


async def _llm_complete(system: str, user: str) -> str:
    import litellm
    from CoScientist.config import get_settings
    s = get_settings().llm
    model = os.getenv("KG_SEMANTIC_MODEL") or s.main_model
    resp = await litellm.acompletion(
        model=model, api_base=s.main_url, api_key=s.openai_api_key,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    # Extraction runs as a detached background task, so it bills the session
    # that spawned it via the ambient binding rather than a passed-down key.
    from CoScientist.logging.metrics import record_completion
    record_completion(resp, model=model, agent="SemanticMemory")
    return resp.choices[0].message.content or ""


def _schema_hint(known_types) -> str:
    """Inject the EXISTING entity/relation types so the model reuses them
    (dynamic schema — keeps types from proliferating)."""
    if not known_types:
        return ""
    ent, rel = known_types
    return (
        "EXISTING TYPES — reuse one of these if it fits; add a new type only if none does.\n"
        f"  entity types: {sorted(ent) or ENTITY_TYPES}\n"
        f"  relation types: {sorted(rel) or RELATION_TYPES}\n\n"
    )


async def extract(text: str, context: str = "", known_types=None,
                  complete: Optional[CompletionFn] = None) -> Extraction:
    """Extract entities/relations from a text. Empty when disabled or on failure.

    known_types = (entity_types, relation_types) already in the graph; passed to
    the model so it reuses them instead of inventing near-duplicates.
    """
    if not semantic_enabled() or not (text or "").strip():
        return Extraction()
    user = (
        _schema_hint(known_types)
        + (f"CONTEXT (the task): {context}\n\n" if context else "")
        + f"OUTPUT TEXT:\n{text[:6000]}"
    )
    try:
        raw = await (complete or _llm_complete)(_SYSTEM_PROMPT, user)
    except Exception:
        return Extraction()
    return parse_extraction(raw if isinstance(raw, str) else str(raw))
