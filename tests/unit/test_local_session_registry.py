import re

import pytest

from CoScientist.web.session_registry import LocalSessionRegistry


def test_users_and_sessions_receive_random_ids_and_stay_isolated():
    registry = LocalSessionRegistry()
    gleb = registry.create_user("  Gleb   Test  ")
    alex = registry.create_user("Alex")

    assert gleb["nickname"] == "Gleb Test"
    assert re.fullmatch(r"user_[0-9a-f]{32}", gleb["id"])

    gleb_session = registry.create_session(gleb["id"], "GSK analysis")
    alex_session = registry.create_session(alex["id"], "Other work")
    assert re.fullmatch(r"session_[0-9a-f]{32}", gleb_session["id"])
    assert [item["id"] for item in registry.list_sessions(gleb["id"])] == [gleb_session["id"]]
    assert [item["id"] for item in registry.list_sessions(alex["id"])] == [alex_session["id"]]


def test_nicknames_are_unique_case_insensitively():
    registry = LocalSessionRegistry()
    registry.create_user("Gleb")
    with pytest.raises(ValueError, match="already registered"):
        registry.create_user("gleb")


def test_touch_and_rename_update_session_metadata():
    registry = LocalSessionRegistry()
    user = registry.create_user("Gleb")
    session = registry.create_session(user["id"], "Initial")

    renamed = registry.rename_session(user["id"], session["id"], "New title")
    touched = registry.touch_session(user["id"], session["id"], status="processing")

    assert renamed["title"] == "New title"
    assert touched["status"] == "processing"
    assert registry.get_user(user["id"])["last_session_id"] == session["id"]



def test_hide_old_sessions_keeps_the_given_and_running_ones():
    registry = LocalSessionRegistry(persist=False)
    user = registry.create_user("Gleb")
    other = registry.create_user("Alex")
    old = registry.create_session(user["id"], "Old run")
    running = registry.create_session(user["id"], "Running")
    registry.touch_session(user["id"], running["id"], status="processing")
    fresh = registry.create_session(user["id"], "Fresh")
    foreign = registry.create_session(other["id"], "Not mine")

    assert registry.hide_old_sessions(user["id"], keep=[fresh["id"]]) == 1
    hidden = {item["id"]: item.get("hidden", False) for item in registry.list_sessions(user["id"])}
    assert hidden == {old["id"]: True, running["id"]: False, fresh["id"]: False}
    assert registry.get_session(user["id"], old["id"])["updated_at"] == old["updated_at"]
    assert "hidden" not in registry.get_session(other["id"], foreign["id"])

    assert registry.unhide_sessions(user["id"]) == 1
    assert not any(item.get("hidden") for item in registry.list_sessions(user["id"]))


def test_imported_session_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_STATE_DIR", str(tmp_path))
    registry = LocalSessionRegistry()
    user = registry.create_user("Gleb")
    registry.import_session(user["id"], "session_imported", "KM-ARL run 11",
                            created_at="2026-09-27T13:05:32+00:00")

    reopened = LocalSessionRegistry()
    session = reopened.get_session(user["id"], "session_imported")
    assert session is not None
    assert session["title"] == "KM-ARL run 11"
    assert session["created_at"] == "2026-09-27T13:05:32+00:00"


def test_deleting_the_last_session_repoints_last_session_id():
    registry = LocalSessionRegistry()
    user = registry.create_user("Gleb")
    older = registry.create_session(user["id"], "Older")
    newer = registry.create_session(user["id"], "Newer")
    assert registry.get_user(user["id"])["last_session_id"] == newer["id"]

    registry.delete_session(user["id"], newer["id"])
    assert registry.get_session(user["id"], newer["id"]) is None
    assert registry.get_user(user["id"])["last_session_id"] == older["id"]

    registry.delete_session(user["id"], older["id"])
    assert registry.get_user(user["id"])["last_session_id"] is None
    with pytest.raises(KeyError):
        registry.delete_session(user["id"], older["id"])


def test_deleting_a_user_drops_their_sessions_and_frees_the_nickname(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_STATE_DIR", str(tmp_path))
    registry = LocalSessionRegistry()
    gleb = registry.create_user("Gleb")
    alex = registry.create_user("Alex")
    first = registry.create_session(gleb["id"], "One")
    second = registry.create_session(gleb["id"], "Two")
    kept = registry.create_session(alex["id"], "Alex work")

    assert sorted(registry.delete_user(gleb["id"])) == sorted([first["id"], second["id"]])
    assert registry.get_user(gleb["id"]) is None
    assert registry.create_user("gleb")["nickname"] == "gleb"

    reopened = LocalSessionRegistry()
    assert [u["nickname"] for u in reopened.list_users()] == ["Alex", "gleb"]
    assert reopened.get_session(alex["id"], kept["id"]) is not None
    assert reopened.get_session(gleb["id"], first["id"]) is None


def test_rename_user_keeps_nicknames_unique(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_STATE_DIR", str(tmp_path))
    registry = LocalSessionRegistry()
    gleb = registry.create_user("Gleb")
    registry.create_user("Alex")

    with pytest.raises(ValueError, match="already registered"):
        registry.rename_user(gleb["id"], "alex")
    assert registry.rename_user(gleb["id"], "GLEB")["nickname"] == "GLEB"
    assert registry.rename_user(gleb["id"], "  Gleb   K ")["nickname"] == "Gleb K"
    # The old name is free again; the new one is taken.
    registry.create_user("Gleb")
    with pytest.raises(ValueError, match="already registered"):
        registry.create_user("gleb k")
    assert LocalSessionRegistry().get_user(gleb["id"])["nickname"] == "Gleb K"
