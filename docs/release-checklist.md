# Internal Release-Readiness Checklist

This checklist is internal planning aid. **Completion of this checklist does not authorize merging, tagging, publishing, or releasing.** Explicit maintainer authorization remains required for each action.

## Documentation and product claims

- [x] Candidate `0.12.0b1` README matches implemented commands, UI, security boundaries, and unpublished beta-candidate status.
- [ ] README branding assets exist, render through repository-relative links, and have meaningful alternative text.
- [x] Candidate installation instructions match Python `>=3.11`, validated Python 3.11–3.13 matrix, and unpublished distribution status.
- [ ] CLI commands, options, side effects, and exit-code descriptions checked against live help and source.
- [ ] Active Textual UI behavior checked; legacy `zeroagent.tui` support status declared.
- [ ] Security disclosures cover approval binding, stale rejection, non-atomic edits, recovery limits, proof limits, redaction limits, and unsandboxed test execution.
- [x] Changelog has unpublished `0.12.0b1` beta-candidate entry without publication date.

## Pending metadata and security UX work

- [x] Add confirmed repository and issue tracker URLs to package metadata.
- [ ] **Pending:** Confirm documentation and security URLs before adding them to package metadata.
- [ ] **Deferred:** Modernize deprecated license metadata in a dedicated release-preparation phase: require compatible `setuptools>=77.0.3`, SPDX license expression, explicit license-file declaration, license-classifier removal, and isolated wheel/sdist metadata and license-file validation.
- [x] Correct active Textual UI safe-edit wording: multi-file application is non-atomic, and recovery is explicit and best effort.
- [ ] **Pending:** Confirm dedicated private security reporting route beyond repository-owner contact.

## CI, packaging, and maintenance

### Validated engineering baseline evidence

- [x] Baseline `62d77e9d2e3cc88cee2d6685d5334d76657b1975`: CI run `40534456712` passed all 7 required Ubuntu/Windows Python 3.11–3.13 and Ubuntu packaging jobs.
- [x] Baseline test jobs passed Ruff check, Ruff format check, pytest, and CLI help, version, and doctor smoke checks.
- [x] Baseline package job built wheel and sdist, ran `scripts/verify_package.py`, and completed Ubuntu fresh-wheel entry point, CLI, TUI help, package-resource, and Pipeline-OFF smoke checks.
- [x] Baseline artifact `12748025807` metadata and bounded archive inspection verified wheel `METADATA`, sdist `PKG-INFO`, Project-URL fields, legacy license metadata consistency, and wheel `RECORD`; this is not signed build provenance or a complete security certification.
- [x] Baseline artifact checksums recorded: `zeroagent-0.12.0.dev0-py3-none-any.whl` `b2b7303ddd7074a480a9beca208cbff285b1d8551d9e21213ea593a97bc1c6be`; `zeroagent-0.12.0.dev0.tar.gz` `3e07b936843e2634daedbb58baa269ff22ce2db91a19a26cac915cf01b23f210`.
- [x] Windows Python 3.11–3.13 editable-install CI passed; Windows fresh-wheel installation and smoke validation remain unverified.
- [ ] **Implemented locally — remote validation pending:** Windows Python 3.13 fresh-wheel build, isolated install, metadata, CLI, resource, and Pipeline-OFF smoke job.

- [ ] Confirm Python/OS matrix result for release candidate: Ubuntu and Windows, Python 3.11, 3.12, 3.13.
- [ ] Run Ruff check, Ruff format check, pytest, and dependency check for release candidate.
- [ ] Build wheel and sdist; run archive scanner.
- [ ] Perform fresh wheel installation smoke, including entry point, TUI help, package resource, and Pipeline-OFF check.
- [ ] Record Windows package-install coverage limitation or add separate Windows fresh-wheel validation.
- [ ] Review version-coupled package scanner expectations in `scripts/verify_package.py` when version changes.
- [ ] **Pending:** Review GitHub Actions Node.js runtime warnings for `checkout`, `setup-python`, and `upload-artifact` under controlled maintenance task.

### 0.12.0b1 candidate evidence

- [x] Candidate version updated in package metadata, runtime version, version-coupled package scanner, tests, and Windows fresh-wheel metadata assertion.
- [x] Candidate changelog, README, installation, usage, and security-support language prepared; candidate remains unpublished.
- [ ] Record exact candidate SHA, exact-CI run, artifact ID, individual SHA-256 checksums, and artifact audit after final candidate validation.
- [ ] Complete candidate local quality, package, isolated-install, dependency, security-reporting, exact-CI, and artifact-audit gates.

## Final release gate

- [ ] Review `SECURITY.md`, `LICENSE`, package metadata, dependencies, and distribution contents.
- [ ] Review release candidate CI logs and artifacts.
- [ ] Confirm clean intended Git state and exact release commit.
- [ ] Obtain explicit maintainer approval for merge, tag, publication, and release as separate decisions.
