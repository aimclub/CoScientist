from types import SimpleNamespace

from CoScientist.agents.callbacks.link_registry import (
    USER_LINKS_STATE_KEY,
    user_links,
)
from CoScientist.agents.callbacks.tool_callbacks import (
    USER_FILES_CONTEXT_STATE_KEY,
    USER_TEXT_FILES_STATE_KEY,
    inject_user_files_context,
)


def _context(state):
    return SimpleNamespace(state=state, user_content=None)


def test_user_text_file_is_rendered_as_distinct_agent_context():
    state = {
        USER_TEXT_FILES_STATE_KEY: [{
            "filename": "источники.md",
            "size": 42,
            "content": "# Данные\nСм. https://example.org/source.txt",
        }]
    }
    context = _context(state)

    inject_user_files_context(context)

    rendered = state[USER_FILES_CONTEXT_STATE_KEY]
    assert "## User-attached text files" in rendered
    assert "### источники.md" in rendered
    assert "# Данные" in rendered


def test_no_user_text_file_renders_empty_context():
    state = {}
    inject_user_files_context(_context(state))
    assert state[USER_FILES_CONTEXT_STATE_KEY] == ""


def test_link_registry_scans_urls_from_user_text_context():
    state = {
        USER_TEXT_FILES_STATE_KEY: [{
            "filename": "links.txt",
            "size": 30,
            "content": "Read https://example.org/source.txt",
        }]
    }
    context = _context(state)
    inject_user_files_context(context)
    user_links(context)

    (entry,) = state[USER_LINKS_STATE_KEY].values()
    assert entry["url"] == "https://example.org/source.txt"
    assert entry["role"] == "text file"
