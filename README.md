# ZEROAGENT X

**Local-First. Proof-Driven. Zero Paid API Required.**

ZEROAGENT X is an open-source Python framework for developer-task agents. Its
default engine runs locally, makes no network requests, enables no paid API
providers, and records no telemetry. Future releases will add opt-in local model
providers, task routing, tool execution, proof verification, and history.

## Status

Development stage. Version `0.9.0.dev0` supplies repository intelligence plus
packaging, safe typed configuration, diagnostics, tests, and contributor tooling.
It is not production-ready and does not execute agent tasks.

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
- Neon Minimal interactive terminal dashboard via `zeroagent tui`.
- Safe configuration defaults: no telemetry, network access, paid providers,
  cloud providers, or shell execution.
- Linux and Windows compatible Python code.

## Planned

- Deterministic, authorized tool execution.
- Future optional local language-model routing.
- Evidence-based result verification.
- Reproducible execution history.

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

`zeroagent tui` needs interactive stdin/stdout. It uses existing local services;
recording remains opt-in and normal JSON CLI commands remain machine-readable.
Run bare `zeroagent` in interactive terminal to launch dashboard; noninteractive
invocation displays normal CLI help.

TUI Local AI uses explicit installed-model selection and repeated single-turn
prompts. It never sends prior prompts, repository contents, or shell tools. TUI
history can inspect records and historical replay remains read-only.

Repository-aware AI requires explicit `--allow-context`. Sensitive filenames,
symlinks, binary data, oversized files, and unsupported types are excluded. Source
excerpts are bounded, hashed, and cited as supplied evidence; model explanations
remain unverified interpretations.

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
