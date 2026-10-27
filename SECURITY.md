# Security Policy

## Reporting vulnerabilities

Do not file public issue for suspected vulnerability. Until dedicated private
reporting channel exists, contact project maintainers through repository owner
contact and include impact, reproduction steps, affected version, and sanitized
evidence. Do not include secrets or private repository content.

## Security support status

ZEROAGENT X `0.12.0b1` is an unpublished beta candidate. No public beta
release line is supported until a maintainer publishes one. After publication,
the maintainer must identify supported release line(s) and any security-fix
policy for that beta; historical development and unreleased versions are not
security-supported releases. This policy does not promise a response time or
long-term maintenance commitment.

## Current security behavior

Current beta candidate has explicit policy-gated local handlers, controlled
editing, and allowlisted pytest execution. It has no cloud provider, paid-provider fallback,
arbitrary shell executor, telemetry client, or automatic execution. `zeroagent
doctor` reads local runtime data only. `zeroagent analyze` reads selected workspace
metadata and supported manifest text; it does not execute, import, install, or
transmit repository content.

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

## Phase 13F threat matrix

| Threat | Protection | Evidence | Residual risk |
|---|---|---|---|
| Arbitrary shell execution | Static handlers; shell policy disabled | `tests/test_router.py`, `tests/test_pipeline.py` | Not OS sandboxing |
| Workspace traversal / symlink escape | Resolved root; child symlinks skipped | `tests/test_repository.py` | Selected root may be symlink |
| Stale Agent route | Task/workspace bound route invalidation | `tests/test_textual_app.py` | Filesystem may change after analysis |
| Approval reuse / cross-run approval | Digest, workspace, run identity, single use | `tests/test_pipeline.py` | User-approved proposal remains untrusted |
| Duplicate guarded execution | Pipeline worker ownership and Agent running guard | `tests/test_pipeline.py`, `tests/test_textual_app.py` | Sync Agent handlers settle, not force-cancelled |
| Fabricated proof | ProofEngine checks actual artifact evidence | `tests/test_proof.py` | Structural proof is not semantic correctness |
| Replay side effects | Replay reads records only | `tests/test_blackbox.py` | Stored records are untrusted |
| Secret leakage | Best-effort redaction, bounded storage | `tests/test_blackbox.py` | Redaction cannot guarantee all secret forms |
| Remote AI / cloud fallback | Loopback-only endpoint; cloud disabled | `tests/test_ai.py`, `tests/test_router.py` | Optional local Ollama requires trusted local host |
| Unsafe shutdown | Agent/Pipeline wait for owned work settlement | `tests/test_textual_app.py`, `tests/test_pipeline.py` | Long synchronous handlers delay exit |

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

## Neon Minimal TUI & Alternate-Screen boundary

TUI is a presentation controller over existing service APIs that isolates rendering in the
terminal's alternate screen buffer (`\x1b[?1049h`). It does not execute shell commands,
enable recording, contact Ollama from dashboard status, or change policy defaults. Local
AI health is checked only when the user explicitly navigates to the dedicated Local AI screen.
Controlled testing requires exact specification digest approval before execution, rejecting
all arbitrary shell commands and unallowlisted runners. Historical replay screen is read-only
and directs execution-ID replay to its existing read-only command. Terminal settings and cursor
modes are restored on exit.

The alternate screen prevents ZEROAGENT X frames from being appended to primary-shell
scrollback. Individual terminal emulators may still provide an emulator-level way to
inspect primary-screen history; ZEROAGENT X cannot control that implementation detail.

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

## Planning boundary

Planning is not authorization or execution. Plans are untrusted structured data
when loaded from disk and are validated against static tool metadata. Model output
cannot register tools, alter tool permissions, add shell commands, or execute plan
steps. Future write and process tools remain explicitly not implemented.

## Pipeline lifecycle boundary

Pipeline is OFF until an explicit Start action. Proposal and test-specification
approval requires exact current digest and bound workspace; approval is separate
from execution. Apply and Test run as owned guarded operations. Cancellation and
normal application shutdown wait for owned operations to settle before terminal
report, navigation, or exit. This protects normal application-controlled shutdown,
not SIGKILL, power loss, or forced process termination.

## Controlled editing boundary

Editing supports explicit approved regular-text modification and creation only.
Absolute/traversal paths, symlinks, Git internals, environments, build folders,
and sensitive credential filenames are rejected. Apply rechecks source hashes and
refuses stale proposals. Recovery is explicit, best-effort, and refuses files
changed after application. Multi-file writes are not transactional; recovery data
can contain original source bytes and must stay outside workspace.

## Controlled testing security boundary

Test execution allows ONLY strictly allowlisted test runners (`pytest`) invoked directly
via array-based argument lists without shell wrappers or command-line string evaluation.
Exact digest approval is required before running tests. Testing executes code within the
workspace, meaning repository test suites can potentially perform filesystem and network
operations; testing is not sandboxed at the OS level and must only be approved in trusted
workspaces.

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
