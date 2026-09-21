"""Assemble a contract-valid ``values`` document from the run's evidence.

The split of labour here is deliberate. The *structure* — section ids, block
types, figure placement, table shape, reference numbering, appendices — is built
by this module, deterministically. The *prose* is written by the agent and
arrives as plain paragraphs keyed by section id.

Two reasons for drawing the line there. The contract is closed-world, so a
single unexpected key is a rejection; a model emitting block dicts would trip
that eventually, and the failure would be a wasted round trip with a cryptic
path in the error. And the agent never has to serialise an image: figures are
placed here from files already on disk, with the asset name the encoder chose.

Every builder function tolerates missing input. A run with no hypotheses, no
figures or no literature still yields a document that validates, because the
contract's ``must`` arrays each get a grounded fallback rather than an empty
list.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from CoScientist.reporting.nir import contract
from CoScientist.reporting.nir.assets import AssetBundle
from CoScientist.reporting.nir.evidence import NirEvidence

logger = logging.getLogger(__name__)

REPOSITORY_URL = "https://github.com/aimclub/CoScientist"

#: A table wider than this is unreadable at 12 pt inside a 165 mm text area.
_MAX_TABLE_COLUMNS = 8
#: Rows kept from a CSV. The full file ships as a downloadable artifact; a
#: 222-row table inside a report body is a wall, not evidence.
_MAX_TABLE_ROWS = 15
_MAX_CELL_CHARS = 120
#: Section titles are headings, not sentences.
_MAX_TITLE_CHARS = 90

_NON_SLUG = re.compile(r"[^a-z0-9]+")
#: A sentence ends on a period only when a lowercase letter, a digit or a
#: closing bracket precedes it — never after an initial such as the "H." of a
#: binomial name.
_SENTENCE_END = re.compile(r"(?<=[а-яёa-z0-9\)\]])\.\s+")
_VERDICT_RU = {
    "confirmed": "подтверждена",
    "refuted": "опровергнута",
    "inconclusive": "не разрешена имеющимися данными",
    "postponed": "не проверялась",
    "formulated": "сформулирована, проверка не завершена",
    "under_verification": "на проверке",
}


# ── inputs ──────────────────────────────────────────────────────────────────


@dataclass
class NirRequisites:
    """Title-page facts. None of these exist in a CoScientist run.

    They come from the operator's HITL form. Anything left blank becomes the
    contract's draft placeholder rather than an invention: a fabricated УДК or
    registration number in a normative document is worse than a visible gap.
    """

    udc: str = ""
    registration_nioktr: str = ""
    registration_ikrbs: str = ""
    report_type: str = contract.REPORT_TYPE_FINAL
    stage: str = ""
    program_code: str = ""
    approval_position: str = ""
    approval_name: str = ""
    approval_degree: str = ""
    approval_academic_title: str = ""
    approval_date: str = ""
    supervisor_role: str = "Руководитель НИР"
    supervisor_name: str = ""
    supervisor_position: str = ""
    supervisor_degree: str = ""
    supervisor_academic_title: str = ""
    performers_raw: str = ""
    page_count: Optional[int] = None


@dataclass
class NirProse:
    """What the agent writes. Everything else is derived."""

    research_title: str = ""
    report_title: str = ""
    abstract_text: str = ""
    keywords: List[str] = field(default_factory=list)
    introduction_paragraphs: List[str] = field(default_factory=list)
    conclusion_paragraphs: List[str] = field(default_factory=list)
    section_texts: Dict[str, List[str]] = field(default_factory=dict)
    #: figure block id ("fig-1") -> caption. A caption is prose: the fallback
    #: below is a de-underscored filename, which is what a reader should never
    #: see under an illustration in a normative document.
    figure_captions: Dict[str, str] = field(default_factory=dict)
    terms: List[Dict[str, str]] = field(default_factory=list)
    abbreviations: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class SectionPlan:
    """One planned section: what it is about and what evidence backs it."""

    id: str
    title: str
    digest: List[str] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)

    def figure_briefs(self) -> List[Dict[str, str]]:
        """What the author needs to caption each figure in this section."""
        return [
            {
                "id": str(figure.get("id")),
                "file": str(figure.get("_source") or ""),
                "current_caption": str(figure.get("title") or ""),
                "needs_caption": bool(figure.get("_from_filename")),
            }
            for figure in self.figures
        ]


@dataclass
class NirOutline:
    """The skeleton, handed to the agent so it writes against real evidence."""

    sections: List[SectionPlan] = field(default_factory=list)
    references: List[Dict[str, str]] = field(default_factory=list)
    question: str = ""
    gaps: List[str] = field(default_factory=list)
    unplaced_figures: List[Dict[str, Any]] = field(default_factory=list)


# ── small helpers ───────────────────────────────────────────────────────────


def _slug(text: str, fallback: str, taken: Iterable[str]) -> str:
    base = _NON_SLUG.sub("-", str(text or "").lower()).strip("-")
    base = re.sub(r"^[^a-z]+", "", base)[:48].rstrip("-")
    if not base:
        base = fallback
    used = set(taken)
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _sentence(text: Any, limit: int = _MAX_TITLE_CHARS) -> str:
    """First clause of a long attribute, usable as a heading.

    Trailing punctuation is stripped: the normcontrol checks reject a heading or
    a caption that ends in a period.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    cut = flat
    # Sentence and clause ends only. NOT ": " — a hypothesis reads
    # "H1: <the actual claim>", and splitting there would throw away the claim
    # and leave a heading that says nothing.
    #
    # The period must follow a lowercase letter or a digit, so an abbreviation
    # does not end a sentence. Without that guard a binomial name splits at the
    # genus initial and "метаболиты H. sosnowskyi" becomes "метаболиты H".
    for candidate in (_SENTENCE_END.split(flat)[0], flat.split("; ")[0]):
        if len(candidate) < len(cut):
            cut = candidate
    if len(cut) > limit:
        cut = cut[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" .,;:—-")


