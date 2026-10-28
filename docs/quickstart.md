# Five-Minute Quick Start

ZEROAGENT X is local-first developer automation. Safe defaults keep telemetry,
cloud providers, paid APIs, network access, shell-command execution, and external
agent execution disabled.

## Prerequisites

- Python 3.11, 3.12, or 3.13.
- Interactive terminal only for Textual TUI.
- Optional: manually installed Ollama for local AI commands.
- Optional: explicitly configured OpenCode executable for governed external-agent
  execution. It is disabled by default.

## Install verified v1.0.0 wheel

Open [release v1.0.0](https://github.com/harisazharir-boop/zeroagent-x/releases/tag/v1.0.0).
Download `zeroagent-1.0.0-py3-none-any.whl` and `SHA256SUMS` into same directory.

```bash
sha256sum -c SHA256SUMS
python -m pip install zeroagent-1.0.0-py3-none-any.whl
zeroagent --version
```

Expected version:

```text
1.0.0
```

PyPI is not used. Windows PowerShell does not include `sha256sum`; use
`Get-FileHash zeroagent-1.0.0-py3-none-any.whl -Algorithm SHA256` and compare it
with `SHA256SUMS` before `python -m pip install`.

## First safe command

Run diagnostics, then analyze current workspace:

```bash
zeroagent doctor
zeroagent analyze . --format json
zeroagent route "Analyze this repository"
```

`doctor` reads local runtime details. `analyze` reads bounded workspace metadata and
supported manifest text. `route` produces decision evidence only. None starts an
external agent, runs shell commands, sends repository content, or contacts providers.

## Launch Textual workspace

Run in interactive terminal:

```bash
zeroagent tui --workspace .
```

Bare `zeroagent` also opens TUI in interactive terminal. In noninteractive contexts,
use CLI commands; `zeroagent tui` exits with code `2`.

## Optional local AI

Install and start Ollama separately, then inspect local availability:

```bash
zeroagent ai doctor
zeroagent ai models
```

Only explicit `ai` commands contact Ollama. Endpoint must be loopback HTTP on port
`11434`; no cloud, paid-provider, or model-download fallback exists.

## Governed OpenCode execution

Inspect state first:

```bash
zeroagent agent adapters
zeroagent agent config
zeroagent agent validate "Summarize this workspace" --workspace .
```

`agent config` reports safe defaults. With shipped defaults, OpenCode execution is
rejected because application policy requires explicit enablement of agent execution,
OpenCode, and network access. ZEROAGENT X v1.0.0 has no user-facing CLI or config-file
workflow for changing those settings; do not bypass application controls. Textual Agent
Control Center also cannot bypass policy. An application integration may supply an
explicit `Settings` object only after reviewing [security boundaries](../SECURITY.md).

When an authorized integration enables policy and a local OpenCode executable exists,
workflow stays request-bound:

```bash
zeroagent agent approve "Summarize this workspace" --workspace . --record
zeroagent agent run "Summarize this workspace" --workspace . --record \
  --approval-token <single-use-token-from-approve>
```

Approval is interactive. Token is opaque, local, valid for five minutes, bound to one
request and policy state, and consumed once. External agents are not OS-sandboxed;
network policy is not physical network isolation. Use disposable trusted workspace.

## Troubleshooting

- `zeroagent` not found: invoke installed environment directly or use
  `python -m zeroagent --help`.
- TUI rejected: use interactive terminal.
- OpenCode unavailable or denied: inspect `zeroagent agent adapters` and
  `zeroagent agent config`; defaults are intentionally disabled.
- More help: [troubleshooting](troubleshooting.md), [CLI reference](usage.md), and
  [security policy](../SECURITY.md).
