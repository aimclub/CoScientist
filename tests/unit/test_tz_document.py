"""Техническое задание по ГОСТ 19.201-78, собранное из рамки исследования.

Рамка заполняла постановку; заказчику нужен документ. Здесь проверяется то, за
что документ и отвечает: что он говорит ровно то, что подтвердил оператор, и
ничего сверх; что все восемь разделов стандарта на месте и в порядке п. 1.4; и
что готовый файл можно открыть — из чата по ссылке и из графа с карточки
«Постановка».

Run from the repo root:  pytest tests/unit/test_tz_document.py -q
"""
import pytest
from dotenv import load_dotenv

load_dotenv()

from CoScientist.context_init.models import ResearchFrame  # noqa: E402
from CoScientist.context_init.tz import (  # noqa: E402
    NOT_SET,
    apply_prose,
    spec_from_frame,
)
from CoScientist.context_init.tz_docx import write_tz_files  # noqa: E402
from CoScientist.graph.research.store import FRAME_ID, ResearchGraphStore  # noqa: E402

#: Разделы, которые стандарт перечисляет в п. 1.4, в его порядке.
GOST_SECTIONS = ("1", "2", "3", "4", "5", "6", "7", "8")


def _frame(**answers) -> ResearchFrame:
    """Рамка, в которой заполнены названные поля и только они."""
    frame = ResearchFrame.blank()
    for block in frame.blocks:
        for field in block.fields:
            if field.name in answers:
                field.value = answers[field.name]
                field.status = "уточнено оператором"
    return frame


# ── состав документа ────────────────────────────────────────────────────────

def test_the_document_has_every_section_the_standard_lists_in_order():
    """П. 1.4 перечисляет восемь разделов. Документ, в котором раздела нет,
    читатель не может отличить от документа, где раздел не требовался."""
    spec = spec_from_frame(ResearchFrame.blank())
    assert [s.number for s in spec.sections] == list(GOST_SECTIONS)


def test_the_requirements_section_keeps_the_standards_own_subsection_numbers():
    """4.1-4.6 соответствуют п. 2.4 стандарта. Номера сохранены, чтобы
    соответствие читалось без сверки."""
    spec = spec_from_frame(ResearchFrame.blank())
    fourth = spec.section("4")
    assert [s.number for s in fourth.subsections] == [
        "4.1", "4.2", "4.3", "4.4", "4.5", "4.6"]


def test_a_subsection_the_standard_has_and_research_has_not_is_named_not_dropped():
    """Маркировка, упаковка, транспортирование (2.4.6-2.4.8) к исследованию не
    применимы. Молча выброшенные, они сообщили бы, что их не требовалось;
    стандарт разрешает объединять разделы, и документ говорит, что объединил."""
    body = spec_from_frame(ResearchFrame.blank()).section("4").body
    assert "2.4.6-2.4.8" in body and "не" in body


# ── ничего не выдумано ──────────────────────────────────────────────────────

def test_an_empty_frame_produces_an_empty_document_not_a_plausible_one():
    """Придуманный заказчик попадёт в документ, который пойдёт людям, и будет
    читаться как факт. Пусто — честный результат опроса."""
    spec = spec_from_frame(ResearchFrame.blank())
    assert spec.customer == NOT_SET and spec.basis == NOT_SET
    # Всё, кроме четвёртого: у него есть собственный текст — оговорка о
    # разделах стандарта, которые к исследованию не применимы, — и подразделы,
    # и пусты как раз они.
    empty = set(spec.unfilled())
    assert empty >= {"1", "2", "3", "5", "6", "7", "8"}
    assert empty >= {"4.1", "4.2", "4.3", "4.4", "4.5", "4.6"}


def test_the_sections_the_new_questions_fill_are_exactly_the_ones_that_were_empty():
    """Блок «Основание и приёмка» добавлен ровно под разделы 2.2, 2.5а, 2.6 и
    2.7 — те, которые из дружеского запроса не выводятся."""
    before = spec_from_frame(ResearchFrame.blank()).unfilled()
    assert {"2", "5", "7"} <= set(before)

    after = spec_from_frame(_frame(
        basis_document="Договор № 17 от 03.02.2026",
        customer="ИТМО, НИИ наносистем",
        topic_name="Токсикологическое профилирование метаболитов борщевика",
        deliverables="Отчёт о НИР по ГОСТ 7.32, набор данных SMILES",
        stages="1. Сбор данных — март. 2. Профилирование — апрель.",
        acceptance="Приёмка комиссией НИИ по акту",
    ))
    assert {"2", "5", "7"}.isdisjoint(after.unfilled())
    assert after.customer == "ИТМО, НИИ наносистем"
    assert "Договор № 17" in after.section("2").rows[0][1]


def test_the_model_may_rewrite_a_section_but_never_fill_an_empty_one():
    """Гибрид держится на этом: факты берутся из подтверждённой рамки, модель
    даёт им связный вид. Иначе «Не задано» превращается в обязательство."""
    spec = spec_from_frame(_frame(formulation="Насколько токсичны метаболиты?"))
    assert spec.section("1").body != NOT_SET and spec.section("7").body == NOT_SET

    apply_prose(spec, {"1": "Работа посвящена оценке токсичности метаболитов.",
                       "7": "Работа выполняется в три этапа до конца года."})
    assert spec.section("1").body.startswith("Работа посвящена")
    assert spec.section("7").body == NOT_SET