def _paragraphs(*chunks: Any) -> List[str]:
    """Non-empty, whitespace-normalised paragraphs."""
    out: List[str] = []
    for chunk in chunks:
        text = " ".join(str(chunk or "").split())
        if text:
            out.append(text)
    return out


def _caption(text: Any, fallback: str) -> str:
    return _sentence(text, 120) or fallback


# ── content blocks ──────────────────────────────────────────────────────────


def _figure_block(path: Path, asset_name: str, block_id: str, caption: str, alt: str) -> Dict[str, Any]:
    return {
        "type": "figure",
        "id": block_id,
        "title": caption,
        "path": asset_name,
        "alt_text": alt or caption,
        "width_mm": contract.FIGURE_DEFAULT_WIDTH_MM,
    }


def _read_table(path: Path) -> Optional[Tuple[List[str], List[List[str]], int]]:
    """``(columns, rows, total_rows)`` from a CSV, or None when unusable."""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect)
            records = [row for row in reader if any(str(cell).strip() for cell in row)]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        logger.info("nir build: cannot read table %s (%s)", path, exc)
        return None
    if len(records) < 2:
        return None

    header = [str(cell).strip() for cell in records[0]][:_MAX_TABLE_COLUMNS]
    if not any(header):
        return None
    width = len(header)
    body: List[List[str]] = []
    for record in records[1:]:
        # The contract rejects a row whose cell count differs from the header's,
        # so pad and truncate rather than trusting the file.
        cells = [str(c).strip()[:_MAX_CELL_CHARS] for c in record][:width]
        cells += [""] * (width - len(cells))
        body.append(cells)
    if not body:
        return None
    return header, body[:_MAX_TABLE_ROWS], len(body)


def _table_blocks(path: Path, block_id: str) -> List[Dict[str, Any]]:
    parsed = _read_table(path)
    if parsed is None:
        return []
    columns, rows, total = parsed
    title = _caption(path.stem.replace("_", " "), "Данные прогона")
    blocks: List[Dict[str, Any]] = [{
        "type": "table",
        "id": block_id,
        "title": title,
        "columns": columns,
        "rows": rows,
    }]
    if total > len(rows):
        blocks.append({
            "type": "note",
            "text": (
                f"В таблице приведены первые {len(rows)} строк из {total}. "
                f"Полный набор данных приложен к отчёту в файле {path.name}"
            ),
        })
    return blocks


