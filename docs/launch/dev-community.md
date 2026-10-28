# DEV Community Article Draft

# Why I Built ZEROAGENT X: A Local-First Approach to Developer Automation

Developer automation is useful when it reduces repetitive work without hiding what it
will read, run, or change. I built ZEROAGENT X to explore local-first workflows where
policy, approval, execution, and evidence are separate visible steps.

## Problem

Agent tools often combine task interpretation and execution into one experience. That
is fast, but it can make trust boundaries hard to inspect. ZEROAGENT X starts smaller:
bounded repository analysis, deterministic routing, explicit local operations, and
optional external-agent integration.

## Why local-first

Safe defaults disable telemetry, cloud providers, paid APIs, network access, shell
execution, and external-agent execution. Built-in analysis does not execute repository
code. Optional Ollama use is explicit and loopback-only. No PyPI package or automatic
cloud fallback exists in v1.0.0.

## ExecutionCoordinator and policy

`ExecutionCoordinator` owns validation, workspace checks, policy evaluation, lifecycle,
timeouts, cancellation, normalized results, and optional bounded local evidence.
The OpenCode adapter is registered explicitly rather than discovered dynamically.
Application policy is not an operating-system sandbox or firewall; it makes application
decisions visible and enforceable inside ZEROAGENT X.

## Request-bound approval

A request fingerprint identifies exact request and relevant policy state, but it is not
an authorization credential. Interactive approval creates an opaque local token. Token
expires after five minutes, binds to one request, and consumes once. This makes approval
a separate deliberate action, not a reusable hash.

## CLI and Textual TUI

Start with safe commands:

```bash
zeroagent doctor
zeroagent analyze . --format json
zeroagent route "Analyze this repository"
```

Use `zeroagent tui --workspace .` in interactive terminal for Textual Agent Workspace.
The optional agent workflow exposes adapters, policy state, validation, approval,
execution, and local evidence separately.

## Security limits

External agents are not OS-sandboxed. Network policy is not physical network isolation.
External workspace modifications are not transactional. Evidence is not tamper-proof.
ProofEngine checks implemented artifact structure, not semantic correctness or source
safety. Those boundaries are documented because transparent limits matter as much as
capabilities.

## Get started

Download release v1.0.0 and verify `SHA256SUMS` before installing wheel:

```bash
sha256sum -c SHA256SUMS
python -m pip install zeroagent-1.0.0-py3-none-any.whl
zeroagent doctor
```

Repository and full quick start:
https://github.com/harisazharir-boop/zeroagent-x

Technical feedback on policy boundaries, local-first ergonomics, and terminal workflow
design is welcome.

**Publication check:** Owner must approve DEV account, final formatting, tags, and timing.
