# Contributing

Contributions improve ZEROAGENT X.

## Setup

Requires Python 3.11 or newer. CI supports Ubuntu and Windows with Python 3.11, 3.12, and 3.13.

```bash
python -m pip install -e ".[dev]"
```

## Before opening pull request

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m pip check
```

Keep changes focused. Add tests for behavior changes. Do not include secrets,
generated build output, or unrelated formatting churn. New network, shell,
destructive, or provider behavior must be opt-in and documented.

## Reporting issues

Use GitHub issues for bugs and feature requests. Include sanitized reproduction
steps, platform, Python version, expected behavior, and actual behavior. Report
security vulnerabilities through [SECURITY.md](SECURITY.md), never public issues.
