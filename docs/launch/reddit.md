# Reddit Drafts

Check current subreddit rules and self-promotion policy before posting. Use one
relevant draft per permitted community; do not cross-post identical text or message
moderators repeatedly.

## r/Python

**Title:** Built ZEROAGENT X: local-first Python developer automation with explicit approvals

Released ZEROAGENT X v1.0.0, Apache-2.0 Python developer tooling with Typer CLI and
Textual UI. It focuses on bounded repository analysis, deterministic routing,
approval-bound editing/testing, structural verification, and local history.

OpenCode integration is present but disabled by default. External execution requires
explicit policy and single-use request-bound approval. It is not OS sandboxed and does
not claim physical network isolation.

Repo: https://github.com/harisazharir-boop/zeroagent-x

Looking for feedback on Python CLI ergonomics, docs, and policy design. What would you
want to inspect before trusting developer automation in a local workspace?

## r/opensource

**Title:** ZEROAGENT X v1.0.0: Apache-2.0 local-first developer automation

ZEROAGENT X is now public under Apache-2.0:
https://github.com/harisazharir-boop/zeroagent-x

Project defaults keep telemetry, cloud providers, paid APIs, shell execution, network,
and external-agent execution disabled. It includes CLI/TUI workflows, bounded analysis,
approval-bound operations, and documented security limits.

Would value maintainer feedback on contribution guidance, release packaging, and where
the project documentation needs more clarity.

## r/commandline

**Title:** A Textual + CLI workflow for local-first developer automation

Sharing ZEROAGENT X, a terminal-oriented Python tool with `zeroagent analyze`,
deterministic `route`, explicit local `run`, and an interactive Textual workspace:
https://github.com/harisazharir-boop/zeroagent-x

The key design choice is that route, approval, and execution are separate actions.
OpenCode execution is optional and disabled by default. Curious which terminal workflow
details matter most: output shape, safe defaults, keyboard navigation, or evidence
inspection.

## r/LocalLLaMA

**Title:** Local-first developer automation with optional loopback Ollama and governed OpenCode

ZEROAGENT X supports explicit local Ollama commands and an optional governed OpenCode
adapter: https://github.com/harisazharir-boop/zeroagent-x

Ollama is manually installed and limited to loopback HTTP on port 11434. No cloud or
paid fallback exists. OpenCode execution needs explicit policy and approval, and is not
a sandbox. Interested in feedback from people using local models alongside codebase
inspection tools.
