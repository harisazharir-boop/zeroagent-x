# Installation

ZEROAGENT X supports Python 3.11 or newer on Linux and Windows.

## Install from source

Obtain a project source checkout, then run:

```bash
python -m venv .venv
```

Linux:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Verify

```bash
zeroagent --version
zeroagent doctor
zeroagent analyze .
zeroagent tui --help
```

Installation does not require API keys, cloud authentication, or paid API
accounts. Default configuration does not make network requests.

## Optional local AI

Install Ollama separately using its official instructions, start its local service,
and obtain a model manually. ZEROAGENT X does not install Ollama or download models.
Then query only an installed model:

```bash
zeroagent ai doctor
zeroagent ai models
zeroagent ai ask "Explain dependency injection" --model <installed-model>
```

TUI local AI also requires a reachable manually started Ollama service and an
installed model. It does not store raw prompts or responses by default.

## Repository context

Repository-aware local AI is explicit and read-only. Preview selected source paths:

```bash
zeroagent context preview "Explain this project" --workspace .
```

Authorize bounded source reads and local transfer only when intended:

```bash
zeroagent context ask "Explain this project" --workspace . --model <installed-model> --allow-context
```

## Planning

Create read-only plans without running anything:

```bash
zeroagent plan tools
zeroagent plan create "Find and fix a bug" --workspace .
```

## Controlled edits

Use trusted structured proposals with `zeroagent edit validate`, `preview`, and
exact-digest `apply`. This feature never invokes shell commands or test runners.

## Controlled tests

Create and preview allowlisted test specifications with `zeroagent test create` and
`zeroagent test preview`, then execute only with exact-digest approval via `zeroagent test run`.

## Textual workspace and Pipeline

Interactive `zeroagent` launches the Textual full-screen application. In a
noninteractive environment it prints CLI help; `zeroagent tui` rejects
noninteractive invocation. Use `zeroagent tui --workspace .` to select a workspace.

Home creates non-executing plans. Open **Agent Workspace** through command palette
or `/agent` for `Task → Route → Run → Verify`. Route selects existing permitted local
capability without running it. Run is explicit and rechecks current task/workspace.
Verify uses ProofEngine on actual result evidence; unsupported result types report
`INCOMPLETE`, not `VERIFIED`. Task text is never interpreted as shell command. Unknown
tasks remain denied. Ollama is optional; cloud services are not required.

Pipeline is OFF until **Start Pipeline**. Proposal preview is read-only. Approval
requires exact current digest and does not execute anything. **Apply Approved Edit**
changes files only after approval. **Run Approved Test** starts only approved,
allowlisted pytest. Stop waits for active work to settle. Apply failures can leave
partial changes; automatic rollback is not guaranteed.

Windows instructions are documentation-reviewed only; runtime validation for this
phase ran on Ubuntu Linux.
