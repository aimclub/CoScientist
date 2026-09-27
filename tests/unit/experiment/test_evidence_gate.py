"""Unit tests for the Scientific Evidence Gate (evidence.py, state_machine, validator, reporting)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from CoScientist.config.settings import ExperimentsSettings
from CoScientist.experiments.critique import critique_plan
from CoScientist.experiments.reporting.models import ArtifactRef, CriterionCheck
from CoScientist.experiments.runtime import (
    approve_plan,
    initialize_runtime,
    on_route_agent_returned,
    record_result,
    start_task,
)
from CoScientist.experiments.runtime.evidence import (
    bind_criteria_evidence,
    is_placeholder_value,
    scan_placeholder_outputs,
    verify_threshold_criteria,
)
from CoScientist.experiments.schemas import ExperimentPlan, ExperimentTask
from CoScientist.reporting.collect import _table_to_markdown

from .helpers import NOW, _approved_state, _design, _plan, _route_return, _server, _task


def test_is_placeholder_value():
    assert is_placeholder_value("") is True
    assert is_placeholder_value("   ") is True
    assert is_placeholder_value(None) is True
    assert is_placeholder_value([]) is True
    assert is_placeholder_value({}) is True
    assert is_placeholder_value("result.csv", expected_names={"result.csv"}) is True
    assert is_placeholder_value("CC(=O)Oc1ccccc1C(=O)O") is False
    assert is_placeholder_value(42.0) is False


def test_scan_placeholder_outputs():
    outputs = {
        "smiles": "",
        "score": -8.5,
        "dummy_key": None,
        "notes": "Valid notes text",
    }
    dropped = scan_placeholder_outputs(outputs)
    assert set(dropped) == {"smiles", "dummy_key"}


def test_placeholder_outputs_purged_in_record_result(tmp_path: Path):
    plan = _plan(_task("EXP-1"))
    state = _approved_state(plan)
    cfg = ExperimentsSettings(evidence_strict=True, route_fedot=True)
    envelope = start_task(state, "EXP-1", settings=cfg)
    attempt_id = envelope["attempt_id"]
    _route_return(state, "FedotAgent")

    result_payload = {
        "status": "success",
        "summary": "Completed with vacant outputs",
        "outputs": {
            "smiles": "",
            "table": None,
        },
        "artifacts": [],
        "criteria_checks": [
            {"criterion_id": "EXP-1-C1", "passed": True, "details": "Done"},
        ],
    }
    recorded = record_result(state, "EXP-1", attempt_id, result_payload, settings=cfg)
    # Since only empty values existed and no real artifacts, status must be downgraded to failure
    task_res = recorded["task_result"]
    assert task_res["status"] == "failure"
    assert task_res["error_code"] == "placeholder_only_outputs"
    assert any("placeholder_outputs_dropped:smiles,table" in w for w in task_res["warnings"])


def test_threshold_criterion_measured_from_csv(tmp_path: Path):
    csv_file = tmp_path / "docking_results.csv"
    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["smiles", "docking_score", "cluster"])
        writer.writerow(["CCO", -8.2, 1])
        writer.writerow(["c1ccccc1", -9.1, 2])
        writer.writerow(["CCN", -7.0, 1])

    task_dict = _task("EXP-1", artifact_name="docking_results.csv")
    task_dict["design"]["metrics"] = [
        {"name": "docking_score", "direction": "minimize", "threshold": -8.0, "test": None}
    ]
    task_dict["success_criteria"] = [
        {
            "criterion_id": "EXP-1-C1",
            "description": "Docking score <= -8.0",
            "kind": "threshold",
            "metric": "docking_score",
            "operator": "<=",
            "target": -8.0,
            "required": True,
            "verification": "Check CSV",
        }
    ]
    task = ExperimentTask.model_validate(task_dict)
    art = ArtifactRef(
        artifact_id="ART-1",
        plan_id="PLAN-1",
        task_id="EXP-1",
        attempt_id="ATT-1",
        role="data",
        name="docking_results.csv",
        workspace_path=str(csv_file),
        media_type="text/csv",
        producer_route="fedot_mas",
        created_at=NOW,
        durability="workspace",
    )

    checks = [
        CriterionCheck(
            criterion_id="EXP-1-C1",
            passed=None,
            observed=None,
            evidence_artifact_ids=["ART-1"],
            details="Pending",
        )
    ]
    verified = verify_threshold_criteria(task, checks, [art])
    assert len(verified) == 1
    assert verified[0].passed is True
    # min was -9.1, which is <= -8.0
    assert pytest.approx(verified[0].observed) == -9.1


def test_threshold_criterion_fails_when_unachievable(tmp_path: Path):
    csv_file = tmp_path / "docking_poor.csv"
    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["smiles", "docking_score"])
        writer.writerow(["CCO", -5.5])
        writer.writerow(["CCN", -6.0])

    task_dict = _task("EXP-1", artifact_name="docking_poor.csv")
    task_dict["design"]["metrics"] = [
        {"name": "docking_score", "direction": "minimize", "threshold": -8.0, "test": None}
    ]
    task_dict["success_criteria"] = [
        {
            "criterion_id": "EXP-1-C1",
            "description": "Docking score <= -8.0",
            "kind": "threshold",
            "metric": "docking_score",
            "operator": "<=",
            "target": -8.0,
            "required": True,
            "verification": "Check CSV",
        }
    ]
    task = ExperimentTask.model_validate(task_dict)
    art = ArtifactRef(
        artifact_id="ART-2",
        plan_id="PLAN-1",
        task_id="EXP-1",
        attempt_id="ATT-1",
        role="data",
        name="docking_poor.csv",
        workspace_path=str(csv_file),
        media_type="text/csv",
        producer_route="fedot_mas",
        created_at=NOW,
        durability="workspace",
    )

    checks = [
        CriterionCheck(
            criterion_id="EXP-1-C1",
            passed=None,
            observed=None,
            evidence_artifact_ids=["ART-2"],
            details="Pending",
        )
    ]
    verified = verify_threshold_criteria(task, checks, [art])
    assert verified[0].passed is False
    assert pytest.approx(verified[0].observed) == -6.0
    assert "passed=False" in verified[0].details or "not met" in verified[0].details.lower()


def test_composite_step_passes_both_tools_to_coder():
    srv1 = _server(tool="generate_mols", url="http://127.0.0.1:8001/mcp")
    srv2 = _server(tool="calculate_docking", url="http://127.0.0.1:8002/mcp")
    task_dict = _task("EXP-1", route="coder")
    task_dict["mcp_servers"] = [srv1, srv2]
    task_dict["expected_artifacts"] = [
        {"name": "generate_mols_out.csv", "role": "data", "media_type": "text/csv", "description": "Generated mols"},
        {"name": "calculate_docking_out.csv", "role": "data", "media_type": "text/csv", "description": "Docking out"},
    ]

    plan = _plan(task_dict)
    state = _approved_state(plan)
    cfg = ExperimentsSettings(route_coder_mcp=True)
    envelope = start_task(state, "EXP-1", settings=cfg)

    # Both tools should be preserved in filtered_tools and envelope task mcp_servers
    assert len(state["filtered_tools"]) == 2
    tools_in_scope = {t["tool"] for t in state["filtered_tools"]}
    assert tools_in_scope == {"generate_mols", "calculate_docking"}
    assert envelope["route"] == "coder"


def test_hypothesis_honesty_not_faked():
    from CoScientist.experiments.schemas.models import HypothesisSpec
    plan = _plan(_task("EXP-1", hypothesis_ref="H1"))
    plan = plan.model_copy(update={
        "hypotheses": [
            HypothesisSpec(hypothesis_id="H1", statement="H1 is testable"),
            HypothesisSpec(hypothesis_id="H2", statement="H2 is futuristic and has no method"),
        ]
    })
    cfg = ExperimentsSettings()
    # Context has H1 and H2, but available operations only mention OP-1 for H1
    context_hypotheses = [
        {"hypothesis_id": "H1", "statement": "H1 is testable"},
        {"hypothesis_id": "H2", "statement": "H2 is futuristic and has no method"},
    ]
    operations = [
        {"operation_id": "OP-1", "statement": "Compute property for H1", "hypothesis_ref": "H1"}
    ]
    critique = critique_plan(
        plan,
        settings=cfg,
        hypothesis_refs=context_hypotheses,
        operations=operations,
    )
    # H2 is untestable at this stage, so it should emit minor hypothesis_not_testable_at_this_stage, not major
    h2_issues = [i for i in critique.issues if "H2" in i.message]
    assert any(i.severity == "minor" and "hypothesis_not_testable_at_this_stage" in i.message for i in h2_issues)
    assert not any(i.severity == "major" and "H2" in i.message for i in h2_issues)


def test_binary_artifact_excluded_from_markdown_tables(tmp_path: Path):
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 binary data \x00\x01\x02\nstream\nendstream")
    md = _table_to_markdown(pdf_file)
    assert md is None

    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK\x03\x04 fake zip content \x00\x00")
    md_zip = _table_to_markdown(zip_file)
    assert md_zip is None

    html_file = tmp_path / "page.html"
    html_file.write_text("<!DOCTYPE html><html><body>Table</body></html>", encoding="utf-8")
    md_html = _table_to_markdown(html_file)
    assert md_html is None


def test_verify_threshold_criteria_sample_size_count(tmp_path: Path):
    from CoScientist.experiments.schemas.models import SuccessCriterion
    task_dict = _task("EXP-1")
    task_dict["success_criteria"] = [
        SuccessCriterion(
            criterion_id="C1",
            description="generate at least 10 molecules",
            kind="threshold",
            metric="num_molecules",
            operator=">=",
            target=10.0,
            required=True,
            verification="Check molecule count in json",
        )
    ]
    task = ExperimentTask.model_validate(task_dict)
    # Create JSON with molecules list of length 15
    json_path = tmp_path / "molecules.json"
    json_path.write_text(json.dumps({
        "molecules": [{"SMILES": f"C{i}"} for i in range(15)]
    }), encoding="utf-8")
    art = ArtifactRef(
        artifact_id="ART-1",
        plan_id="PLAN-1",
        task_id="EXP-1",
        attempt_id="ATT-1",
        name="molecules.json",
        workspace_path=str(json_path),
        role="data",
        media_type="application/json",
        producer_route="fedot_mas",
        created_at=NOW,
        durability="workspace",
    )
    checks = [CriterionCheck(criterion_id="C1", passed=None, observed=None, details="Pending")]
    verified = verify_threshold_criteria(task, checks, [art])
    assert len(verified) == 1
    assert verified[0].passed is True
    assert verified[0].observed == 15.0


def test_skip_task_allowed_when_has_prior_attempts(tmp_path: Path):
    from CoScientist.experiments.runtime import skip_task, retry_task, fallback_task
    task = _task("EXP-1", optional=False)
    plan = _plan(task)
    state = _approved_state(plan)
    cfg = ExperimentsSettings(evidence_strict=True, route_fedot=True)
    # Start attempt 1
    envelope = start_task(state, "EXP-1", settings=cfg)
    attempt_id = envelope["attempt_id"]
    _route_return(state, "FedotAgent")
    # Record failed attempt
    record_result(state, "EXP-1", attempt_id, {
        "status": "failure",
        "error_code": "mcp_error",
        "error_message": "Attempt failed",
        "summary": "Attempt failed",
        "retryable": True,
    }, settings=cfg)
    
    # Task is now in retry_pending. Suppose it transitions to fallback_pending -> fallback_task -> ready
    from CoScientist.experiments.runtime.state_machine import _runtime, _task as get_task
    runtime = _runtime(state)
    task_rt = get_task(runtime, "EXP-1")
    task_rt["status"] = "fallback_pending"
    fb_res = fallback_task(state, "EXP-1", "mcp failed", settings=cfg)
    assert fb_res["status"] == "success"
    assert task_rt["status"] == "ready"

    # Even though status is ready and task is not optional, it has prior attempts, so skip_task must succeed
    skip_res = skip_task(state, "EXP-1", "Skipping after stuck fallback")
    assert skip_res["status"] == "success"
    assert task_rt["status"] == "skipped"

