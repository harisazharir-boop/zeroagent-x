# Product Hunt Launch Package

## Product name

ZEROAGENT X

## Tagline

Local-first developer automation, under your control.

## Short description

Terminal workflows for inspectable developer automation with explicit policy and
request-bound approvals.

## Full description

ZEROAGENT X is an Apache-2.0 developer automation platform for Python developers and
terminal users who want local-first workflows with clear execution boundaries.

Use CLI or Textual TUI for bounded repository analysis, deterministic task routing,
planning, approval-bound editing and pytest workflows, structural verification, and
opt-in local history. Optional Ollama integration stays loopback-only. Optional
OpenCode execution is disabled by default and requires explicit policy, configured
local executable, and a single-use approval bound to exact request.

Limits are deliberate: external agents are not OS-sandboxed, application network policy
is not a firewall, edits are not transactional, evidence is not tamper-proof, and
ProofEngine does not prove semantic correctness. PyPI is not used for v1.0.0.

Try release v1.0.0: https://github.com/harisazharir-boop/zeroagent-x/releases/tag/v1.0.0

## Maker introduction

I built ZEROAGENT X to explore developer automation that starts from local inspection,
explicit user actions, and visible policy decisions instead of automatic external-agent
execution. Feedback on trust boundaries and terminal workflows is welcome.

## First comment

Thanks for checking out ZEROAGENT X. Best first path: verify release checksum, install
wheel, run `zeroagent doctor`, then `zeroagent analyze . --format json`. See
`docs/quickstart.md` for safe defaults and optional integration limits. Please share
reproducible setup friction or policy questions; no artificial upvote requests.

## FAQ

**Is it on PyPI?** No. Install source or verified GitHub Release wheel.

**Does it use cloud AI by default?** No. Cloud and paid-provider fallback are disabled.

**Is OpenCode sandboxed?** No. It is policy-gated, not OS-sandboxed.

**Does ProofEngine prove output correctness?** No. It performs implemented structural checks.

**Which platforms?** CI validates Ubuntu and Windows on Python 3.11–3.13.

## Pre-launch checklist

- [ ] Owner approves Product Hunt account, copy, screenshots, and timing.
- [ ] Screenshots are real and redacted.
- [ ] Release link and asset checksums rechecked.
- [ ] No PyPI claim, invented metric, or security guarantee.
- [ ] Maker available to answer questions.
