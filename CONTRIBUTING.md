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

## Good first contributions

Start with a reproducible bug, documentation correction, test coverage gap, or
small scoped usability improvement. Discuss broad architecture or security-boundary
changes in an issue before implementation. Maintainers label real, bounded tasks when
available; this project does not create placeholder issues for appearance.

## Pull request expectations

Explain user-visible behavior, validation performed, and any compatibility impact.
Keep security claims precise. Never add telemetry, automatic network access, external
providers, shell execution, or destructive behavior without explicit opt-in, tests,
and documentation.

## Reporting issues

Use GitHub issues for bugs and feature requests. Include sanitized reproduction
steps, platform, Python version, expected behavior, and actual behavior. Report
security vulnerabilities through [SECURITY.md](SECURITY.md), never public issues.
