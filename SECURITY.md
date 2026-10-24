# Security Policy

## Reporting vulnerabilities

Do not file public issue for suspected vulnerability. Until dedicated private
reporting channel exists, contact project maintainers through repository owner
contact and include impact, reproduction steps, affected version, and sanitized
evidence. Do not include secrets or private repository content.

## Current security behavior

This release has no agent executor, tool runner, provider client, network client,
shell executor, or telemetry client. `zeroagent doctor` reads local runtime data
only. `zeroagent analyze` reads selected workspace metadata and supported manifest
text; it does not execute, import, install, or transmit repository content.

Typed defaults disable telemetry, network access, cloud providers, paid API
providers, and shell-command execution. Unknown configuration fields are
rejected. These defaults are tested.

## Workspace trust model and limits

Analysis requires explicit workspace path. It resolves selected path and rejects
missing paths and files. Child symbolic links are skipped, so discovery does not
follow them outside workspace or enter symlink loops. Results use relative paths,
not workspace absolute paths. File count, file size, and directory-depth limits
bound traversal. Unreadable entries create warnings instead of aborting analysis.

This is not filesystem sandboxing. ZEROAGENT X runs with user's operating-system
permissions, and an explicitly selected workspace root may itself be a symlink to
any accessible directory. Malicious local filesystems can still cause races,
resource pressure within configured limits, or parser errors. Treat reports and
manifest declarations as untrusted data.

## Router policy boundary

Router task text is untrusted input. Classification uses fixed whole-word rules;
it never evaluates text, dynamically imports code, or executes shell commands.
Only static built-in capability handlers can run. Routing checks availability and
network, paid API, cloud-provider, and shell policy before selecting a capability.
Route-only commands do not invoke handlers. Unknown, unavailable, or forbidden
tasks fail without fallback to a paid or remote provider.

Routing policy is not an OS sandbox. Approved repository handlers still operate
under current user's permissions and inherit Repository Intelligence workspace
limits. No LLM, cloud provider, network client, or shell executor exists in this
phase.

## ProofEngine boundary

ProofEngine validates consistency of untrusted execution artifacts using fixed,
local checks. It verifies registry and policy compatibility for routing decisions,
plus repository report structure and evidence-path safety. It does not execute
repository code or evidence files, run shell commands, use network services, or
load plugins dynamically.

`VERIFIED` means required implemented checks passed. It does not prove filesystem
inventory exhaustiveness, absence of filesystem races, cryptographic integrity,
absence of secrets, code safety, or absence of vulnerabilities. Absolute and
parent-traversal evidence paths fail; missing evidence produces failure or
incomplete verification. ProofEngine is not OS-level sandboxing.

## AgentBlackBox privacy boundary

BlackBox is disabled by default and requires `--record`. Records are stored outside
workspace by default. Credential-like fields and common free-text secret patterns
are redacted before persistence; source contents and environment values are not
recorded. Redaction is best-effort, not perfect. Stored history is untrusted input.
Replay never executes handlers, accesses workspace, or creates records. Storage
limits and ID/symlink checks reduce risk but do not make records tamper-proof.

## Local AI boundary

Only explicit `zeroagent ai` commands contact configured local Ollama service.
Endpoint validation permits only loopback HTTP on port 11434, disables environment
proxies, and rejects redirects. Normal analysis, routing, execution, proof, and
history commands never contact Ollama. No cloud, paid-provider, or automatic
model-download fallback exists. Local model output is untrusted text; ProofEngine
cannot establish its factual accuracy or safety.

## Neon Minimal TUI boundary

TUI is a presentation controller over existing service APIs. It does not execute
shell commands, enable recording, contact Ollama from dashboard status, or change
policy defaults. Local AI health is checked only when user selects Local AI screen.
Historical replay screen is informational and directs execution-ID replay to its
existing read-only command.

## Phase 8 hardening boundary

TUI treats workspace paths, record metadata, model output, and other external text
as untrusted display data. Control characters are replaced and display length is
bounded before Rich rendering. BlackBox rejects oversized records before JSON read.
These measures reduce terminal-output and resource-exhaustion risk but do not
provide a terminal sandbox or cryptographic record integrity.

## Workspace context boundary

Repository discovery and repository content reads are separate. `context inspect`
and `context preview` do not read source text. `context ask` requires
`--allow-context` before bounded selected excerpts go to explicitly selected local
Ollama model. Sensitive filenames, symlinks, binaries, and unsupported file types
are hard excluded. No user path bypasses these exclusions. Context excerpts are
untrusted data; prompt framing reduces but cannot eliminate model prompt-injection
risk. Hashes prove supplied bytes, not AI interpretation correctness.

## Security requirements for future features

- Destructive actions require explicit user authorization.
- File access must be constrained to declared workspace boundaries.
- Untrusted code must not execute automatically.
- Arbitrary shell commands must not execute automatically.
- Repository content must not transmit automatically.
- Paid API fallback must remain disabled unless user opts in.
- Logs must avoid exposing secrets and sensitive content.
- New dependencies require maintenance, provenance, and vulnerability review.

These requirements are project policy, not implemented enforcement mechanisms
in this foundation release. Future feature work must add enforcement and tests
before claiming protection.
