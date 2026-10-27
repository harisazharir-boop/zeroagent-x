# Textual Workspace Guide

ZEROAGENT X active terminal UI is `ZeroAgentApp` in `src/zeroagent/textual_app.py`. It is launched by CLI; legacy `src/zeroagent/tui.py` is not default CLI-launched interface.

## Launch

```bash
zeroagent
zeroagent tui --workspace .
zeroagent tui --workspace . --debug
zeroagent tui --workspace . --no-logo
```

TUI requires interactive stdin and stdout. Bare `zeroagent` opens workspace only in interactive terminal; otherwise it prints CLI help. `zeroagent tui` rejects noninteractive invocation with exit code `2`.

## Navigation

- Arrow keys and **Enter** select menu items.
- **Escape** returns to prior/home screen where available.
- **/** opens command palette or feature navigation.
- **q** or **Ctrl+C** exits.
- **Tab** changes focus in feature workbenches.

Terminal size, graphics protocol, and emulator behavior can affect rendering. `--no-logo` disables inline graphics-logo rendering.

## Screens

| Screen | Implemented purpose |
|---|---|
| Agent Workspace | Explicit Task → Route → Run → Verify flow for supported local tasks |
| Analyze Repository | Bounded repository structure and metadata analysis |
| Ask About Repository | Deterministic context selection; local-model transfer needs authorization |
| Safe Code Editing | Proposal review, diff, exact-digest approval, guarded apply |
| Run Controlled Tests | Approval-bound allowlisted pytest specification workflow |
| Verify Execution | ProofEngine structural evidence display |
| Execution History | Opt-in AgentBlackBox records |
| Historical Replay | Stored historical events only; no rerun |
| Local AI Chat | Optional manually configured local Ollama interaction |
| Settings | Current safe-default policies and diagnostics |
| Help | In-app guidance |
| Pipeline | Guarded plan/analyze/edit/test lifecycle |

## Agent Workspace

Agent Workspace keeps operations distinct:

1. **Route Task** selects a supported registered local capability and policy decision without execution.
2. **Run Agent** is separate explicit execution. Task or workspace changes invalidate prior route.
3. **Verify Results** invokes available ProofEngine checks against actual result evidence.

Unknown tasks and arbitrary shell commands cannot bypass policy. Some result types have no structural proof checks and correctly produce `INCOMPLETE`.

## Safe editing and controlled tests

Safe editing requires loaded structured proposal, preview, and exact digest approval before apply. It rechecks workspace containment and current file hashes. Multi-file application is not atomic. A failure can leave partial changes; recovery is explicit, outside workspace, and best effort.

Controlled tests use an allowlisted `pytest` specification. Preview shows exact command and digest. Approval does not execute tests; running is separate explicit action. Tests execute workspace code and are not OS-sandboxed.

## Pipeline

Pipeline begins `OFF`. **Start Pipeline** performs plan and repository analysis, then pauses for proposal review. Approval and execution remain separate:

1. Submit proposal and inspect diff.
2. Approve exact proposal digest.
3. Apply approved edit.
4. Submit and approve test specification.
5. Run approved test.
6. Review structural evidence report.

Pipeline tracks owned Apply and Test work. Cancellation or normal shutdown waits for active owned operation to settle before final state. It cannot protect against forced termination, power loss, or semantic defects.

## Local AI and history

Ollama use is optional. It must be manually installed, running locally, and have selected installed model. Local model output is untrusted. Repository-context transfer requires explicit authorization and excludes sensitive names, symlinks, binary data, oversized files, and unsupported types.

AgentBlackBox records are opt-in. History and replay are read-only; replay never invokes handlers. Redaction reduces common secret exposure but is not a guarantee.

See [usage reference](usage.md), [troubleshooting](troubleshooting.md), and [security policy](../SECURITY.md).
