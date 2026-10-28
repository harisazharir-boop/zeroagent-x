# Demonstration Guide

Use disposable workspace, local test data, terminal recording, and no credentials.
Do not present simulated output as provider-backed execution. Capture actual command
output and redact any accidental personal paths before publishing.

## Demo 1 — ZEROAGENT X in 60 Seconds

**Target:** 45–90 seconds.
**Caption:** “Local-first developer automation: inspect, route, and control work from
terminal without automatic cloud or agent execution.”

### Recording script

1. Show `zeroagent --version` and `zeroagent doctor`.
2. Run `zeroagent analyze . --format json` in disposable workspace.
3. Run `zeroagent route "Analyze this repository"`.
4. Launch `zeroagent tui --workspace .` in interactive terminal; show Agent Workspace.
5. Run `zeroagent agent config` and show disabled defaults.
6. Run `zeroagent agent validate "Summarize this workspace" --workspace .`.
7. Show no agent executes without explicit policy and approval. Do not claim result
   from unavailable provider.

### Screenshot checklist

- Terminal version and safe-default diagnostics.
- Read-only analysis output with non-sensitive disposable files.
- TUI screen captured from actual terminal session.
- Agent policy configuration and request validation output.

## Demo 2 — Policy-Controlled Execution

**Target:** 60–90 seconds.
**Caption:** “Request validation is not authorization: execution needs explicit policy,
single-use approval, and available local adapter.”

### Recording script

1. Run `zeroagent agent config`.
2. Run `zeroagent agent validate "Summarize this workspace" --workspace .`.
3. Explain default policy disables execution, OpenCode, and network access.
4. Explain authorized integrations may construct explicit `Settings`; no v1.0.0 CLI
   command changes those switches.
5. If authorized provider exists, record real `approve` then `run` in disposable
   workspace. Otherwise end after validation and label demo “policy boundary only.”
6. If evidence was recorded, show `zeroagent agent history` and `agent evidence ID`.

## Demo 3 — Developer Workflow

**Target:** 60–90 seconds.
**Caption:** “Start with safe read-only repository analysis, then choose explicit,
bounded automation.”

### Commands

```bash
mkdir zeroagent-demo && cd zeroagent-demo
printf 'print("hello")\n' > app.py
zeroagent analyze . --format json
zeroagent route "Analyze this Python repository"
zeroagent run "Analyze this repository" --workspace . --verify --format json
```

`run` above invokes implemented local repository analysis, not an external agent.
Show ProofEngine result as structural evidence, never semantic proof.

## Asset specifications

Existing `docs/assets/zeroagent-x-banner.png` is genuine repository banner. New visual
assets must use actual terminal/TUI captures. No image-generation tool is available in
this repository workflow, so prepare these production specs rather than fabricated
screens:

| Asset | Specification |
|---|---|
| Social announcement | 1600×900 PNG; deep navy `#080D18`; cyan `#00E5FF`, violet `#8B5CF6`, emerald `#00E6A8`; logo, tagline, release URL; no metrics or claims beyond release facts |
| Product Hunt cover | 1270×760 PNG; same palette; real terminal/TUI screenshot inside bordered panel; title and local-first tagline |
| CLI screenshot | 1600×1000 PNG; real `doctor`, `analyze`, or policy output; redact paths/usernames; label command exactly |
| TUI screenshot | 1600×1000 PNG; actual interactive `zeroagent tui --workspace .`; no composited controls or invented states |
| Architecture diagram | SVG or 1600×900 PNG; CLI/TUI → Coordinator → explicit adapter → bounded evidence; label policy and approval gates; include “not OS sandbox” note |
