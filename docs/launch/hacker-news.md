# Hacker News Draft

**Suggested title:** Show HN: ZEROAGENT X – Local-first developer automation with policy-gated agents

I built ZEROAGENT X, an Apache-2.0 Python tool for developer workflows where
execution remains explicit and inspectable:

https://github.com/harisazharir-boop/zeroagent-x

It provides bounded read-only repository analysis, deterministic local routing,
planning, approval-bound edit and pytest workflows, structural evidence checks, local
history, and a Textual terminal UI. It also has an OpenCode adapter, but external
agent execution is disabled by default and requires explicit policy, a request-bound
single-use approval, and a configured local executable.

Why build it: many developer-agent workflows optimize for autonomous execution. This
project explores a different default: local-first analysis, visible policy boundaries,
and evidence that can be inspected after a run.

Important limits: this is not OS sandboxing; network policy is not a firewall;
external workspace changes are not transactional; stored evidence is not tamper-proof;
and ProofEngine verifies structural checks, not semantic correctness. There is no PyPI
package or cloud-provider fallback in v1.0.0.

Release wheel and source archive:
https://github.com/harisazharir-boop/zeroagent-x/releases/tag/v1.0.0

Interested in technical feedback on policy boundaries, local-first ergonomics, and
what would make this useful in your own terminal workflow.

**Publication check:** Confirm current Show HN rules, exact account, and timing before
submission. Do not add launch-day engagement requests.
