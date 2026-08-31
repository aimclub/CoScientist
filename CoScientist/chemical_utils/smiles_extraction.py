"""Pull SMILES-format molecules out of free-text RAG/literature-search answers.

The paper-analysis MCP tools (`explore_chemistry_database`, `explore_my_papers`)
are prompted to copy SMILES strings verbatim into their text answer (see
mcp-servers/paper-analysis-mcp-server/prompts.py, rule 7), but they hand back
plain prose — nothing marks *which* substring is a SMILES. This module finds
candidate tokens and keeps only the ones RDKit can actually parse, so a stray
word or abbreviation from the surrounding text never gets treated as a
molecule.
"""
import logging
import re
from typing import List

logger = logging.getLogger(__name__)

try:
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")  # RDKit logs a parse error per rejected candidate — silence that
    _RDKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - rdkit is an optional/transitive dependency
    Chem = None
    _RDKIT_AVAILABLE = False
    logger.warning("rdkit not installed — SMILES extraction from literature text is disabled.")

# Text is split on whitespace/quotes/markdown-table pipes; a SMILES never contains these.
_TOKEN_SPLIT_RE = re.compile(r"[\s,;|`\"'“”‘’]+")
# The characters SMILES is built from (organic subset + charges/rings/stereo).
_SMILES_CHARSET_RE = re.compile(r"^[A-Za-z0-9@+\-\[\]\(\)=#$:/\\%.]+$")
# Require at least one character that plain English words don't use, so bare
# words ("Instructions", "CoScientist") never reach the (expensive) RDKit check.
_SMILES_MARKER_RE = re.compile(r"[0-9@+#\[\]=]")

_MIN_LEN = 4
_MAX_LEN = 200


def _is_valid_smiles(token: str) -> bool:
    return _RDKIT_AVAILABLE and Chem.MolFromSmiles(token) is not None


def _canonical(token: str) -> str:
    if not _RDKIT_AVAILABLE:
        return token
    mol = Chem.MolFromSmiles(token)
    return Chem.MolToSmiles(mol) if mol is not None else token


def extract_smiles(text: str) -> List[str]:
    """Return the deduplicated, RDKit-canonicalized SMILES found in ``text``.

    Order is preserved (first occurrence wins); returns [] if RDKit is not
    installed or no candidate validates, never raises.
    """
    if not text or not _RDKIT_AVAILABLE:
        return []

    seen_canonical = set()
    results: List[str] = []

    for raw in _TOKEN_SPLIT_RE.split(text):
        for candidate in (raw, raw.rstrip(".")):
            if not (_MIN_LEN <= len(candidate) <= _MAX_LEN):
                continue
            if not _SMILES_MARKER_RE.search(candidate):
                continue
            if not _SMILES_CHARSET_RE.match(candidate):
                continue
            if not _is_valid_smiles(candidate):
                continue

            canonical = _canonical(candidate)
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                results.append(canonical)
            break  # accepted — don't also try the un-stripped/stripped sibling

    return results
