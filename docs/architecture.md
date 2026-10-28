# Architecture

## Explicit agent execution engine

`zeroagent.execution` owns agent-request validation, workspace validation, policy,
approval boundaries, lifecycle state, timeout, cancellation, normalized results, and
optional local BlackBox evidence. Adapters are explicitly registered; dynamic plugin
discovery is unsupported. The first adapter is `opencode`, which invokes an explicitly
configured local OpenCode executable through `opencode run --format json` without a
shell or `--auto`. OpenCode may require configured providers or network access, so the
engine rejects it unless agent execution, OpenCode, and network access are explicitly
enabled. This is not OS sandboxing. Output and evidence are bounded and redacted best
effort; local evidence is not tamper-proof.

## Current components

Project uses `src/` layout and one small runtime surface:

- `zeroagent.cli`: Typer CLI and `doctor` diagnostics.
- `zeroagent.config`: immutable Pydantic `Settings` with safe defaults.
- `zeroagent.__main__`: module entry point.
- `zeroagent.security.workspace`: explicit workspace path resolution and validation.
- `zeroagent.core.discovery`: bounded metadata-only recursive discovery.
- `zeroagent.core.repository`: report models, language and manifest detection, and
  safe dependency declaration parsing.
- `zeroagent.routing.router`: static capability registry, rule classifier, policy
  gate, deterministic routing evidence, and local handlers.
- `zeroagent.proof`: strict proof models, static verification registry, and
  deterministic checks for routing and repository reports.
- `zeroagent.blackbox`: opt-in sanitized execution history and historical replay.
- `zeroagent.ai`: explicit optional loopback-only Ollama provider client.
- `zeroagent.tui`: Rich Neon Minimal TTY controller using existing service APIs.
- `zeroagent.context`: deterministic, bounded, read-only source selection and context assembly.
- `zeroagent.planning`: static tool catalog, deterministic task planning, and plan validation.

Namespace packages under `core`, `routing`, `tools`, `proof`, `history`,
`tools`, `proof`, `history`, and `providers` reserve clear extension boundaries.

## Repository analysis

`zeroagent analyze PATH` resolves explicitly selected directory then traverses
regular files beneath it. It does not follow child file or directory symlinks.
Symlink workspace roots are resolved only because user explicitly selected them.
Traversal has default limits: 10,000 files, 5,000,000 bytes per included file,
and depth 20. Files beyond a limit are skipped and report becomes incomplete.

Discovery always ignores `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`,
`.pytest_cache`, `.ruff_cache`, `dist`, and `build`. It also uses `pathspec`'s
maintained `GitIgnoreSpec` for root `.gitignore` patterns. This implements
gitwildmatch matching for that root file; nested `.gitignore`, `.git/info/exclude`,
and global Git excludes are not read.

Language statistics count discovered files by extension or known filename. They
are not line counts or estimates of code volume. Report evidence only includes
workspace-relative paths. `analysis_timestamp` varies; all other report sequences
are sorted deterministically.

