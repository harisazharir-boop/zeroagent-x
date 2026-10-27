# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Added controlled Pipeline lifecycle, exact artifact approval, retained reports,
  shutdown settlement, and duplicate-action safety coverage.
- Clarified Pipeline status, approval versus execution, installation, and security
  documentation. No release has been published.
- Redesigned README with approved local branding assets, CI-tested platform scope,
  architecture overview, and security-boundary summaries.
- Added CLI usage, active Textual workspace, troubleshooting, and internal
  release-readiness documentation. No release has been published.

## 0.12.0.dev0 - 2026-10-24

- Added full-screen alternate-screen buffer isolation for `zeroagent` interactive terminal mode.
- Restored 10-item menu interface with dedicated feature screens for all capabilities.
- Added bold, geometric, futuristic X logo branding with cyan/purple geometry and compact header spacing.
- Moved Local AI Chat to dedicated feature screen 09 with local model selection.
- Added controlled test execution subsystem (`zeroagent test`) with allowlisted pytest runner.
- Added exact specification digest binding for test execution.
- Added ProofEngine structural verification for test execution results.
- Added opt-in AgentBlackBox metadata recording for test execution.
- Updated Tool Registry with `tests.execute` as IMPLEMENTED.

## 0.11.0.dev0 - 2026-10-24

- Added controlled structured text patch validation, preview, approval, apply, and recovery.
- Added stale-hash detection and controlled patch/apply registry availability.

## 0.10.0.dev0 - 2026-10-24

- Added deterministic planning-only Tool Registry, plan validator, and `plan` CLI.
- Added Neon Minimal planning screen and explicit context-aware TUI AI transfer flow.

## 0.9.0.dev0 - 2026-10-24

- Added read-only Agent Workspace & Context Engine with deterministic selection,
  bounded source excerpts, hashes, sensitive-file exclusions, and explicit consent.
- Added `zeroagent context` inspect, preview, and authorized local AI ask commands.

## 0.8.0.dev0 - 2026-10-24

- Hardened BlackBox oversized-record loading, model identifier validation, and
  local provider timeout handling.
- Completed Neon Minimal local AI, history inspection, and read-only replay flows.
- Added safe terminal-text rendering for untrusted local data.

## 0.7.0.dev0 - 2026-10-24

- Added ZEROAGENT X Neon Minimal interactive dashboard as default TTY experience.
- Added raw arrow navigation, Escape back navigation, explicit command mode, and
  responsive Rich layouts.

## 0.6.0.dev0 - 2026-10-24

- Added optional loopback-only Ollama provider commands and validated local requests.
- Added local AI metadata proof boundary; generated text semantics remain incomplete.

## 0.5.0.dev0 - 2026-10-23

- Added opt-in AgentBlackBox local execution records, history, inspection, and replay.
- Added redaction, local storage limits, and historical-only replay.

## 0.4.0.dev0 - 2026-10-23

- Added ProofEngine typed reports and deterministic verification aggregation.
- Added routing, repository report, and portable evidence-path checks.
- Added `zeroagent run --verify` text and JSON proof output.

## 0.3.0.dev0 - 2026-10-23

- Added deterministic ZeroCost Router with rule-based task classification.
- Added static local capability registry and enforceable routing policy checks.
- Added `zeroagent route` and policy-gated `zeroagent run` commands.

## 0.2.0.dev0 - 2026-10-23

- Added read-only Repository Intelligence Engine.
- Added bounded discovery, `.gitignore` gitwildmatch matching, language detection,
  manifest detection, and dependency declaration parsing.
- Added `zeroagent analyze` text, JSON, and protected report export modes.

## 0.1.0 - 2026-10-23

- Created project foundation.
- Added safe typed configuration and diagnostic CLI.
- Added tests, CI, documentation, and community files.
