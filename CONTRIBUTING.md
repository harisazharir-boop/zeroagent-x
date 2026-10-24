# Contributing

Thank you for improving ZEROAGENT X.

## Setup

Requires Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
```

## Before opening pull request

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Keep changes focused. Add tests for behavior changes. Do not include secrets,
generated build output, or unrelated formatting churn. New network, shell,
destructive, or provider behavior must be opt-in and documented.

## Reporting issues

Use GitHub issue templates for bugs and feature requests. Include sanitized
reproduction steps. Report security vulnerabilities privately under
[SECURITY.md](SECURITY.md).