Supported language names: Python, JavaScript, TypeScript, Rust, Go, Java, C,
C++, C#, Ruby, PHP, Shell, HTML, CSS, JSON, YAML, TOML, Markdown, and Unknown.
Supported ecosystem manifests: `pyproject.toml`, `requirements.txt`, `setup.py`,
`package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, and
`build.gradle.kts`. Dependency extraction currently supports `pyproject.toml`,
`requirements.txt`, and `package.json` only.

## JSON report schema

JSON output is `AnalysisReport` schema version `1.0`. Top-level fields are
`schema_version`, `tool_version`, `analysis_timestamp`, `workspace_identifier`,
`file_count`, `directory_count`, `languages`, `ecosystems`, `manifests`,
`dependencies`, `evidence`, `warnings`, and `complete`. Dependency records state
declaration source and group where applicable. Warnings identify incomplete or
unsupported analysis; no confidence scores are generated.

## ZeroCost Router

`zeroagent route TASK` normalizes input and classifies whole-word tokens into
`repository_analysis`, `language_detection`, `dependency_inspection`,
`environment_diagnostics`, or `unknown`. More-specific dependency and language
rules take precedence over repository analysis. No confidence scores or semantic
understanding claims are made.

Built-in capabilities are static code registrations: `repository_analyzer`,
`language_statistics`, `dependency_inspector`, and `environment_diagnostics`.
They are deterministic, local, and do not use providers. Registry ordering uses
numeric priority then capability identifier.

Before selection, policy rejects unavailable capabilities and capabilities that
require disabled network access, paid APIs, cloud provider access, or shell
execution. Policy evaluation is routing authorization, not OS-level sandboxing.
`route` never invokes handlers. `run` requires a selected handler, validates
workspace requirements, then invokes only that static handler. Unknown tasks fail
without execution.

Router reports use `RoutingDecision`: task, classification and match reason,
selected capability, decision, policy snapshot, evaluated candidates, and whether
execution happened. `run --format json` also returns real handler result.

Zero paid API use means no paid API is required by these capabilities. Local CPU,
memory, storage, and electricity costs still apply. LLM routing is future work.

## ProofEngine

`zeroagent run TASK --verify` verifies actual routed execution result. It never
trusts a generic success field. Routing checks independently inspect current static
registry and effective settings. Repository checks validate schema version, counts,
file-count language percentages, manifest evidence, language-inventory evidence,
relative evidence paths, and declared completeness.

Proof records use `PASS`, `FAIL`, `INCOMPLETE`, and `NOT_APPLICABLE` per check.
Overall status is `FAILED` if any required applicable check fails; otherwise
`INCOMPLETE` if any required applicable check is incomplete; otherwise `VERIFIED`
when at least one required applicable check passes. No required applicable checks
also yields `INCOMPLETE`. Failed and incomplete CLI proofs exit with codes `3` and
`4` respectively.

Evidence paths must be nonempty portable relative paths without `..` components.
Linux absolute paths and Windows drive or UNC paths fail. Evidence is untrusted
metadata; ProofEngine does not execute files, calculate hashes, validate signatures,
or prove report inventory completeness. Unsupported execution artifact types are
incomplete, not verified.

## AgentBlackBox

`run --record` persists one sanitized JSON record only after explicit opt-in.
Normal runs write no history. Default storage is outside analyzed workspace:
`$XDG_DATA_HOME/zeroagent/blackbox` or `~/.local/share/zeroagent/blackbox` on
Linux, and `%LOCALAPPDATA%/ZEROAGENT X/blackbox` on Windows. `--storage-dir`
overrides location. Records use schema `1.0`, UUID4-hex IDs, UTC timestamps,
ordered lifecycle events, minimal result summaries, and proof summaries.

`history`, `inspect ID`, and `replay ID` only read stored records. Replay is
historical display, not active re-execution. Default retention: 100 records, 1 MB
per record, and 30 days. Storage is not tamper-proof.

## Local AI

`zeroagent ai doctor`, `ai models`, and `ai ask` explicitly authorize local
Ollama communication. They alone contact Ollama. Default endpoint is
`http://127.0.0.1:11434`; only `127.0.0.1` or `::1`, port 11434, plain HTTP, and
root endpoint are accepted. Credentials, paths, queries, fragments, redirects,
and proxies are rejected or disabled. Loopback traffic is still a network
connection and not OS-level isolation.

Ollama is not a Python dependency. Install and start it manually, then obtain a
model manually. `ai ask` requires explicit installed-model ID, accepts only text,
and sends no files, workspace data, environment values, or tools. There is no
cloud or paid-provider fallback. Prompt and response lengths are bounded.

ProofEngine checks local AI metadata only. It marks semantic correctness,
truthfulness, code safety, and hallucination risk `INCOMPLETE`.

## Phase 8 Hardening

BlackBox validates record IDs, rejects symlinks, bounds stored and loaded JSON
sizes, and treats malformed records as unreadable. TUI strips control characters
and bounds untrusted displayed paths, record metadata, model identifiers, and model
responses. TUI local AI is repeated single-turn use: prior prompts are not sent.
History inspection displays stored event metadata; replay calls only existing
historical record helper and never invokes capability handlers.

## Workspace Context

`zeroagent context inspect` discovers only safe-file metadata. `context preview`
selects relevant paths using deterministic keyword/path scoring without reading
source content. `context ask` requires `--allow-context` before it reads selected
source excerpts or sends them to explicit local Ollama model.

