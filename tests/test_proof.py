"""Tests for deterministic ProofEngine verification."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from zeroagent.config import Settings
from zeroagent.core.repository import AnalysisReport, Evidence, LanguageStat
from zeroagent.proof.engine import default_verification_registry, verify_execution
from zeroagent.proof.models import CheckResult, EvidenceReference, aggregate_status
from zeroagent.proof.registry import VerificationCheck, VerificationRegistry
from zeroagent.routing.router import default_registry, run_task


def _report(**updates: object) -> AnalysisReport:
    values: dict[str, object] = {
        "tool_version": "0.4.0.dev0",
        "analysis_timestamp": "2026-10-23T00:00:00Z",
        "workspace_identifier": "fixture",
        "file_count": 1,
        "directory_count": 0,
        "languages": [LanguageStat(language="Python", file_count=1, percentage=100.0)],
        "ecosystems": ["python"],
        "manifests": ["pyproject.toml"],
        "dependencies": [],
        "evidence": [
            Evidence(
                finding_type="language_detection",
                evidence={"file": "module.py", "detector": "extension_detection"},
            ),
            Evidence(
                finding_type="project_manifest",
                ecosystem="python",
                evidence={"file": "pyproject.toml", "detector": "manifest_detection"},
            ),
        ],
        "warnings": [],
        "complete": True,
    }
    values.update(updates)
    return AnalysisReport.model_validate(values)


def _executed_decision(tmp_path: Path):
    (tmp_path / "module.py").write_text("pass\n")
    return run_task("Analyze this repository", tmp_path)


def test_models_reject_invalid_status_and_serialize() -> None:
    with pytest.raises(ValidationError):
        CheckResult(check_id="test", status="MAYBE", required=True, reason="bad")
    reference = EvidenceReference(reference_type="file", path="src/module.py")
    assert reference.model_dump_json().startswith('{"reference_type"')


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        (
            [CheckResult(check_id="a", status="PASS", required=True, reason="ok")],
            "VERIFIED",
        ),
        (
            [CheckResult(check_id="a", status="FAIL", required=True, reason="bad")],
            "FAILED",
        ),
        (
            [
                CheckResult(
                    check_id="a", status="INCOMPLETE", required=True, reason="missing"
                )
            ],
            "INCOMPLETE",
        ),
        (
            [
                CheckResult(
                    check_id="a", status="NOT_APPLICABLE", required=True, reason="skip"
                )
            ],
            "INCOMPLETE",
        ),
        (
            [
                CheckResult(
                    check_id="a", status="FAIL", required=False, reason="optional"
                )
            ],
            "INCOMPLETE",
        ),
    ],
)
def test_aggregation_rules(checks: list[CheckResult], expected: str) -> None:
    assert aggregate_status(checks) == expected


def test_registry_rejects_duplicate_and_unknown_check() -> None:
    check = VerificationCheck("test", frozenset({"artifact"}), lambda: None)
    registry = VerificationRegistry([check])
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(check)
    with pytest.raises(KeyError, match="Unknown"):
        registry.get("missing")


def test_default_verification_registry_ordering() -> None:
    assert [
        check.identifier
        for check in default_verification_registry().for_artifact("repository_report")
    ] == ["repository.report", "routing.decision"]


def test_valid_executed_repository_report_verifies(tmp_path: Path) -> None:
    decision, result = _executed_decision(tmp_path)
    proof = verify_execution(decision, result, tmp_path)
    assert proof.overall_status == "VERIFIED"
    assert all(check.status == "PASS" for check in proof.checks)


def test_corrupted_repository_statistics_fail(tmp_path: Path) -> None:
    decision, _ = _executed_decision(tmp_path)
    report = _report(file_count=2)
    proof = verify_execution(decision, report, tmp_path)
    assert proof.overall_status == "FAILED"
    assert (
        next(
            check for check in proof.checks if check.check_id == "repository.statistics"
        ).status
        == "FAIL"
    )


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "C:\\Windows\\System32", "../secret", "src/../../secret"]
)
def test_invalid_evidence_paths_fail(tmp_path: Path, path: str) -> None:
    decision, _ = _executed_decision(tmp_path)
    report = _report(
        evidence=[
            Evidence(
                finding_type="language_detection",
                evidence={"file": path, "detector": "extension_detection"},
            )
        ],
        manifests=[],
    )
    proof = verify_execution(decision, report, tmp_path)
    assert proof.overall_status == "FAILED"


def test_missing_evidence_is_incomplete_not_verified(tmp_path: Path) -> None:
    decision, _ = _executed_decision(tmp_path)
    report = _report(evidence=[], manifests=[])
    proof = verify_execution(decision, report, tmp_path)
    assert proof.overall_status in {"FAILED", "INCOMPLETE"}
    assert proof.overall_status != "VERIFIED"


def test_routing_mismatch_and_denied_execution_fail(tmp_path: Path) -> None:
    decision, result = _executed_decision(tmp_path)
    unknown = decision.model_copy(update={"selected_capability": "not_registered"})
    denied = decision.model_copy(
        update={
            "decision": "denied",
            "selected_capability": None,
            "execution_performed": True,
        }
    )
    assert verify_execution(unknown, result, tmp_path).overall_status == "FAILED"
    assert verify_execution(denied, result, tmp_path).overall_status == "FAILED"


def test_policy_mismatch_fails(tmp_path: Path) -> None:
    decision, result = _executed_decision(tmp_path)
    registry = default_registry()
    capability = registry.for_category("repository_analysis")[0]
    blocked = capability.__class__(**{**capability.__dict__, "requires_network": True})
    proof = verify_execution(
        decision,
        result,
        tmp_path,
        settings=Settings(),
        registry=type(registry)([blocked]),
    )
    assert proof.overall_status == "FAILED"


def test_unsupported_artifact_is_incomplete(tmp_path: Path) -> None:
    decision, _ = _executed_decision(tmp_path)
    proof = verify_execution(decision, {"unverified": "artifact"}, tmp_path)
    assert proof.overall_status == "INCOMPLETE"