# ── outline ─────────────────────────────────────────────────────────────────


def _hypothesis_digest(ev: NirEvidence, hypothesis: Dict[str, Any]) -> List[str]:
    """Facts the author must use for this hypothesis, quoted from the graph."""
    attrs = hypothesis.get("attrs") or {}
    hid = str(hypothesis.get("id") or "")
    status = str(hypothesis.get("status") or "")
    digest = _paragraphs(
        f"{hid}. Формулировка: {attrs.get('formulation', '')}",
        f"Обоснование: {attrs.get('rationale', '')}" if attrs.get("rationale") else "",
        f"Статус: {_VERDICT_RU.get(status, status)}",
        f"Почему не проверялась: {attrs.get('not_tested_reason')}" if attrs.get("not_tested_reason") else "",
    )
    for transition in hypothesis.get("status_history") or []:
        reason = transition.get("reason")
        if reason:
            digest.append(
                f"Переход {transition.get('from') or '—'} → {transition.get('to')} "
                f"({transition.get('source')}): {reason}"
            )
    for criteria in ev.by_type("ConfirmationCriteria"):
        if any(_e.get("to") == hid for _e in ev.edges_from(str(criteria.get("id")), "formulated_for")):
            threshold = (criteria.get("attrs") or {}).get("threshold")
            if threshold:
                digest.append(f"Критерий {criteria.get('id')}: {threshold}")
    for item in ev.evidence_for(hid):
        eattrs = item.get("attrs") or {}
        digest.append(
            f"{item.get('id')} ({eattrs.get('subtype', 'evidence')}): {eattrs.get('content', '')}"
            + (f" | измерено на: {eattrs.get('measured_on')}" if eattrs.get("measured_on") else "")
        )
    return digest


def _method_digest(ev: NirEvidence) -> List[str]:
    digest: List[str] = []
    for method in ev.by_type("VerificationMethod"):
        attrs = method.get("attrs") or {}
        digest += _paragraphs(
            f"{method.get('id')} ({attrs.get('method_type', '')}): {attrs.get('description', '')}",
            f"Литературное основание: {attrs.get('literature_basis')}" if attrs.get("literature_basis") else "",
        )
    for tool in ev.by_type("Tool"):
        attrs = tool.get("attrs") or {}
        digest += _paragraphs(
            f"Инструмент {attrs.get('name', tool.get('id'))} "
            f"({attrs.get('tool_type', '')}): {attrs.get('description', '')} "
            f"{attrs.get('location', '')}".strip()
        )
    for base in ev.by_type("EmpiricalBase"):
        attrs = base.get("attrs") or {}
        digest += _paragraphs(
            f"Эмпирическая база {base.get('id')} ({attrs.get('base_type', '')}): "
            f"{attrs.get('source_ref', '')} {attrs.get('volume', '')}".strip()
        )
    for constraint in ev.by_type("Constraint"):
        attrs = constraint.get("attrs") or {}
        digest += _paragraphs(
            f"Ограничение ({attrs.get('subtype', '')}): {attrs.get('content', '')}"
        )
    for step in ev.by_type("PlanStep"):
        attrs = step.get("attrs") or {}
        digest += _paragraphs(
            f"Этап {attrs.get('plan_task_id', step.get('id'))}: {attrs.get('title', '')}. "
            f"{attrs.get('description', '')}"
        )
    return digest


def _conclusion_digest(ev: NirEvidence) -> List[str]:
    digest: List[str] = []
    for conclusion in ev.conclusions:
        attrs = conclusion.get("attrs") or {}
        digest += _paragraphs(
            f"{conclusion.get('id')} — {attrs.get('synthesis', '')}",
            f"Как установлено: {attrs.get('how_established')}" if attrs.get("how_established") else "",
            f"Против критериев: {attrs.get('against_criteria')}" if attrs.get("against_criteria") else "",
            f"Границы применимости: {attrs.get('validity_bounds')}" if attrs.get("validity_bounds") else "",
            f"Открытые вопросы: {attrs.get('open_questions')}" if attrs.get("open_questions") else "",
        )
    return digest


