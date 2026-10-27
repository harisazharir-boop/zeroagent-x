# Installation

ZEROAGENT X is an unpublished development preview. Install from source checkout; no PyPI installation path is documented.

## Requirements and validated scope

- Python `>=3.11` is required by `pyproject.toml`.
- CI validated Ubuntu and Windows on Python 3.11, 3.12, and 3.13 for commit `574491be49d36dc45aa75c6ec0a600f233fac6de` in [run `40539452222`](https://github.com/harisazharir-boop/zeroagent-x/actions/runs/40539452222).
- Fresh wheel installation smoke ran on Ubuntu Python 3.13 only.
- Python 3.14 and Windows fresh-wheel installation are not part of validated release matrix.

## Ubuntu / Linux source setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/zeroagent --version
.venv/bin/zeroagent doctor
.venv/bin/zeroagent --help
```

Activate virtual environment if desired:

```bash
source .venv/bin/activate
zeroagent doctor
```

## Windows PowerShell source setup

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\zeroagent.exe --version
.venv\Scripts\zeroagent.exe doctor
.venv\Scripts\zeroagent.exe --help
```

Activate virtual environment if desired:

```powershell
.\.venv\Scripts\Activate.ps1
zeroagent doctor
```

If PowerShell execution policy blocks activation, run commands through `.venv\Scripts\python.exe` or `.venv\Scripts\zeroagent.exe`; do not weaken project security controls.

## Verify and launch

```bash
zeroagent --help
zeroagent --version
zeroagent doctor
python -m zeroagent --help
zeroagent tui --help
```

`python -m zeroagent --help` is fallback when shell cannot find `zeroagent`. Full-screen TUI requires interactive stdin and stdout:

```bash
zeroagent tui --workspace .
```

Bare `zeroagent` opens Textual workspace in interactive terminal; noninteractive bare use shows CLI help. Explicit `zeroagent tui` rejects noninteractive invocation with exit code `2`.

## Optional local AI

Install Ollama separately using official instructions, start local service, and obtain a model manually. ZEROAGENT X does not install Ollama, download models, contact cloud providers, or use paid fallback.

```bash
zeroagent ai doctor
zeroagent ai models
zeroagent ai ask "Explain dependency injection" --model <installed-model>
```

Only loopback Ollama endpoints are accepted: `127.0.0.1` or `::1`, plain HTTP, port `11434`. Local AI output is untrusted.

## Next steps

- [Usage and CLI reference](usage.md)
- [Textual workspace guide](tui.md)
- [Troubleshooting](troubleshooting.md)
- [Security policy](../SECURITY.md)
