from uuid import uuid4

import pytest

from CoScientist.cli import _configure_utf8_stdio, _run_graph, main
from CoScientist.graph.memory import get_knowledge_graph
from CoScientist.graph.memory_store import get_global_knowledge_memory
from CoScientist.graph.semantic import Entity, Extraction, Relation


def test_graph_cli_reads_scoped_execution_and_knowledge(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "graph_runs"))
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "graph_runs" / "knowledge_memory.json"),
    )
    token = uuid4().hex
    user_id = f"user-{token}"
    session_id = f"session-{token}"
    invocation_id = f"inv-{token}"
    goal_id = f"goal:{invocation_id}"

    execution = get_knowledge_graph(user_id=user_id, session_id=session_id)
    execution.add_node(
        id=goal_id,
        kind="goal",
        label="Scoped CLI question",
        status="success",
    )
    get_global_knowledge_memory().ingest(
        Extraction(
            entities=[
                Entity(key="molecule:a", type="molecule", name="A"),
                Entity(key="target:b", type="target", name="B"),
            ],
            relations=[
                Relation(src="molecule:a", dst="target:b", type="inhibits")
            ],
        ),
        source="Scoped CLI question",
        refs={
            "user_id": user_id,
            "session_id": session_id,
            "run": invocation_id,
            "goal_id": goal_id,
            "result_id": f"result:{invocation_id}",
        },
    )

    _run_graph(
        "show",
        "session",
        None,
        "execution",
        user_id=user_id,
        session_id=session_id,
    )
    execution_output = capsys.readouterr().out
    assert f"user={user_id} session={session_id}" in execution_output
    assert "Scoped CLI question" in execution_output

    _run_graph(
        "show",
        "session",
        None,
        "knowledge",
        user_id=user_id,
        session_id=session_id,
    )
    knowledge_output = capsys.readouterr().out
    assert "A inhibits B" in knowledge_output


def test_graph_cli_requires_complete_scope_pair():
    with pytest.raises(SystemExit):
        main(["graph", "show", "--user-id", "user-only"])


def test_cli_configures_scientific_unicode_output(monkeypatch):
    class Stream:
        def __init__(self):
            self.encodings = []

        def reconfigure(self, *, encoding):
            self.encodings.append(encoding)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr("CoScientist.cli.sys.stdout", stdout)
    monkeypatch.setattr("CoScientist.cli.sys.stderr", stderr)

    _configure_utf8_stdio()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]