def build_outline(ev: NirEvidence, bundle: Optional[AssetBundle] = None) -> NirOutline:
    """Plan the body: sections, the evidence behind each, figures and tables.

    Figures are spread across the hypothesis sections in order, so an
    illustration lands near the claim it bears on rather than in a gallery at
    the end. What does not fit goes to the results section.
    """
    outline = NirOutline(gaps=list(ev.gaps))
    question = ev.question
    if question:
        outline.question = str((question.get("attrs") or {}).get("formulation") or "")
    if not outline.question:
        outline.question = ev.original_request

    taken: List[str] = []

    method = SectionPlan(
        id=_slug("metodika", "metodika", taken),
        title="Методика исследования и использованные средства",
        digest=_method_digest(ev),
    )
    taken.append(method.id)
    outline.sections.append(method)

    for hypothesis in ev.hypotheses:
        hid = str(hypothesis.get("id") or "h")
        attrs = hypothesis.get("attrs") or {}
        # Shorten the claim first, then compose. Shortening the composed string
        # would cut at the colon and leave a heading that names a hypothesis id
        # and nothing about what it says.
        claim = _sentence(attrs.get("formulation"), 70)
        section = SectionPlan(
            id=_slug(f"proverka-{hid}", f"section-{len(taken)}", taken),
            title=f"Проверка гипотезы {hid}: {claim}" if claim else f"Проверка гипотезы {hid}",
            digest=_hypothesis_digest(ev, hypothesis),
        )
        taken.append(section.id)
        outline.sections.append(section)

    results = SectionPlan(
        id=_slug("rezultaty", "rezultaty", taken),
        title="Обобщённые результаты и их обсуждение",
        digest=_conclusion_digest(ev),
    )
    taken.append(results.id)
    outline.sections.append(results)

    # Agent reports the graph never captured. Attached to the results section so
    # the author can mine them; the digest is explicit about where they come from.
    for report in ev.agent_reports:
        results.digest.append(
            f"Отчёт агента {report['agent']}: {report['text'][:2000]}"
        )

    _place_artifacts(ev, outline, bundle)
    return outline


def _place_artifacts(
    ev: NirEvidence, outline: NirOutline, bundle: Optional[AssetBundle]
) -> None:
    """Spread figures over the hypothesis sections, tables over the results."""
    hypothesis_sections = outline.sections[1:-1] or outline.sections[-1:]
    results = outline.sections[-1]

    figure_index = 0
    for position, path in enumerate(ev.figures):
        asset_name = bundle.name_for(path) if bundle else None
        if not asset_name:
            continue
        figure_index += 1
        described = _figure_caption(ev, path)
        caption = _caption(
            described or _filename_caption(path), f"Иллюстрация {figure_index}"
        )
        block = _figure_block(
            path,
            asset_name,
            f"fig-{figure_index}",
            caption,
            _figure_alt(ev, path) or caption,
        )
        # Marks a caption nobody wrote — the builder fell back to the filename.
        # Stripped before the block reaches the document; it only tells the
        # author which figures still need a caption.
        block["_from_filename"] = not described
        block["_source"] = path.name
        target = (
            hypothesis_sections[position % len(hypothesis_sections)]
            if hypothesis_sections else results
        )
        target.figures.append(block)

    table_index = 0
    for path in ev.tables:
        if path.suffix.lower() not in (".csv", ".tsv"):
            continue
        table_index += 1
        blocks = _table_blocks(path, f"tbl-{table_index}")
        if blocks:
            results.tables.extend(blocks)
        else:
            table_index -= 1


def _figure_caption(ev: NirEvidence, path: Path) -> str:
    """The graph's description of this file, or "" when nothing describes it.

    Empty is meaningful: it tells the caller the only caption available is a
    filename, which is worth flagging to the author.
    """
    stem = path.stem.lower()
    for node in ev.by_type("CodeArtifact", "GeneratedData"):
        attrs = node.get("attrs") or {}
        node_path = str(attrs.get("path") or "")
        if node_path and Path(node_path).stem.lower() in stem:
            description = str(attrs.get("description") or "").strip()
            if description:
                return description
    return ""


def _filename_caption(path: Path) -> str:
    """Last resort: the filename, made readable."""
    return path.stem.replace("_", " ").strip()


