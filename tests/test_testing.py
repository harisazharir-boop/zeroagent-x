"""Comprehensive tests for controlled test execution and verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from zeroagent.proof.checks.test_exec import verify_test
from zeroagent.proof.engine import verify_execution
from zeroagent.testing import (
    TestEvidence,
    TestRunnerError,
    approve_test,
    execute_test,
    load_test_spec,
    make_test_spec,
    validate_test_spec,
)


def test_make_test_spec_valid(tmp_path: Path) -> None:
    spec = make_test_spec(
        tmp_path, runner="pytest", arguments=["tests/test_cli.py", "-k", "help"]
    )
    assert spec.workspace_identifier == tmp_path.name
    assert spec.runner == "pytest"
    assert spec.arguments == ["tests/test_cli.py", "-k", "help"]
    assert len(spec.digest) == 64


def test_make_test_spec_unsupported_runner(tmp_path: Path) -> None:
    with pytest.raises(TestRunnerError, match="not in allowlist"):
        make_test_spec(tmp_path, runner="bash")


def test_make_test_spec_unsafe_arguments(tmp_path: Path) -> None:
    with pytest.raises(TestRunnerError, match="unsafe shell characters"):
        make_test_spec(tmp_path, runner="pytest", arguments=["test.py; rm -rf /"])


def test_validate_test_spec_digest_mismatch(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path)
    corrupted = spec.model_copy(update={"digest": "a" * 64})
    with pytest.raises(TestRunnerError, match="digest does not match"):
        validate_test_spec(corrupted, tmp_path)


def test_validate_test_spec_workspace_mismatch(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path)
    other_path = tmp_path.parent / "other_ws"
    other_path.mkdir(exist_ok=True)
    with pytest.raises(TestRunnerError, match="[Ww]orkspace mismatch"):
        validate_test_spec(spec, other_path)


def test_approve_test_binding(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path, runner="pytest")
    approval = approve_test(spec, tmp_path)
    assert approval.specification_id == spec.specification_id
    assert approval.specification_digest == spec.digest
    assert approval.workspace_identifier == tmp_path.name


def test_execute_test_rejection_on_digest_mismatch(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path, runner="pytest")
    approval = approve_test(spec, tmp_path)
    # Corrupt approval digest
    bad_approval = approval.model_copy(update={"specification_digest": "0" * 64})
    with pytest.raises(TestRunnerError, match="Approval is not bound"):
        execute_test(spec, bad_approval, tmp_path)


def test_execute_test_rejection_on_workspace_escape(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path, runner="pytest", working_directory="../escaped")
    approval = approve_test(spec, tmp_path)
    with pytest.raises(TestRunnerError, match="resolves outside workspace"):
        execute_test(spec, approval, tmp_path)


def test_execute_test_actual_run_success(tmp_path: Path) -> None:
    # Create simple passing test
    test_file = tmp_path / "test_simple.py"
    test_file.write_text("def test_ok(): assert 1 == 1\n")
    spec = make_test_spec(tmp_path, runner="pytest", arguments=["test_simple.py"])
    approval = approve_test(spec, tmp_path)

    result = execute_test(spec, approval, tmp_path)
    assert result.status == "PASSED"
    assert result.exit_code == 0
    assert "1 passed" in result.stdout or "passed" in result.stdout
    assert result.duration_seconds >= 0.0


def test_execute_test_actual_run_failure(tmp_path: Path) -> None:
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_bad(): assert 1 == 2\n")
    spec = make_test_spec(tmp_path, runner="pytest", arguments=["test_fail.py"])
    approval = approve_test(spec, tmp_path)

    result = execute_test(spec, approval, tmp_path)
    assert result.status == "FAILED"
    assert result.exit_code != 0


def test_execute_test_timeout_handling(tmp_path: Path) -> None:
    test_file = tmp_path / "test_hang.py"
    test_file.write_text("import time\ndef test_sleep(): time.sleep(5)\n")
    spec = make_test_spec(
        tmp_path, runner="pytest", arguments=["test_hang.py"], timeout_seconds=1
    )
    approval = approve_test(spec, tmp_path)

    result = execute_test(spec, approval, tmp_path)
    assert result.status == "TIMED_OUT"
    assert "timed out" in (result.error or "")


def test_load_test_spec_safety(tmp_path: Path) -> None:
    spec = make_test_spec(tmp_path, runner="pytest")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(spec.model_dump_json())

    loaded = load_test_spec(spec_path)
    assert loaded.digest == spec.digest
    assert loaded.specification_id == spec.specification_id

    # Reject oversized spec
    big_path = tmp_path / "big_spec.json"
    big_path.write_text("x" * 1_000_001)
    with pytest.raises(TestRunnerError, match="size limit"):
        load_test_spec(big_path)


def test_proof_engine_test_verification(tmp_path: Path) -> None:
    evidence = TestEvidence(
        specification_digest="a" * 64,
        approval_bound=True,
        runner_allowlisted=True,
        execution_completed=True,
        exit_code_zero=True,
        output_integrity=True,
    )
    results = verify_test(evidence)
    status_map = {c.check_id: c.status for c in results}

    assert status_map["tests.specification_valid"] == "PASS"
    assert status_map["tests.approval_bound"] == "PASS"
    assert status_map["tests.runner_allowlisted"] == "PASS"
    assert status_map["tests.exit_code_zero"] == "PASS"
    # Semantic correctness must remain INCOMPLETE
    assert status_map["tests.semantic_correctness"] == "INCOMPLETE"

    report = verify_execution(None, evidence, tmp_path)
    assert report.artifact_type == "test_evidence"
    assert (
        report.overall_status == "INCOMPLETE"
    )  # Because semantic correctness is INCOMPLETE