Selection scores exact query/path token overlap, filename matches, manifest names,
and Markdown relevance, then tie-breaks by repository-relative path. Context has
defaults of 10 files, 32 KiB per file, 64 KiB total source bytes, and 200 lines
per excerpt. Sources include relative path, line range, SHA-256, and truncation
state. `.env*`, private-key names/extensions, credential filenames, binaries,
symlinks, and unsupported types are excluded.

Repository text is framed as untrusted data in provider prompt. It cannot change
permissions, tools, endpoint policy, or verification. Valid hashes and references
prove supplied excerpt structure only; they do not prove model explanation truth.

## Planning

`zeroagent plan create TASK --workspace PATH` creates an offline deterministic plan.
Each step states stable tool ID, dependencies, required permissions, and truthful
availability. `IMPLEMENTED`, `REQUIRES_AUTHORIZATION`, and `NOT_IMPLEMENTED` are
distinct. Plans never invoke tools or grant permissions. Validator rejects unknown
tools, permission changes, missing or cyclic dependencies, execution claims, and
unsafe/oversized plan files. Future code-write and process-execute tools are
descriptors only, with no handlers.

## Safe Editing

`edit validate` and `edit preview` are read-only. Structured proposals support
text `modify` and `create` with original/result SHA-256 hashes and canonical
proposal digest. `edit apply` requires exact digest approval, rechecks containment
and stale hashes, and uses per-file temporary replacement. Multi-file application
is not atomic. Explicit `edit recover` restores only files still matching applied
hash; recovery directory stays outside workspace.

## Premium Neon Agent Workspace

In interactive terminals, bare `zeroagent` enters the terminal's alternate screen buffer
(`\x1b[?1049h`), hiding previous shell output and rendering a full-viewport application
without polluting the shell scrollback buffer. On exit or cancellation (`q`, `ctrl_c`),
the original screen is cleanly restored (`\x1b[?1049l`). In noninteractive environments,
bare invocation prints standard help and never waits for input.

The interface is implemented with Textual. It owns the full viewport, alternate
screen lifecycle, focus, application screens, scrollable result panels, and
keyboard navigation. It replaces the former manually redrawn Rich menu loop.

The interface centers around a restored 10-item Main Menu:
1. Analyze Repository
2. Ask About Repository (Context Engine)
3. Plan Agent Task (Planning Engine)
4. Safe Code Editing
5. Run Controlled Tests (Allowlisted Pytest)
6. Verify Execution (ProofEngine)
7. Execution History (AgentBlackBox)
8. Historical Replay
9. Local AI Chat (Dedicated Ollama interface)
10. Settings

Each item navigates to a dedicated screen with its own layout, state, and clear Esc/Back
navigation. Branding features the authoritative official PNG logo asset (`assets/logo.png`)
streamed safely via direct terminal driver file transmission (Kitty `t=f` / iTerm2 inline)
without loading binary payloads into Textual/Rich widget trees. In standard terminal
environments lacking graphics protocols, the clean stylized glyph `⨉` renders directly
beside the wordmark.
Redundant numeric shortcut bars are omitted from the footer in favor of contextual key guidance
(`↑↓ Navigate`, `Enter Select`, `/ Commands`, `Esc Back`, `q Exit`). A compact single-line
`CommandComposer` docks above the footer with rounded cyan focus highlighting.

## Controlled Test Execution

`zeroagent test create` constructs a test specification bounded by runner allowlist
(`pytest`). `test preview` displays exact command and digest. Execution via `test run`
strictly mandates matching exact digest approval. Tests are executed via direct
argument array subprocess invocations (`sys.executable -m pytest`), never via shell string.
Timeouts and output byte limits prevent deadlocks and uncontrolled log inflation. ProofEngine
checks execution completion, allowlisting, and exit status, while marking semantic correctness
incomplete.

## Intended growth

Future components must keep policy separate from execution. A tool boundary must
enforce authorization and workspace limits; proof
components must verify outputs; history must preserve reproducible records.
Provider integrations remain optional and must not create paid or network
fallback behavior by default.

No LLM or remote provider routing is implemented in this release.