def _figure_alt(ev: NirEvidence, path: Path) -> str:
    return _sentence(_figure_caption(ev, path), 200)


# ── document ────────────────────────────────────────────────────────────────


def _placeholder(value: str) -> str:
    text = str(value or "").strip()
    return text or contract.PLACEHOLDER


def _performers(requisites: NirRequisites) -> List[Dict[str, Any]]:
    """One performer per non-empty line of the form's free-text field.

    Format per line: ``роль | должность | И.О. Фамилия | вклад``. Fewer fields
    degrade to placeholders rather than dropping the row, because ``performers``
    is a ``must`` array with ``min_items: 1`` — an empty list fails validation
    outright and the author never sees why.
    """
    rows: List[Dict[str, Any]] = []
    for line in str(requisites.performers_raw or "").splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (4 - len(parts))
        rows.append({
            "role": _placeholder(parts[0]),
            "position": _placeholder(parts[1]),
            "name": _placeholder(parts[2]),
            "contributed_sections": [_placeholder(parts[3])],
        })
    if not rows:
        rows.append({
            "role": _placeholder(requisites.supervisor_role),
            "position": _placeholder(requisites.supervisor_position),
            "name": _placeholder(requisites.supervisor_name),
            "contributed_sections": [contract.PLACEHOLDER],
        })
    return rows


def _title(requisites: NirRequisites, prose: NirProse, ev: NirEvidence) -> Dict[str, Any]:
    research_title = _sentence(
        prose.research_title or ev.original_request or "Научно-исследовательская работа", 250
    )
    report_title = _sentence(prose.report_title or research_title, 250)

    approval: Dict[str, Any] = {
        "position": _placeholder(requisites.approval_position),
        "name": _placeholder(requisites.approval_name),
    }
    for key, value in (
        ("degree", requisites.approval_degree),
        ("academic_title", requisites.approval_academic_title),
        ("date", requisites.approval_date),
    ):
        if str(value or "").strip():
            approval[key] = str(value).strip()

    supervisor: Dict[str, Any] = {
        "role": _placeholder(requisites.supervisor_role),
        "name": _placeholder(requisites.supervisor_name),
    }
    for key, value in (
        ("position", requisites.supervisor_position),
        ("degree", requisites.supervisor_degree),
        ("academic_title", requisites.supervisor_academic_title),
    ):
        if str(value or "").strip():
            supervisor[key] = str(value).strip()

    report_type = (
        requisites.report_type
        if requisites.report_type in contract.REPORT_TYPES
        else contract.REPORT_TYPE_FINAL
    )
    title: Dict[str, Any] = {
        "udc": _placeholder(requisites.udc),
        "registration_nioktr": _placeholder(requisites.registration_nioktr),
        "registration_ikrbs": _placeholder(requisites.registration_ikrbs),
        "approval": approval,
        "research_title": research_title,
        "report_title": report_title,
        "report_type": report_type,
        "supervisor": supervisor,
    }
    # Conditional: the contract demands a stage only for an interim report, and
    # sending one for a final report is an unknown_value error.
    if report_type == contract.REPORT_TYPE_INTERIM:
        title["stage"] = _placeholder(requisites.stage)
    if str(requisites.program_code or "").strip():
        title["program_code"] = str(requisites.program_code).strip()
    return title


_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
#: A presigned link is a capability with an expiry, not a citation. Putting one
#: in a bibliography prints a dead 600-character URL into a normative document.
_NOT_CITABLE = ("x-amz-", "x-amz-signature", "?x-amz")


def _citable_urls(text: Any) -> List[str]:
    """URLs from free text, minus our own expiring artifact links."""
    found: List[str] = []
    for url in _URL_RE.findall(str(text or "")):
        cleaned = url.rstrip(".,;)")
        if any(marker in cleaned.lower() for marker in _NOT_CITABLE):
            continue
        found.append(cleaned)
    return found


