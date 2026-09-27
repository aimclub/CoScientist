"""Evidence verification and placeholder gating for Experiment Module.

Uses stdlib only (re, csv, json, pathlib).
Enforces scientific honesty:
1. Detects and purges empty/missing outputs.
2. Binds criteria checks to concrete artifact evidence.
3. Measures threshold criteria against data extracted from CSV/JSON artifacts.
"""
from __future__ import annotations

import csv
import json
import logging
import operator as op_module
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from CoScientist.experiments.reporting.models import ArtifactRef, CriterionCheck
from CoScientist.experiments.runtime.shared import artifact_name_key
from CoScientist.experiments.schemas.models import ExperimentTask

logger = logging.getLogger(__name__)

_OPERATOR_TABLE: Mapping[str, Callable[[Any, Any], bool]] = {
    "<=": op_module.le,
    "≤": op_module.le,
    ">=": op_module.ge,
    "≥": op_module.ge,
    "<": op_module.lt,
    ">": op_module.gt,
    "==": op_module.eq,
    "=": op_module.eq,
    "!=": op_module.ne,
    "≠": op_module.ne,
    "in": lambda a, b: a in b if hasattr(b, "__contains__") else False,
}


def is_placeholder_value(val: Any, expected_names: set[str] | None = None) -> bool:
    """Return True if val represents missing data or self-reference."""
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return True
        if expected_names and s.lower() in expected_names:
            return True
        return False
    if isinstance(val, (list, tuple)):
        if not val:
            return True
        return all(is_placeholder_value(x, expected_names) for x in val)
    if isinstance(val, dict):
        if not val:
            return True
        return all(is_placeholder_value(v, expected_names) for v in val.values())
    return False


def scan_placeholder_outputs(
    outputs: Mapping[str, Any] | None,
    expected_names: Sequence[str] | None = None,
) -> list[str]:
    """Scan outputs dictionary and return list of keys that contain vacant/placeholder values."""
    if not isinstance(outputs, Mapping):
        return []
    names_set = {n.lower().strip() for n in expected_names or [] if n and str(n).strip()}
    dropped: list[str] = []
    for k, v in outputs.items():
        if is_placeholder_value(v, names_set):
            dropped.append(str(k))
    return dropped


def _match_artifact_for_criterion(
    crit: Any,
    task: ExperimentTask,
    artifacts: Sequence[ArtifactRef],
) -> ArtifactRef | None:
    """Find a concrete artifact that serves as evidence for a criterion."""
    if not artifacts:
        return None

    # 1. If criterion references an expected artifact by name or target
    target = str(getattr(crit, "target", "") or "").strip()
    metric = str(getattr(crit, "metric", "") or "").strip()
    crit_desc = str(getattr(crit, "description", "") or "").lower()

    # Exact or normalized match against artifact names
    for a in artifacts:
        if not a.artifact_id:
            continue
        aname = a.name.lower()
        if target and (a.name == target or aname == target.lower()):
            return a
        if metric and aname == metric.lower():
            return a

    # 2. Check expected artifacts associated with task
    for exp in task.expected_artifacts:
        exp_name = str(exp.name or "").strip()
        if exp_name and (exp_name.lower() in crit_desc or (target and exp_name.lower() == target.lower())):
            for a in artifacts:
                if a.name == exp_name or artifact_name_key(a.name) == artifact_name_key(exp_name):
                    return a

    return None


def bind_criteria_evidence(
    task: ExperimentTask,
    checks: list[CriterionCheck],
    artifacts: list[ArtifactRef],
) -> list[CriterionCheck]:
    """Ensure each criterion check has evidence_artifact_ids populated if a matching artifact exists."""
    if not artifacts:
        return checks

    task_criteria = {c.criterion_id: c for c in task.success_criteria}
    out: list[CriterionCheck] = []

    for check in checks:
        crit = task_criteria.get(check.criterion_id)
        if not check.evidence_artifact_ids and crit is not None:
            hit = _match_artifact_for_criterion(crit, task, artifacts)
            if hit is not None and hit.artifact_id:
                check = check.model_copy(update={
                    "evidence_artifact_ids": [hit.artifact_id],
                })
        out.append(check)

    return out


def _compare_operator(observed: float, operator: str, target: float) -> bool:
    cmp_fn = _OPERATOR_TABLE.get(operator.strip())
    if cmp_fn is not None:
        try:
            return bool(cmp_fn(observed, target))
        except (TypeError, ValueError):
            return False
    return False