def test_the_research_tasks_reach_the_document_as_tasks():
    """«OP-1» — машинный ключ плана, а не строка документа."""
    from CoScientist.context_init.models import FrameOperation

    frame = ResearchFrame.blank()
    frame.operations = [
        FrameOperation(operation_id="OP-1", statement="Собрать SMILES метаболитов"),
        FrameOperation(operation_id="OP-2", statement="Предсказать LD50"),
    ]
    rows = spec_from_frame(frame).section("4").subsections[0].rows
    assert [k for k, _ in rows] == ["Задача 1", "Задача 2"]
    assert rows[1][1] == "Предсказать LD50"


# ── файлы ───────────────────────────────────────────────────────────────────

def test_the_word_file_opens_and_carries_the_sections(tmp_path):
    docx = pytest.importorskip("docx")
    spec = spec_from_frame(_frame(
        formulation="Насколько токсичны метаболиты борщевика?",
        topic_name="Профилирование метаболитов",
        customer="ИТМО"))
    name, _ = write_tz_files(spec, tmp_path, "test")
    assert name and (tmp_path / name).is_file()

    document = docx.Document(str(tmp_path / name))
    headings = [p.text for p in document.paragraphs
                if p.style.name.startswith("Heading")]
    for number, title in ((s.number, s.title) for s in spec.sections):
        assert f"{number}. {title}" in headings
    # Значения, которые читатель ищет первыми, лежат в таблице, а не в прозе.
    said = "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
    assert "ИТМО" in said


def test_both_formats_are_written_from_one_assembly(tmp_path):
    spec = spec_from_frame(_frame(formulation="Вопрос"))
    docx_name, md_name = write_tz_files(spec, tmp_path, "test")
    assert docx_name and md_name
    text = (tmp_path / md_name).read_text(encoding="utf-8")
    for number, title in ((s.number, s.title) for s in spec.sections):
        assert f"{number}. {title}" in text


def test_a_document_that_cannot_be_written_does_not_stop_the_research(tmp_path):
    """Исследование, остановленное тем, что не собрался .docx, хуже, чем
    исследование без .docx."""
    import CoScientist.context_init.tz_docx as mod

    spec = spec_from_frame(ResearchFrame.blank())

    def explode(_spec):
        raise RuntimeError("python-docx недоступен")

    original, mod.build_tz_docx = mod.build_tz_docx, explode
    try:
        docx_name, md_name = write_tz_files(spec, tmp_path, "test")
    finally:
        mod.build_tz_docx = original
    assert docx_name is None and md_name


# ── граф ────────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    s = ResearchGraphStore(directory=str(tmp_path))
    s.ensure_root("Насколько токсичны метаболиты борщевика?")
    return s


def _frame_card(store):
    """Карточка «Постановка», или None — она проекция и рисуется, только когда
    есть что показать."""
    return next((n for n in store.to_view()["nodes"] if n["id"] == FRAME_ID), None)


def _attached_specs(card):
    return [a for a in (card or {}).get("attachments", []) if a["kind"] == "spec"]


def test_the_specification_hangs_off_the_framing_card(store):
    """Панель делает ссылку из вложения и инертный текст из атрибута, так что
    это единственный способ открыть документ из графа."""
    from CoScientist.context_init.tz_agent import publish_spec

    spec = spec_from_frame(_frame(formulation="Вопрос"))
    docx_name, _ = publish_spec(spec, store, store._dir / "tz")
    assert docx_name

    specs = _attached_specs(_frame_card(store))
    assert len(specs) == 1, specs
    assert specs[0]["href"].startswith("/api/tz-document?name=")


def test_a_specification_derived_from_a_conclusion_stays_with_it(store):
    """Условие, а не перенос типа: ТЗ пишется до исследования, а спецификация,
    выведенная из вывода, принадлежит выводу."""
    r = store.commit(source="OrchestratorAgent", enforce_permissions=False, nodes=[
        {"type": "Conclusion", "ref": "cl_new", "attrs": {"synthesis": "Вывод."}},
        {"type": "Spec", "ref": "sp_new", "attrs": {"content": "Спецификация."}},
    ], edges=[{"type": "derived_from", "from": "#sp_new", "to": "#cl_new"}])
    assert r.ok, r.errors
    assert not _attached_specs(_frame_card(store))
    # И лежит там, откуда выведена.
    conclusion = next(n for n in store.to_view()["nodes"] if n["kind"] == "conclusion")
    assert [a["kind"] for a in conclusion["attachments"]] == ["spec"]


def test_the_link_the_card_carries_is_the_one_the_chat_carries():
    """Один адрес в двух местах: `chat.js` делает ссылку из голого
    `/api/tz-document…`, `store._href` пропускает `/api/…` в карточку. Разойдись
    они — одна из двух ссылок молча перестанет открываться."""
    from CoScientist.context_init.tz_agent import _link, announcement

    said = announcement("ТЗ_20260923.docx", "ТЗ_20260923.md")
    assert _link("ТЗ_20260923.docx") in said
    assert "ГОСТ 19.201-78" in said
    # Тело документа в ленту не выгружается.
    assert len(said.splitlines()) <= 4
