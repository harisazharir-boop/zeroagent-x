# ZEROAGENT X

**Don't Just Run AI. Prove It Works.**

ZEROAGENT X is an open-source, local-first developer workflow tool. It provides
read-only planning and analysis, explicit controlled edit and test workflows,
local evidence checks, and a Textual workspace. Defaults disable telemetry,
cloud providers, paid APIs, and network access.

## Status

Development preview. Version `0.12.0.dev0` includes guarded local execution,
but is not a published release or a guarantee of semantic code correctness.

## Available now

- Python package and `zeroagent` CLI.
- `doctor` command with real local runtime diagnostics.
- Read-only deterministic repository analysis with `zeroagent analyze`.
- Language file-count distribution, ecosystem manifests, and dependency metadata.
- JSON reports with relative-path evidence and structured warnings.
- ZeroCost Router for deterministic local capability selection and execution.
- ProofEngine verification for routing and repository-analysis artifacts.
- AgentBlackBox opt-in local execution history and historical replay.
- Optional loopback-only Ollama commands for explicit local text generation.
- Simple Graphite Textual workspace (`zeroagent` in an interactive terminal, or
  `zeroagent tui --workspace .`) with planning and controlled Pipeline workflow.
- Controlled pytest execution with exact digest approval (`zeroagent test`).
- Safe code editing with unified diffs and recovery backups (`zeroagent edit`).
- Safe configuration defaults: no telemetry, network access, paid providers,
  cloud providers, or shell execution.
- Linux and Windows compatible Python code.

## Pipeline workflow

Pipeline is OFF until **Start Pipeline**. It plans and analyzes, then pauses for
explicit input. Load a proposal JSON and inspect its workspace, ID, digest, and
exact diff. **Approve Edit** records approval only; **Apply Approved Edit** is a
separate file-changing action. Create and inspect a controlled test specification
the same way. **Approve Test** does not run it; **Run Approved Test** starts only
the allowlisted runner. Stop waits for active Apply or Test work to settle safely.

Reports retain stage evidence and can be `VERIFIED`, `FAILED`, or `INCOMPLETE`.
Structural verification does not prove resulting code is logically correct. An
Apply failure may have changed files; automatic rollback is not guaranteed.

## Installation

Requires Python 3.11 or newer.

For a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Usage

```bash
zeroagent --help
zeroagent --version
zeroagent doctor
zeroagent analyze .
zeroagent analyze . --format json
zeroagent analyze . --output report.json
zeroagent route "Analyze this repository"
zeroagent route "Analyze this repository" --format json
zeroagent run "Analyze this repository" --workspace .
zeroagent run "Analyze this repository" --workspace . --verify
zeroagent run "Analyze this repository" --workspace . --verify --format json
zeroagent run "Analyze this repository" --workspace . --verify --record
zeroagent history
zeroagent ai doctor
zeroagent ai models
zeroagent ai ask "Explain dependency injection" --model <installed-model>
zeroagent tui --workspace .
zeroagent context inspect --workspace .
zeroagent context preview "Explain this project" --workspace .
zeroagent context ask "Explain authentication" --workspace . --model <installed-model> --allow-context
zeroagent plan tools
zeroagent plan create "Find and fix the authentication bug" --workspace .
zeroagent edit --help
zeroagent test --help
python -m zeroagent --help
```

`analyze` does not execute repository code, install dependencies, or use network
services. See [architecture](docs/architecture.md) for report schema, limits, and
ignore behavior.

`route` only returns deterministic decision evidence; it never executes a
capability. `run` executes only registered, policy-permitted local handlers.
Zero paid API requirement does not mean zero hardware, electricity, or local
compute cost.

`--verify` checks routing-policy consistency and repository report consistency.
It returns `VERIFIED`, `FAILED`, or `INCOMPLETE`; it does not prove source safety,
complete filesystem inventory, cryptographic integrity, or absence of vulnerabilities.

`--record` is explicit opt-in. It stores a sanitized local event record outside
analyzed repository by default. `replay` displays stored history only; it never reruns capability.

Local AI is optional. Install Ollama and obtain model manually, then use explicit
`ai` commands. ZEROAGENT X never installs Ollama, downloads models, uses cloud
fallback, or requires paid APIs. Local models need local hardware and electricity.
Generated text is untrusted and not semantically verified.

`zeroagent` in an interactive terminal, or `zeroagent tui --workspace .`, enters the full-screen
Simple Graphite workspace with Home planning, slash-command feature navigation,
and dedicated feature pages. Noninteractive `zeroagent` displays CLI help; the
explicit `tui` command rejects noninteractive invocation.

Controlled test execution via `zeroagent test` supports an allowlisted pytest runner
with exact digest approval and process isolation boundaries. Test results are
structurally verified by ProofEngine while marking semantic correctness as incomplete.

Repository-aware AI requires explicit `--allow-context`. Sensitive filenames,
symlinks, binary data, oversized files, and unsupported types are excluded. Source
excerpts are bounded, hashed, and cited as supplied evidence; model explanations
remain unverified interpretations.

Plans are deterministic and planning-only. They declare tools, dependencies,
permissions, and unsupported future work. They never execute handlers, edit files,
run tests, or grant authorization.

### Agent Workspace

Open **Agent Workspace** from command palette or enter `/agent`. It provides explicit
`Task → Route → Run → Verify` flow. **Route Task** selects registered local capability
and applies policy without execution. **Run Agent** is separate explicit action; task
or workspace changes invalidate prior route. **Verify Results** runs existing
ProofEngine over actual execution evidence. Arbitrary shell commands and unknown tasks
cannot bypass policy. Some capability result types have no structural proof checks and
correctly report `INCOMPLETE`. Pipeline editing and controlled testing remain separate
exact-approval workflows. Ollama stays optional; no cloud service is required.

Safe editing accepts structured text-only proposals. Validate and preview are
read-only. Apply needs exact proposal-digest approval, detects stale hashes, and
stores explicit recovery data outside workspace. No shell commands or tests run.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Read [development guide](docs/development.md) before contributing. See
[CONTRIBUTING.md](CONTRIBUTING.md) for contribution process and
[SECURITY.md](SECURITY.md) for security reporting and project boundaries.

## License

Licensed under [Apache License 2.0](LICENSE).
