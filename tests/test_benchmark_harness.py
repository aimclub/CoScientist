"""Benchmark harness: the IO contract and the post-run classifiers.

Fast and offline — no agent, no verifier run. The end-to-end check is
``python -m benchmarks.harness run --agent oracle``, which must score 1.0 on
every task whose verifier can run on the host.
"""
import json
import re

import pytest

from benchmarks.harness import analysis
from benchmarks.harness.tasks import iter_tasks

TASKS = iter_tasks()


def test_all_selected_tasks_load():
    assert {t.name for t in TASKS} == {
        "geometric-pharmacophore-alignment",
        "foodstuff-beta-activity", "glycan-ms2-elucidation",
        "hof-topology-interpenetration", "roy-polymorph-cn",
    }


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_io_contract(task):
    spec = task.io_spec()
    assert spec["inputs"] and spec["outputs"]
    for item in spec["inputs"]:
        assert (task.path / item["source"]).is_file()
        assert item["target"].startswith("/")
    committed = json.loads((task.path / "io.json").read_text())
    assert committed == spec, "io.json is stale: run `python -m benchmarks.harness sync`"


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_prompt_has_no_container_paths(task):
    prompt = task.render_prompt(600)
    body = prompt.split("---", 1)[1]
    roots = "|".join(task.roots())
    assert not re.search(rf"(?<![\w.])/({roots})/", body)
    # Upstream wording does not always spell out the full path; the preamble does.
    given = {i["target"] for i in task.inputs()}
    for out in task.outputs():
        if out["path"] not in given:
            assert task.localize(out["path"]) in prompt


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_seeded_workspace_matches_inputs(task, tmp_path):
    seeded = task.seed_workspace(tmp_path)
    for item in seeded:
        assert (tmp_path / item["target"].lstrip("/")).is_file()


def _tests(*cases):
    return {"total": len(cases), "passed": sum(s == "passed" for _, s in cases),
            "cases": [{"name": n, "status": s} for n, s in cases]}


@pytest.mark.parametrize("result,tests,present,misplaced,expected", [
    ({"reward": 1.0}, _tests(("t::test_values", "passed")), True, [], "solved"),
    ({"reward": 0.0}, _tests(("t::test_file_exists", "failed")), False, [], "no_output"),
    ({"reward": 0.0}, None, False, ["results.txt"], "wrong_output_path"),
    ({"reward": 0.0, "agent_status": "timeout"}, None, False, [], "timeout_no_output"),
    ({"reward": 0.0}, _tests(("t::test_sig_figs", "failed"), ("t::test_value_within_tolerance", "failed")),
     True, [], "format_error"),
    ({"reward": 0.0}, _tests(("t::test_value_within_tolerance", "failed")), True, [], "wrong_answer"),
    ({"reward": None}, None, True, [], "unverified"),
])
def test_outcome_classification(result, tests, present, misplaced, expected):
    arts = [{"path": "/app/x", "present": present}]
    assert analysis.classify_outcome(result, tests, arts, misplaced) == expected


def test_integrity_flags_answer_hunting_not_own_scripts(tmp_path):
    trial = tmp_path / "run" / "bench" / "task" / "trial-1"
    (trial / "workspace").mkdir(parents=True)

    def ev(cmd):
        return {"ev": "tool", "tool": "execute_bash", "args": json.dumps({"command": cmd})}

    own = [ev("python solve.py"), ev(f"cd {trial / 'ws_workspace'} && ls results")]
    assert analysis.integrity(trial, own)["clean"]
    hunting = analysis.integrity(trial, [ev("find / -name solve.sh")])
    assert hunting["suspicious_accesses"] and not hunting["clean"]
    escaped = analysis.integrity(trial, [ev(f"cat {trial / 'input' / 'io.json'}")])
    assert escaped["escaped_workspace"] and not escaped["clean"]


# ── OpenHands coder: data through the sandbox ────────────────────────────────
import io
import zipfile

from benchmarks.harness import sandbox_io


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_openhands_prompt_points_into_sandbox_workspace(task):
    prompt = task.render_prompt(600, "openhands")
    body = prompt.split("---", 1)[1]
    roots = "|".join(task.roots())
    assert not re.search(rf"(?<![\w.])/({roots})/", body.replace("/workspace/", "@"))
    assert "dataset_url" in prompt
    given = {i["target"] for i in task.inputs()}
    for out in task.outputs():
        if out["path"] not in given:
            assert "/workspace" + out["path"].rstrip("/") in prompt


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_inputs_zip_has_container_layout(task, tmp_path):
    task.seed_workspace(tmp_path)
    names = set(zipfile.ZipFile(io.BytesIO(sandbox_io.inputs_zip(task, tmp_path))).namelist())
    for item in task.inputs():
        assert item["target"].lstrip("/") in names
    for d in task.precreated_dirs():
        assert d.strip("/") + "/" in names


def test_sandbox_ids_newest_last(tmp_path):
    (tmp_path / "trace").mkdir()
    (tmp_path / "trace" / "events.jsonl").write_text(
        json.dumps({"result": json.dumps({"sandbox_id": "a1"})}) + "\n"
        + json.dumps({"result": "watch http://x/console?task_id=b2"}) + "\n")
    assert sandbox_io.sandbox_ids(tmp_path) == ["a1", "b2"]
    assert sandbox_io.sandbox_ids(tmp_path, ["a1"]) == ["b2", "a1"]


def test_fetch_outputs_prefers_newest_sandbox(tmp_path, monkeypatch):
    task = next(t for t in TASKS if t.name == "roy-polymorph-cn")
    files = {("old", "/workspace/results/TB3_Conf_Answers.csv"): b"stale",
             ("new", "/workspace/results/TB3_Conf_Answers.csv"): b"Answers\n1"}
    monkeypatch.setattr(sandbox_io, "sandbox_api", lambda: "http://sandbox/api/v1")
    monkeypatch.setattr(sandbox_io, "_download", lambda api, sid, path: files.get((sid, path)))
    got = sandbox_io.fetch_outputs(task, tmp_path, ["old", "new"])
    assert got[0]["sandbox_id"] == "new"
    assert (tmp_path / "workspace/results/TB3_Conf_Answers.csv").read_bytes() == b"Answers\n1"


def test_task_output_dir_named_solution_is_not_a_leak(tmp_path):
    trial = tmp_path / "run" / "bench" / "task" / "trial-1"
    (trial / "workspace").mkdir(parents=True)
    ev = {"ev": "tool", "tool": "execute_bash",
          "args": json.dumps({"command": "python hof.py > app/solution/output.json"})}
    assert analysis.integrity(trial, [ev])["clean"]
