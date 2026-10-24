# Development

## Environment

Use Python 3.11 or newer. Create virtual environment outside global Python
packages.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

On Windows, invoke `.venv\Scripts\python.exe` when `python` is not activated.

## Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
zeroagent --help
zeroagent --version
zeroagent doctor
zeroagent analyze . --format json
zeroagent route "Analyze this repository" --format json
zeroagent run "Analyze this repository" --workspace .
zeroagent run "Analyze this repository" --workspace . --verify --format json
zeroagent run "Analyze this repository" --workspace . --verify --record
zeroagent history
zeroagent ai --help
zeroagent context preview "Explain this project" --workspace .
zeroagent plan create "Explain this project" --workspace .
zeroagent edit --help
zeroagent tui --workspace .
zeroagent

# In the TUI: /model, type a prompt, /clear, /back
python -m zeroagent --help
```

## Design rules

- Keep dependency set small and local-first.
- Add type annotations to runtime code.
- Keep network, provider, shell, and destructive actions opt-in.
- Add tests for every new behavior.
- Document current behavior separately from planned behavior.
