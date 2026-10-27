# Troubleshooting

Use `zeroagent doctor` first. It reports runtime version, platform, current directory, and safe-default policy state.

| Symptom | Likely cause | Verified action | Limitation |
|---|---|---|---|
| Unsupported Python or dependency install failure | Python below required `3.11` or wrong interpreter | Create venv with Python 3.11+ and run its `python -m pip install -e ".[dev]"` | CI validates 3.11–3.13, not Python 3.14 |
| `zeroagent` command not found | Venv not activated or console script not on `PATH` | Use `.venv/bin/zeroagent` on Linux, `.venv\Scripts\zeroagent.exe` on Windows, or `python -m zeroagent --help` | Project is not documented as PyPI install |
| `TUI requires an interactive terminal` | stdin/stdout is not TTY | Run in interactive terminal; use CLI commands in automation | `zeroagent tui` exits `2` when noninteractive |
| TUI renders poorly | Terminal emulator, width, graphics protocol, or alternate-screen behavior | Resize terminal; run `zeroagent tui --no-logo` | CI cannot cover every terminal emulator |
| Ollama unreachable | Service absent or not listening on validated local endpoint | Start Ollama locally; run `zeroagent ai doctor` | Only loopback HTTP at port 11434 is accepted; do not bypass endpoint validation |
| Requested model missing | Model not installed locally | Run `zeroagent ai models`, then choose listed `--model` | ZEROAGENT X does not download models |
| Context ask denied / no sources | Missing `--allow-context`, no eligible files, or exclusions | Use `context preview`; then explicitly pass `--allow-context` when intended | Sensitive/binary/symlink/unsupported sources remain excluded |
| Workspace error | Path missing or is not directory | Pass existing directory with `--workspace PATH` | Tool does not select fallback workspace |
| Edit approval rejected | Digest differs, workspace differs, invalid proposal, or stale source bytes | Run `zeroagent edit preview proposal.json --workspace PATH`; copy exact shown digest; regenerate proposal after source changes | Never bypass approval or stale-hash checks |
| Edit partially applied | Multi-file apply failed after earlier file change | Preserve recovery directory; inspect result; run `edit recover` only when files remain unchanged | Multi-file edit is not atomic; recovery is best effort |
| Test approval rejected | Spec digest/workspace mismatch or unsafe arguments | Validate and preview spec; use exact preview digest | Only `pytest` is allowlisted |
| Controlled tests unexpected side effects | Pytest executes workspace code | Approve only trusted workspace and arguments | Test execution is not OS-sandboxed |
| Proof is `INCOMPLETE` | No applicable structural check or incomplete evidence | Read check reasons; use result as incomplete, not verified | ProofEngine does not prove semantic correctness |
| Contributor Windows test digest mismatch | Fixture uses text write while digest expects LF bytes | Use byte writes for digest-paired test fixtures | This is contributor test-fixture guidance, not production validation bypass |

For security boundaries and vulnerability reporting, see [SECURITY.md](../SECURITY.md). For commands, see [usage reference](usage.md).
