# Development

## Supported and validated matrix

Package metadata requires Python 3.11 or newer. CI validates Python 3.11, 3.12, and 3.13 on Ubuntu and Windows. Latest validated commit `5e12ea4` passed all six test jobs with `322` tests each. Ubuntu Python 3.13 package job also passed wheel/sdist build, archive scan, clean wheel install, CLI/TUI smoke, resource loading, and Pipeline-OFF check.

Python 3.14 is not part of validated CI matrix. Windows fresh-wheel package installation was not separately exercised by package job.

## Environment

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

On Windows, use `.venv\Scripts\python.exe` when venv is not activated.

## Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
zeroagent --help
zeroagent --version
zeroagent doctor
python -m zeroagent --help
```

Package build and scan run in CI:

```bash
python -m pip install --upgrade build
python -m build --wheel --sdist --outdir dist
python scripts/verify_package.py dist
```

Do not publish, tag, or modify release metadata from routine development checks.

## Documentation maintenance

- Keep README claims tied to source code and current CI evidence.
- Document active Textual UI in [tui guide](tui.md); do not present legacy `zeroagent.tui` as default CLI UI.
- Keep command syntax and exit-code claims consistent with `src/zeroagent/cli.py` and [usage guide](usage.md).
- State security boundaries and limitations; do not claim semantic correctness, full sandboxing, or perfect redaction.
- Update [troubleshooting](troubleshooting.md), [architecture](architecture.md), and [release checklist](release-checklist.md) when behavior or validation scope changes.

## Design rules

- Keep dependency set small and local-first.
- Add type annotations to runtime code.
- Keep network, provider, shell, and destructive actions opt-in.
- Add tests for every new behavior.
- Document current behavior separately from planned behavior.
