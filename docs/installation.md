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
