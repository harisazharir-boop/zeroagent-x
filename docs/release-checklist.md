# Internal Release-Readiness Checklist

This checklist is internal planning aid. **Completion of this checklist does not authorize merging, tagging, publishing, or releasing.** Explicit maintainer authorization remains required for each action.

## Documentation and product claims

- [ ] README matches implemented commands, UI, security boundaries, version, and preview/release status.
- [ ] README branding assets exist, render through repository-relative links, and have meaningful alternative text.
- [ ] Installation instructions match supported Python and tested OS/version matrix.
- [ ] CLI commands, options, side effects, and exit-code descriptions checked against live help and source.
- [ ] Active Textual UI behavior checked; legacy `zeroagent.tui` support status declared.
- [ ] Security disclosures cover approval binding, stale rejection, non-atomic edits, recovery limits, proof limits, redaction limits, and unsandboxed test execution.
- [ ] Changelog reviewed; no release entry or version claim is premature.

## Pending metadata and security UX work

- [ ] **Pending:** Add confirmed repository, documentation, issue tracker, and security URLs to package metadata.
- [ ] **Pending:** Modernize deprecated license metadata after packaging-toolchain compatibility review.
- [ ] **Pending:** Correct active Textual UI phrase claiming “atomic rollback”; implementation uses non-atomic multi-file apply with best-effort recovery.
- [ ] **Pending:** Confirm dedicated private security reporting route beyond repository-owner contact.

## CI, packaging, and maintenance

- [ ] Confirm Python/OS matrix result for release candidate: Ubuntu and Windows, Python 3.11, 3.12, 3.13.
- [ ] Run Ruff check, Ruff format check, pytest, and dependency check for release candidate.
- [ ] Build wheel and sdist; run archive scanner.
- [ ] Perform fresh wheel installation smoke, including entry point, TUI help, package resource, and Pipeline-OFF check.
- [ ] Record Windows package-install coverage limitation or add separate Windows fresh-wheel validation.
- [ ] Review version-coupled package scanner expectations in `scripts/verify_package.py` when version changes.
- [ ] **Pending:** Review GitHub Actions Node.js runtime warnings for `checkout`, `setup-python`, and `upload-artifact` under controlled maintenance task.

## Final release gate

- [ ] Review `SECURITY.md`, `LICENSE`, package metadata, dependencies, and distribution contents.
- [ ] Review release candidate CI logs and artifacts.
- [ ] Confirm clean intended Git state and exact release commit.
- [ ] Obtain explicit maintainer approval for merge, tag, publication, and release as separate decisions.
