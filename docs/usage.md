# Usage and CLI Reference

Run `zeroagent --help` for command help. Commands below reflect `src/zeroagent/cli.py` in beta candidate version `0.12.0b1`.

## Command inventory

| Command | Purpose | Side effect |
|---|---|---|
| `doctor` | Local runtime and safe-default diagnostics | Read-only |
| `tui` | Launch active Textual workspace | Interactive terminal session |
| `analyze PATH` | Bounded repository metadata analysis | Read-only unless `--output` creates a new report file |
| `route TASK` | Deterministic routing decision | Read-only; never runs handler |
| `run TASK` | Run policy-permitted registered local handler | Handler-dependent; built-ins are local analysis/diagnostics |
| `history`, `inspect ID`, `replay ID` | Read stored BlackBox records | Read-only; replay never reruns work |
| `ai` | Explicit optional local Ollama commands | Local loopback request only when invoked |
| `context` | Inspect, select, or explicitly transfer bounded context | `ask` sends approved excerpts to local Ollama |
| `plan` | List, create, validate deterministic plans | No tool execution |
| `edit` | Validate, preview, propose, apply, recover structured patches | `apply` and `recover` change workspace files |
| `test` | Create, validate, preview, run controlled test specs | `run` executes approved `pytest` |

## Workspace behavior

Workspace commands require existing directory paths. ZEROAGENT X resolves selected workspace explicitly and does not choose implicit fallback workspace. Repository analysis skips child symlinks; safe edit and controlled-test operations additionally enforce their own containment rules.

## Analysis, route, run, and proof

```bash
zeroagent analyze .
zeroagent analyze . --format json
zeroagent analyze . --output report.json

zeroagent route "Analyze this repository"
zeroagent run "Analyze this repository" --workspace .
zeroagent run "Analyze this repository" --workspace . --verify --format json
```

`route` returns decision evidence and never invokes a capability. `run` executes only selected registered local handler after policy checks. `run --verify` verifies actual result with available structural checks.

Proof status:

- `VERIFIED`: implemented required structural checks passed.
- `FAILED`: a required structural check failed.
- `INCOMPLETE`: required checks are unavailable or incomplete.

Proof does not prove semantic correctness, source safety, complete inventory, cryptographic integrity, or absence of vulnerabilities.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Command completed successfully; proof may be absent unless requested |
| `1` | Controlled test completed with non-passing result |
| `2` | Validation, usage, policy, workspace, provider, or command failure |
| `3` | `run --verify` produced `FAILED` proof |
| `4` | `run --verify` produced `INCOMPLETE` proof |

Typer may also use standard nonzero parsing/usage exits. Treat command output and documented command-specific behavior as source of truth.

## Planning and context

```bash
zeroagent plan tools
zeroagent plan create "Explain this project" --workspace .
zeroagent context inspect --workspace .
zeroagent context preview "Explain this project" --workspace .
zeroagent context ask "Explain this project" --workspace . --model <installed-model> --allow-context
```

Plans are deterministic and non-executing. Context preview selects paths without reading source text. `context ask` needs `--allow-context` before bounded selected excerpts are read and sent to explicitly selected local Ollama model.

## Safe editing

Safe editing accepts structured text-only proposal JSON. It supports `modify` and `create`, limits file and content sizes, rejects unsafe paths, validates hashes, and records recovery outside workspace.

```bash
zeroagent edit validate proposal.json --workspace .
zeroagent edit preview proposal.json --workspace .
zeroagent edit apply proposal.json --workspace . \
  --approve-digest <digest-shown-by-preview> \
  --recovery-dir /safe/path/outside/workspace
zeroagent edit recover /safe/path/outside/workspace/recovery-id --workspace .
```

`validate` and `preview` do not change files. `apply` requires exact current proposal digest, workspace binding, and byte-exact current source SHA-256 values. A stale file rejects application. Multi-file application is not atomic: a failure can leave partial changes and retained recovery data. Recovery is explicit, best effort, and refuses files changed after application.

`edit propose TASK --workspace PATH --model MODEL --allow-context` requests untrusted structured JSON from selected local model; it does not write repository files.

## Controlled pytest execution

Only `pytest` is allowlisted. Test execution uses direct argument-array subprocess invocation, not shell-string evaluation.

```bash
zeroagent test runners
zeroagent test create --workspace . --runner pytest --args "-q"
zeroagent test validate test-spec.json --workspace .
zeroagent test preview test-spec.json --workspace .
zeroagent test run test-spec.json --workspace . --approve-digest <digest-shown-by-preview>
```

Create command emits a specification; save JSON output yourself when using `--format json`. Exact specification digest approval is mandatory for `run`. Pytest executes workspace code and is not OS-sandboxed; approve only trusted workspaces.

## AgentBlackBox

Add `--record` to supported `run`, `edit apply`, or `test run` commands to persist sanitized local metadata. `--storage-dir PATH` overrides default storage.

```bash
zeroagent run "Analyze this repository" --workspace . --record
zeroagent history
zeroagent inspect <execution-id>
zeroagent replay <execution-id>
```

Default record storage is outside analyzed workspace: `$XDG_DATA_HOME/zeroagent/blackbox` or `~/.local/share/zeroagent/blackbox` on Linux, `%LOCALAPPDATA%/ZEROAGENT X/blackbox` on Windows. Default limits are 100 records, 1 MB each, and 30 days. Redaction is best effort; storage is not tamper-proof.

## Optional Ollama

```bash
zeroagent ai doctor
zeroagent ai models
zeroagent ai ask "Explain dependency injection" --model <installed-model>
```

AI commands explicitly contact manually installed local Ollama. Endpoint validation permits only loopback HTTP on port `11434`; proxies and redirects are disabled. No cloud, paid-provider, or model-download fallback exists.