def _references(ev: NirEvidence, graph_export_url: Optional[str]) -> List[Dict[str, str]]:
    """Cited literature, then the artifacts that let a reader re-run the work."""
    entries: List[Dict[str, str]] = []
    seen: set = set()

    def add(text: str) -> None:
        flat = " ".join(str(text or "").split())
        if not flat or flat.lower() in seen:
            return
        seen.add(flat.lower())
        entries.append({"id": f"src-{len(entries) + 1}", "text": flat})

    for item in ev.literature:
        attrs = item.get("attrs") or {}
        add(attrs.get("source_ref") or attrs.get("source") or attrs.get("content"))
    for method in ev.by_type("VerificationMethod"):
        attrs = method.get("attrs") or {}
        sources = attrs.get("sources")
        if isinstance(sources, str):
            for url in _citable_urls(sources):
                add(url)
        elif isinstance(sources, list):
            for url in sources:
                add(url)
        # The literature a method was built on, which agents record here far
        # more often than they create a literature-subtype Evidence node.
        add(attrs.get("literature_basis"))
    for base in ev.by_type("EmpiricalBase"):
        add((base.get("attrs") or {}).get("source_ref"))
    # Evidence prose sometimes carries the only citation of a model or dataset.
    for item in ev.by_type("Evidence"):
        attrs = item.get("attrs") or {}
        for field_name in ("source_ref", "source"):
            add(attrs.get(field_name))
        for url in _citable_urls(attrs.get("content")):
            add(url)

    add(
        "CoScientist: многоагентная система автоматизации научного исследования. "
        f"Исходный код: {REPOSITORY_URL}"
    )
    if graph_export_url:
        add(
            "Граф научного исследования по настоящей работе (машинная выгрузка, "
            f"формат JSON): {graph_export_url}"
        )
    if not entries:
        add("Источники в ходе работы не фиксировались")
    return entries


def _appendices(ev: NirEvidence) -> List[Dict[str, Any]]:
    """Reference appendices: how to read our data, and what the run cost."""
    appendices: List[Dict[str, Any]] = []

    nodes = ev.type_census()
    edges = ev.edge_census()
    if nodes:
        blocks: List[Dict[str, Any]] = [{
            "type": "paragraph",
            "text": (
                "Ход исследования фиксировался в типизированном графе. Узел описывает "
                "объект работы, ребро — отношение между объектами; каждый узел хранит "
                "автора записи, время и историю смены статуса с указанием причины. "
                "Ниже приведён состав графа настоящей работы; машинная выгрузка "
                "приложена к отчёту отдельным файлом."
            ),
        }, {
            "type": "table",
            "id": "graph-nodes",
            "title": "Состав узлов графа научного исследования",
            "columns": ["Тип узла", "Назначение", "Количество"],
            "rows": [
                [name, _NODE_PURPOSE.get(name, "—"), str(count)]
                for name, count in nodes.items()
            ],
        }]
        if edges:
            blocks.append({
                "type": "table",
                "id": "graph-edges",
                "title": "Состав связей графа научного исследования",
                "columns": ["Тип связи", "Количество"],
                "rows": [[name, str(count)] for name, count in edges.items()],
            })
        appendices.append({
            "id": "research-graph",
            "status": "справочное",
            "title": "Структура графа научного исследования",
            "blocks": blocks,
        })

    resource_rows = _resource_rows(ev)
    if resource_rows:
        appendices.append({
            "id": "resources",
            "status": "справочное",
            "title": "Вычислительные ресурсы, затраченные на работу",
            "blocks": [{
                "type": "table",
                "id": "resource-usage",
                "title": "Затраты вычислительных ресурсов",
                "columns": ["Показатель", "Значение"],
                "rows": resource_rows,
            }],
        })
    return appendices


_NODE_PURPOSE = {
    "ResearchQuestion": "исследовательский вопрос",
    "Hypothesis": "проверяемая гипотеза",
    "Evidence": "полученное свидетельство",
    "Conclusion": "вывод по итогам проверки",
    "VerificationMethod": "метод проверки гипотезы",
    "ConfirmationCriteria": "критерий подтверждения",
    "PlanStep": "этап плана работ",
    "ExperimentTask": "задача эксперимента",
    "Tool": "использованный инструмент",
    "Resource": "ресурс",
    "EmpiricalBase": "эмпирическая база",
    "Constraint": "ограничение исследования",
    "CodeArtifact": "программный артефакт",
    "GeneratedData": "сгенерированные данные",
    "Report": "отчётный материал",
    "CostModel": "модель стоимости",
}


