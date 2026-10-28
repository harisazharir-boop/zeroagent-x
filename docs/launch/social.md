# X and LinkedIn Drafts

All copy below is draft-only. Owner approval must name account, exact post, destination,
and timing before publication.

## X launch announcement

ZEROAGENT X v1.0.0 is public: local-first developer automation with CLI, Textual TUI,
explicit policy gates, request-bound approval, and inspectable local evidence.

Apache-2.0. No PyPI release. OpenCode stays opt-in and is not OS-sandboxed.

https://github.com/harisazharir-boop/zeroagent-x

## X technical thread

**1/5** ZEROAGENT X separates route, approval, execution, and evidence instead of
treating “agent task” as one opaque action. https://github.com/harisazharir-boop/zeroagent-x

**2/5** Built-in workflows start local-first: bounded repository analysis, deterministic
routing, planning, controlled edits/tests, and structural verification.

**3/5** Optional OpenCode execution is disabled by default. It needs explicit policy,
configured local executable, and opaque single-use request-bound approval.

**4/5** Important boundary: policy is application control, not OS sandboxing or physical
network isolation. Evidence is local and bounded, not tamper-proof. ProofEngine is
structural, not semantic proof.

**5/5** Release v1.0.0 has verified wheel/source assets and Apache-2.0 license. Looking
for technical feedback on local-first developer workflows and trust boundaries.

## X demo announcement

Recording a real ZEROAGENT X walkthrough: safe `doctor` and repository analysis,
Textual workspace, then policy-gated agent request validation. No mocked provider run.

Repo: https://github.com/harisazharir-boop/zeroagent-x

## X architecture post

ZEROAGENT X architecture: CLI/TUI → ExecutionCoordinator → explicit adapter → bounded
local evidence. Policy and approval gates sit before external execution. That improves
control, but it does not create OS sandboxing. Diagram and docs:
https://github.com/harisazharir-boop/zeroagent-x/blob/ci/phase-14a-validation/docs/architecture.md

## X feedback request

What would you need to inspect before trusting local developer automation in a
workspace? ZEROAGENT X v1.0.0 is looking for feedback on CLI ergonomics, policy
boundaries, and documentation gaps: https://github.com/harisazharir-boop/zeroagent-x

## LinkedIn launch announcement

ZEROAGENT X v1.0.0 is now public: an Apache-2.0, local-first developer automation
platform for Python developers and terminal users.

It combines bounded repository analysis, deterministic routing, explicit policy-gated
workflows, request-bound approval, Textual TUI, and inspectable local evidence. Optional
OpenCode integration stays disabled by default and requires explicit policy and approval.

Design goal: make developer automation easier to control, monitor, and understand.

Important limits are documented clearly. It is not OS-sandboxed; application network
policy is not physical network isolation; evidence is not tamper-proof; and
ProofEngine does not guarantee semantic correctness.

Repository: https://github.com/harisazharir-boop/zeroagent-x
Release: https://github.com/harisazharir-boop/zeroagent-x/releases/tag/v1.0.0

Feedback from Python, local-first, CLI, and developer-tooling communities is welcome.

## LinkedIn architecture post

Developer automation needs visible trust boundaries. ZEROAGENT X uses separate layers:
CLI/Textual UI, explicit policy, request-specific approval, coordinator-owned lifecycle,
registered adapters, and bounded local evidence.

This structure does not turn an external agent into a sandbox. It does make permission
and execution decisions inspectable within application workflow. Details:
https://github.com/harisazharir-boop/zeroagent-x/blob/ci/phase-14a-validation/docs/architecture.md
