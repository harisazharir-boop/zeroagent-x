"""Consistency checks for Repository Intelligence reports."""

from collections import Counter

from zeroagent.core.repository import AnalysisReport
from zeroagent.proof.checks.evidence import verify_evidence_paths
from zeroagent.proof.models import CheckResult


def verify_repository_report(report: AnalysisReport) -> list[CheckResult]:
    """Check report consistency. This does not prove inventory exhaustiveness."""
    schema = CheckResult(
        check_id="repository.schema",
        status="PASS" if report.schema_version == "1.0" else "FAIL",
        required=True,
        reason=(
            "Supported repository report schema"
            if report.schema_version == "1.0"
            else "Unsupported repository report schema"
        ),
    )
    counts_valid = report.file_count >= 0 and report.directory_count >= 0
    total_languages = sum(item.file_count for item in report.languages)
    percentages_valid = all(
        item.file_count >= 0
        and item.percentage
        == (
            round(item.file_count / report.file_count * 100, 2)
            if report.file_count
            else 0.0
        )
        for item in report.languages
    )
    statistics = CheckResult(
        check_id="repository.statistics",
        status="PASS"
        if counts_valid and total_languages == report.file_count and percentages_valid
        else "FAIL",
        required=True,
        reason=(
            "Counts and file-count language percentages are consistent"
            if counts_valid
            and total_languages == report.file_count
            and percentages_valid
            else "Counts or file-count language percentages are inconsistent"
        ),
    )
    manifest_paths = {
        item.evidence.get("file")
        for item in report.evidence
        if item.finding_type == "project_manifest"
    }
    manifests_valid = all(manifest in manifest_paths for manifest in report.manifests)
    manifests = CheckResult(
        check_id="repository.manifests",
        status="PASS" if manifests_valid else "FAIL",
        required=True,
        reason=(
            "Every manifest has project-manifest evidence"
            if manifests_valid
            else "Manifest lacks project-manifest evidence"
        ),
    )
    language_evidence = Counter(
        item.evidence.get("file")
        for item in report.evidence
        if item.finding_type == "language_detection"
    )
    inventory = CheckResult(
        check_id="repository.inventory_evidence",
        status="PASS"
        if sum(language_evidence.values()) == report.file_count
        else "FAIL",
        required=True,
        reason=(
            "Language evidence count matches reported file count"
            if sum(language_evidence.values()) == report.file_count
            else "Language evidence count does not match reported file count"
        ),
    )
    completeness = CheckResult(
        check_id="repository.completeness",
        status="PASS" if report.complete else "INCOMPLETE",
        required=True,
        reason=(
            "Report declares complete analysis"
            if report.complete
            else "Report declares incomplete analysis; exhaustive inventory is unproven"
        ),
    )
    return [
        schema,
        statistics,
        manifests,
        verify_evidence_paths(report.evidence),
        inventory,
        completeness,
    ]
