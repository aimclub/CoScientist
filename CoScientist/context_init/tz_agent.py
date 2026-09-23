"""Стадия выпуска технического задания — сразу после подтверждения рамки.

Отдельная стадия, а не хвост `ContextInitSessionAgent`, по одной причине:
связный текст разделов пишет модель, а модельный вызов в системе делает агент.
Всё остальное вокруг него детерминировано — разделы собраны из подтверждённой
рамки (`tz.spec_from_frame`), и проза может переформулировать раздел, но не
может заполнить пустой (`tz.apply_prose`).

Согласования у этой стадии нет. Оператор уже утвердил рамку, а ТЗ — её
изложение по ГОСТ 19.201-78; второе окно на старте каждого прогона стоило бы
дороже, чем даёт. Если рамку потом правят, документ выпускается заново.

Ничего здесь не поднимает исключений наружу: исследование, остановленное тем,
что не собрался .docx, — это хуже, чем исследование без .docx.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from pydantic import BaseModel, Field

from CoScientist.context_init.agent import coerce_frame
from CoScientist.context_init.models import ResearchFrame
from CoScientist.context_init.tz import (
    NOT_SET,
    TechnicalSpec,
    apply_prose,
    spec_from_frame,
)
from CoScientist.context_init.tz_docx import render_tz_markdown, write_tz_files
from CoScientist.graph.research.store import get_research_graph
from CoScientist.hitl.session_agent import SessionAgent

logger = logging.getLogger(__name__)

#: Куда кладутся документы. Тот же каталог, что у ТЗ микрофлюидики — это одно и
#: то же место в глазах оператора, и маршрут `/api/tz-document` один.
TZ_DOCUMENTS_DIR = Path("tz_documents")

#: Стадия отработала в этой сессии. Как и у рамки: `pipeline.pre` вызывается на
#: каждом ходу чата, а ТЗ выпускается один раз.
TZ_COMPLETED_STATE_KEY = "tz_document_issued"
TZ_DOCUMENT_STATE_KEY = "tz_document"

#: Ссылка, по которой документ открывается. Именно эта форма: `chat.js` делает
#: из голого `/api/tz-document…` кликабельную ссылку, а `store._href` пропускает
#: `/api/…` в карточку графа — так один адрес работает в обоих местах.
_ROUTE = "/api/tz-document"


class TZProseSection(BaseModel):
    """Переписанный текст одного раздела."""

    number: str = Field(description="Номер раздела, напр. «1» или «8»")
    text: str = Field(description="Связный текст раздела на русском")


class TZProse(BaseModel):
    """Что модель возвращает: только проза, только для заполненных разделов."""

    sections: List[TZProseSection] = Field(default_factory=list)


def _link(name: str) -> str:
    from urllib.parse import quote

    return f"{_ROUTE}?name={quote(name)}"


def tz_is_issued(state: Dict[str, Any]) -> bool:
    return bool(state.get(TZ_COMPLETED_STATE_KEY))


def build_spec(state: Dict[str, Any], prose: Any = None) -> Optional[TechnicalSpec]:
    """Собрать ТЗ из рамки, лежащей в состоянии сессии, и наложить прозу."""
    raw = state.get("research_frame")
    if not raw:
        return None
    try:
        frame: ResearchFrame = coerce_frame(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ТЗ не собрано: рамка не разобрана (%s)", exc)
        return None
    spec = spec_from_frame(frame, str(frame.original_request or ""))
    rows = (prose or {}).get("sections") if isinstance(prose, dict) else None
    if rows:
        said = {str(r.get("number") or ""): str(r.get("text") or "")
                for r in rows if isinstance(r, dict)}
        spec = apply_prose(spec, said)
    return spec


def publish_spec(spec: TechnicalSpec, store: Any,
                 directory: Path = TZ_DOCUMENTS_DIR
                 ) -> Tuple[Optional[str], Optional[str]]:
    """Записать файлы и повесить ТЗ на карточку «Постановка».

    Узел `Spec` — единственный способ сделать документ открываемым из графа:
    панель превращает в ссылку вложение, а не атрибут. Адрес кладётся в `path`,
    потому что именно его читает `store._href`.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    docx_name, md_name = write_tz_files(spec, directory, stamp)
    shown = docx_name or md_name
    if not shown:
        logger.warning("ТЗ не сохранено: ни .docx, ни .md записать не удалось")
        return None, None
    try:
        root = store.root_id()
        attrs = {
            "content": render_tz_markdown(spec),
            "name": shown,
            # `path` — то, из чего панель делает ссылку.
            "path": _link(shown),
        }
        result = store.commit(
            source="ContextInitAgent",
            nodes=[{"type": "Spec", "ref": "tz_new", "attrs": attrs}],
            edges=([{"type": "derived_from", "from": "#tz_new", "to": root}]
                   if root else []),
            partial_edges=True,
        )
        if not result.ok:
            logger.warning("ТЗ не прикреплено к графу: %s", result.errors[:2])
    except Exception as exc:  # noqa: BLE001
        logger.warning("ТЗ не прикреплено к графу: %s", exc)
    return docx_name, md_name