def _extract_metric_from_csv(path: Path, metric_name: str, direction: str | None) -> float | None:
    try:
        with open(path, mode="r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return None
            target_key = metric_name.strip().lower()
            col = None
            for fld in reader.fieldnames:
                if fld and fld.strip().lower() == target_key:
                    col = fld
                    break
            if not col:
                return None
            vals: list[float] = []
            for row in reader:
                raw_v = row.get(col)
                if raw_v is not None and str(raw_v).strip():
                    try:
                        vals.append(float(str(raw_v).strip()))
                    except (ValueError, TypeError):
                        continue
            if not vals:
                return None
            dir_str = (direction or "").lower()
            if dir_str == "minimize":
                return min(vals)
            if dir_str == "maximize":
                return max(vals)
            return vals[0]
    except Exception as exc:
        logger.warning("Failed to extract metric from CSV %s: %s", path, exc)
        return None


def _extract_metric_from_json(path: Path, metric_name: str, direction: str | None) -> float | None:
    try:
        with open(path, mode="r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        target_key = metric_name.strip().lower()

        def _search(obj: Any) -> list[float]:
            found: list[float] = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if str(k).strip().lower() == target_key:
                        try:
                            found.append(float(v))
                        except (ValueError, TypeError):
                            pass
                    else:
                        found.extend(_search(v))
            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    found.extend(_search(item))
            return found

        vals = _search(data)
        if vals:
            dir_str = (direction or "").lower()
            if dir_str == "minimize":
                return min(vals)
            if dir_str == "maximize":
                return max(vals)
            return vals[0]
        return None
    except Exception as exc:
        logger.warning("Failed to extract metric from JSON %s: %s", path, exc)
        return None


def _measure_artifact_size(path: Path) -> float | None:
    """Measure tabular row count or top-level array length for structural size criteria."""
    try:
        if path.suffix.lower() in (".csv", ".tsv"):
            with open(path, mode="r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    return 0.0
                return float(sum(1 for _ in reader))
        if path.suffix.lower() == ".json":
            with open(path, mode="r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if isinstance(data, list):
                return float(len(data))
            if isinstance(data, dict):
                # Only check direct top-level collections
                direct_lists = [len(v) for v in data.values() if isinstance(v, list)]
                if direct_lists:
                    return float(max(direct_lists))
    except Exception as exc:
        logger.warning("Failed to measure artifact size for %s: %s", path, exc)
    return None


def verify_threshold_criteria(
    task: ExperimentTask,
    checks: list[CriterionCheck],
    artifacts: Sequence[ArtifactRef],
) -> list[CriterionCheck]:
    """Verify threshold criteria by extracting observed values from evidence artifacts and comparing."""
    crit_map = {c.criterion_id: c for c in task.success_criteria}
    art_map = {a.artifact_id: a for a in artifacts if a.artifact_id}
    metric_directions = {
        m.name.lower(): m.direction for m in task.design.metrics if m.name
    }

    out: list[CriterionCheck] = []
    for check in checks:
        crit = crit_map.get(check.criterion_id)
        if crit is None or str(crit.kind) != "threshold":
            out.append(check)
            continue

        metric = str(crit.metric or "").strip()
        op = str(crit.operator or "==").strip()
        target = crit.target
        target_num = None
        if target is not None:
            try:
                target_num = float(target)
            except (ValueError, TypeError):
                target_num = None

        observed = check.observed
        obs_num = None
        if observed is not None and not isinstance(observed, bool):
            try:
                obs_num = float(observed)
            except (ValueError, TypeError):
                obs_num = None

        if obs_num is None:
            # Attempt to extract from bound artifacts
            candidate_arts: list[ArtifactRef] = []
            for aid in check.evidence_artifact_ids:
                if aid in art_map:
                    candidate_arts.append(art_map[aid])
            if not candidate_arts:
                candidate_arts = [a for a in artifacts if a.role in ("data", "model") or a.name.endswith((".csv", ".json"))]

            dir_choice = metric_directions.get(metric.lower())
            for a in candidate_arts:
                if not a.workspace_path:
                    continue
                p = Path(a.workspace_path)
                if not p.is_file():
                    continue
                if p.suffix.lower() in (".csv", ".tsv"):
                    obs_num = _extract_metric_from_csv(p, metric, dir_choice)
                elif p.suffix.lower() == ".json":
                    obs_num = _extract_metric_from_json(p, metric, dir_choice)
                if obs_num is None:
                    # Fallback to measuring structural length of data artifacts
                    obs_num = _measure_artifact_size(p)
                if obs_num is not None:
                    break

        if obs_num is not None and target_num is not None:
            passed = _compare_operator(obs_num, op, target_num)
            details = f"Observed {metric}={obs_num:.4g} {op} target {target_num:.4g} (passed={passed})"
            out.append(check.model_copy(update={
                "observed": obs_num,
                "passed": passed,
                "details": details,
            }))
        elif obs_num is not None:
            out.append(check.model_copy(update={
                "observed": obs_num,
                "passed": True if check.passed is True else False,
                "details": f"Observed {metric}={obs_num:.4g}",
            }))
        else:
            # Cannot measure threshold -> criterion fails
            out.append(check.model_copy(update={
                "passed": False,
                "details": f"Threshold metric {metric!r} could not be measured from artifacts",
            }))

    return out


__all__ = [
    "bind_criteria_evidence",
    "is_placeholder_value",
    "scan_placeholder_outputs",
    "verify_threshold_criteria",
]
