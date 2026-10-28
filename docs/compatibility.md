# Stable v1 Compatibility Contract

This document states stable interfaces for `1.0.0`. It describes source compatibility; publication is governed separately.

## Supported surface

- Python: 3.11, 3.12, 3.13.
- OS: Ubuntu and Windows CI matrix. Other OS use is best effort.
- CLI: documented `zeroagent` command groups and options in `docs/usage.md`.
- Settings: public `zeroagent.config.Settings` fields. New fields may be added with
  safe defaults; removal or semantic change requires documented migration.
- Execution: immutable `ExecutionRequest`, `ExecutionResult`, `AdapterCapabilities`,
  `AdapterResult`, and `AgentAdapter` contract under `zeroagent.execution`.
- Evidence: BlackBox schema `1.0` records remain readable while supported. Records
  are local, bounded, redacted best effort, and not authenticity evidence.

## Compatibility policy

Stable documented CLI and public models receive deprecation notice in changelog and
documentation before incompatible future stable removal where practical. Internal
widgets, private attributes, storage implementation, visual layout, and undocumented
modules have no compatibility promise. Pre-1.0 versions had no stable API guarantee.

## Security support and unsupported capabilities

Security reporting process is in `SECURITY.md`; support scope and response commitments
are intentionally limited there. ZEROAGENT X does not provide OS sandboxing, physical
network prevention, process isolation, transactional rollback, tamper-proof evidence,
or semantic proof. External provider availability and billing remain user-controlled.