def _resource_rows(ev: NirEvidence) -> List[List[str]]:
    rows: List[List[str]] = []
    runs = (ev.metrics or {}).get("runs")
    if isinstance(runs, list) and runs:
        rows.append(["Запусков вычислительной среды", str(len(runs))])
    for node in ev.by_type("Resource"):
        attrs = node.get("attrs") or {}
        label = str(attrs.get("resource_type") or node.get("id"))
        value = " / ".join(
            str(attrs.get(k)) for k in ("remaining", "limit") if attrs.get(k)
        )
        if value:
            rows.append([label, value])
    return rows


def build_nir_values(
    ev: NirEvidence,
    requisites: NirRequisites,
    prose: NirProse,
    outline: NirOutline,
    graph_export_url: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Build ``values``; return it with the problems the author should know about.

    Problems are advisory. The document is always structurally valid — every
    ``must`` array gets a fallback — so the author can render a draft and see
    what the gaps look like on the page instead of arguing with a validator.
    """
    problems: List[str] = []

    sections: List[Dict[str, Any]] = []
    for plan in outline.sections:
        written = [p for p in prose.section_texts.get(plan.id, []) if str(p).strip()]
        if not written:
            # Fall back to the evidence itself so the section is never empty.
            written = plan.digest[:6] or [
                f"Материалы по разделу «{plan.title}» в ходе работы не зафиксированы"
            ]
            problems.append(f"раздел «{plan.id}» не написан — подставлена выжимка из графа")
        blocks: List[Dict[str, Any]] = [
            {"type": "paragraph", "text": " ".join(str(p).split())} for p in written
        ]
        for figure in plan.figures:
            written_caption = _sentence(prose.figure_captions.get(figure["id"]), 120)
            if written_caption:
                figure = dict(figure, title=written_caption, alt_text=written_caption)
            elif figure.get("_from_filename"):
                problems.append(
                    f"рисунок {figure['id']} без подписи — использовано имя файла"
                )
            blocks.append({k: v for k, v in figure.items() if not k.startswith("_")})
        blocks.extend(plan.tables)
        sections.append({"id": plan.id, "title": plan.title, "blocks": blocks})

    if not sections:
        sections = [{
            "id": "rezultaty",
            "title": "Результаты работы",
            "blocks": [{"type": "paragraph", "text": contract.PLACEHOLDER}],
        }]
        problems.append("основная часть пуста")

    introduction = _paragraphs(*prose.introduction_paragraphs)
    if not introduction:
        introduction = _paragraphs(
            ev.original_request,
            outline.question,
        ) or [contract.PLACEHOLDER]
        problems.append("введение не написано — подставлена исходная постановка задачи")
    introduction.append(
        "Работа выполнена автоматизированной многоагентной системой CoScientist; "
        f"исходный код системы доступен по адресу {REPOSITORY_URL}. "
        "Ход исследования зафиксирован в графе, структура которого приведена в приложении."
    )

    conclusion = _paragraphs(*prose.conclusion_paragraphs)
    if not conclusion:
        conclusion = _conclusion_digest(ev)[:6] or [contract.PLACEHOLDER]
        problems.append("заключение не написано — подставлены выводы из графа")

    keywords = [str(k).strip().rstrip(".") for k in prose.keywords if str(k).strip()]
    if len(keywords) < contract.KEYWORDS_MIN:
        problems.append(
            f"ключевых слов {len(keywords)}, требуется не менее {contract.KEYWORDS_MIN}"
        )
        keywords = keywords + [contract.PLACEHOLDER] * (contract.KEYWORDS_MIN - len(keywords))
    keywords = keywords[: contract.KEYWORDS_MAX]

    abstract_text = " ".join(str(prose.abstract_text or "").split())
    if not abstract_text:
        abstract_text = contract.PLACEHOLDER
        problems.append("реферат не написан")
    elif len(abstract_text) > contract.ABSTRACT_MAX_CHARS:
        problems.append(
            f"реферат {len(abstract_text)} символов при рекомендованных "
            f"{contract.ABSTRACT_MAX_CHARS} — сервер выдаст предупреждение"
        )

    document: Dict[str, Any] = {
        "title": _title(requisites, prose, ev),
        "performers": _performers(requisites),
        "abstract": {"keywords": keywords, "text": abstract_text},
        "introduction": [{"type": "paragraph", "text": p} for p in introduction],
        "sections": sections,
        "conclusion": [{"type": "paragraph", "text": p} for p in conclusion],
        "references": _references(ev, graph_export_url),
    }

    terms = [
        {"term": str(t.get("term", "")).strip(), "definition": str(t.get("definition", "")).strip()}
        for t in prose.terms
        if str(t.get("term", "")).strip() and str(t.get("definition", "")).strip()
    ]
    if terms:
        document["terms"] = terms
    abbreviations = [
        {"term": str(a.get("term", "")).strip(), "definition": str(a.get("definition", "")).strip()}
        for a in prose.abbreviations
        if str(a.get("term", "")).strip() and str(a.get("definition", "")).strip()
    ]
    if abbreviations:
        document["abbreviations"] = abbreviations

    appendices = _appendices(ev)
    if appendices:
        document["appendices"] = appendices

    problems.extend(_lint(document))
    return contract.envelope(document), problems


def _lint(document: Dict[str, Any]) -> List[str]:
    """Catch locally what the server would reject, so no round trip is wasted."""
    problems: List[str] = []
    seen: Dict[str, str] = {}

    def claim(identifier: Any, where: str) -> None:
        key = str(identifier or "")
        if not key:
            return
        if key in seen:
            problems.append(f"идентификатор «{key}» повторяется ({seen[key]} и {where})")
        else:
            seen[key] = where

    def walk_blocks(blocks: Sequence[Dict[str, Any]], where: str) -> None:
        for block in blocks:
            block_type = block.get("type")
            if block_type not in contract.BLOCK_FIELDS:
                problems.append(f"{where}: неизвестный тип блока «{block_type}»")
                continue
            allowed = contract.block_allowed_keys(block_type)
            extra = set(block) - allowed
            if extra:
                problems.append(f"{where}: лишние поля блока {sorted(extra)}")
            required, _ = contract.BLOCK_FIELDS[block_type]
            missing = required - set(block)
            if missing:
                problems.append(f"{where}: в блоке {block_type} нет полей {sorted(missing)}")
            if "id" in block:
                claim(block["id"], where)
            if block_type == "table":
                width = len(block.get("columns") or [])
                for index, row in enumerate(block.get("rows") or []):
                    if len(row) != width:
                        problems.append(
                            f"{where}: в строке {index + 1} таблицы {len(row)} ячеек "
                            f"при {width} колонках"
                        )
                        break
            if block_type == "figure":
                width = block.get("width_mm", contract.FIGURE_DEFAULT_WIDTH_MM)
                if not (contract.FIGURE_MIN_WIDTH_MM <= width <= contract.MAX_WIDTH_MM):
                    problems.append(f"{where}: ширина рисунка {width} мм вне допустимого диапазона")

    for section in document.get("sections") or []:
        claim(section.get("id"), f"раздел {section.get('id')}")
        if not contract.SLUG_RE.match(str(section.get("id") or "")):
            problems.append(f"идентификатор раздела «{section.get('id')}» не соответствует шаблону")
        walk_blocks(section.get("blocks") or [], f"раздел {section.get('id')}")
    for appendix in document.get("appendices") or []:
        claim(appendix.get("id"), f"приложение {appendix.get('id')}")
        if appendix.get("status") not in contract.APPENDIX_STATUSES:
            problems.append(f"приложение {appendix.get('id')}: недопустимый статус")
        walk_blocks(appendix.get("blocks") or [], f"приложение {appendix.get('id')}")
    for reference in document.get("references") or []:
        claim(reference.get("id"), "список источников")
        if not contract.REFERENCE_ID_RE.match(str(reference.get("id") or "")):
            problems.append(f"идентификатор источника «{reference.get('id')}» не соответствует шаблону")
    walk_blocks(document.get("introduction") or [], "введение")
    walk_blocks(document.get("conclusion") or [], "заключение")
    return problems


__all__ = [
    "NirRequisites",
    "NirProse",
    "NirOutline",
    "SectionPlan",
    "build_outline",
    "build_nir_values",
    "REPOSITORY_URL",
]