def announcement(docx_name: Optional[str], md_name: Optional[str]) -> str:
    """Короткое сообщение в ленту: что появилось и где это открыть.

    Короткое намеренно. Тело документа в ленту не выгружается — карточку
    «Постановка» и ссылку читают глазами, а стена текста в чате хоронит и то и
    другое.
    """
    lines = ["📄 Техническое задание сформировано по ГОСТ 19.201-78."]
    if docx_name:
        lines.append(f"Word: [{docx_name}]({_link(docx_name)})")
    if md_name:
        lines.append(f"Прочитать в браузере: [{md_name}]({_link(md_name)})")
    lines.append("Документ приложен к карточке «Постановка» в графе исследования.")
    return "\n".join(lines)


class TZSpecSessionAgent(SessionAgent):
    """Выпускает ТЗ по подтверждённой рамке — один раз за сессию."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if tz_is_issued(state) or not state.get("research_frame"):
            # Нечего выпускать: либо уже выпущено, либо рамка не подтверждена
            # (стадия рамки выключена или не дошла до сева). Молча пропускаем —
            # это не ошибка, а обычный ход чата после старта.
            return
        async for event in super()._run_async_impl(ctx):
            yield event

    def _post_final_events(self, ctx: InvocationContext, output_text):
        state = ctx.session.state
        spec = build_spec(state, state.get(self.output_key) if self.output_key else None)
        if spec is None:
            return
        try:
            store = get_research_graph(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ТЗ: граф недоступен (%s)", exc)
            store = None
        docx_name, md_name = (publish_spec(spec, store) if store is not None
                              else (None, None))
        if not (docx_name or md_name):
            return
        logger.info("ТЗ выпущено: %s", docx_name or md_name)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text=announcement(docx_name, md_name))],
            ),
            actions=EventActions(state_delta={
                TZ_COMPLETED_STATE_KEY: True,
                TZ_DOCUMENT_STATE_KEY: {"docx": docx_name, "md": md_name},
            }),
        )


__all__ = [
    "TZ_COMPLETED_STATE_KEY",
    "TZ_DOCUMENTS_DIR",
    "TZ_DOCUMENT_STATE_KEY",
    "TZProse",
    "TZSpecSessionAgent",
    "announcement",
    "build_spec",
    "stage_tz_draft",
    "publish_spec",
    "tz_is_issued",
]


def stage_tz_draft(callback_context) -> None:
    """before_agent: put the assembled ТЗ where the prompt can read it.

    A prompt is rendered once, when the agent tree is built; the draft differs
    per session, so it travels through session state and ADK's own `{tz_draft?}`
    substitution. Only the sections that HAVE text are offered — there is
    nothing to rewrite in «Не задано», and offering it invites the model to fill
    it in.
    """
    try:
        state = callback_context.state
        spec = build_spec(state)
        if spec is None:
            state["tz_draft"] = ""
            return
        parts = []
        for section in spec.sections:
            body = (section.body or "").strip()
            if body and body != NOT_SET and not section.rows:
                parts.append(f"{section.number}. {section.title}\n{body}")
        state["tz_draft"] = "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001 — a missing draft costs prose, not the run
        logger.warning("ТЗ: черновик для модели не собран (%s)", exc)
        try:
            callback_context.state["tz_draft"] = ""
        except Exception:  # noqa: BLE001
            pass
    return None
