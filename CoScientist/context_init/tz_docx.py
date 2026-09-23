"""Рендер технического задания: Word для человека, Markdown для чата и графа.

Два выхода из одного `TechnicalSpec`, потому что документ живёт в двух местах.
В .docx его открывают, печатают и подписывают; .md показывает то же самое там,
где Word не откроешь — в ленте чата и в карточке «Постановка».

Оформление намеренно скромное: ГОСТ 19.201-78 задаёт СОДЕРЖАНИЕ разделов, а
требования к оформлению листов лежат в ГОСТ 19.106-78, который мы не заявляем и
не проверяем. Обещать в колонтитуле соответствие тому, чего никто не сверял, —
хуже, чем не обещать ничего.
"""
from __future__ import annotations

import io
from typing import List, Optional, Tuple

from CoScientist.context_init.tz import NOT_SET, TZSection, TechnicalSpec

#: Что печатается на титуле над темой.
_STANDARD = "ГОСТ 19.201-78"


def _visible(section: TZSection) -> bool:
    """Печатать ли раздел. Печатаются все — включая пустые.

    Пустой раздел в ТЗ не мусор, а вопрос заказчику: «основание для работы не
    задано» сообщает читателю ровно то, что произошло. Молча выброшенный раздел
    сообщил бы, что его не требовалось.
    """
    return bool(section.number)


# ── Markdown ────────────────────────────────────────────────────────────────

def _md_section(section: TZSection, level: int = 2) -> List[str]:
    out = ["", "#" * level + f" {section.number}. {section.title}"]
    if section.body:
        out += ["", section.body]
    if section.rows:
        out += ["", "| | |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in section.rows]
    for sub in section.subsections:
        out += _md_section(sub, level + 1)
    return out


def render_tz_markdown(spec: TechnicalSpec) -> str:
    """Тот же документ, что и .docx, в виде Markdown."""
    lines = [
        f"# Техническое задание",
        "",
        f"**{spec.topic}**",
        "",
        f"Составлено по {_STANDARD}.",
        "",
        "| | |",
        "|---|---|",
        f"| Заказчик | {spec.customer} |",
        f"| Основание | {spec.basis} |",
    ]
    if spec.original_request:
        lines += ["", "> Исходный запрос заказчика:", ">",
                  "> " + spec.original_request.replace("\n", "\n> ")]
    for section in spec.sections:
        if _visible(section):
            lines += _md_section(section)
    missing = spec.unfilled()
    if missing:
        lines += ["", "---", "",
                  "Разделы, для которых сведения не заданы: "
                  + ", ".join(missing) + ". "
                  "Они заполняются оператором в форме «Основание и приёмка» "
                  "рамки исследования."]
    return "\n".join(lines) + "\n"


# ── Word ────────────────────────────────────────────────────────────────────

def _add_rows(document, rows: List[Tuple[str, str]]) -> None:
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].text = str(key)
        cells[1].text = str(value)
        for paragraph in cells[0].paragraphs:
            for run in paragraph.runs:
                run.bold = True


def _add_section(document, section: TZSection, level: int) -> None:
    document.add_heading(f"{section.number}. {section.title}", level=level)
    if section.body:
        document.add_paragraph(section.body)
    if section.rows:
        _add_rows(document, section.rows)
    for sub in section.subsections:
        _add_section(document, sub, min(level + 1, 4))


def build_tz_docx(spec: TechnicalSpec) -> bytes:
    """Собрать .docx и вернуть его байтами.

    Байтами, а не файлом: вызывающий решает, писать на диск, отдавать по HTTP
    или и то и другое, и ему не приходится чистить временный файл, если запись
    не удалась.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()
    # Times New Roman 12 — регистр, в котором такие документы читают; python-docx
    # ставит Calibri 11, и ТЗ выглядит как записка.
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ТЕХНИЧЕСКОЕ ЗАДАНИЕ")
    run.bold = True
    run.font.size = Pt(18)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(spec.topic).bold = True

    note = document.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.add_run(f"Составлено по {_STANDARD}").italic = True

    _add_rows(document, [("Заказчик", spec.customer),
                         ("Основание", spec.basis)])

    if spec.original_request:
        document.add_heading("Исходный запрос заказчика", level=2)
        document.add_paragraph(spec.original_request)

    document.add_page_break()
    for section in spec.sections:
        if _visible(section):
            _add_section(document, section, level=1)

    missing = spec.unfilled()
    if missing:
        document.add_paragraph()
        warning = document.add_paragraph()
        warning.add_run(
            "Сведения не заданы для разделов: " + ", ".join(missing) + ". "
            "Они заполняются оператором в форме «Основание и приёмка» рамки "
            "исследования."
        ).italic = True

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def write_tz_files(spec: TechnicalSpec, directory, stamp: str
                   ) -> Tuple[Optional[str], Optional[str]]:
    """Записать оба файла и вернуть их имена, или None для того, что не вышло.

    Ничего не поднимает: документ, который не удалось сохранить, не должен
    останавливать исследование — оператор увидит в ленте, что файла нет, и это
    честнее упавшего прогона.
    """
    from pathlib import Path

    directory = Path(directory)
    docx_name = md_name = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        md_name = f"ТЗ_{stamp}.md"
        (directory / md_name).write_text(render_tz_markdown(spec), encoding="utf-8")
    except OSError:
        md_name = None
    try:
        docx_name = f"ТЗ_{stamp}.docx"
        (directory / docx_name).write_bytes(build_tz_docx(spec))
    except Exception:  # noqa: BLE001 — python-docx raises its own family
        docx_name = None
    return docx_name, md_name


__all__ = ["build_tz_docx", "render_tz_markdown", "write_tz_files"]
