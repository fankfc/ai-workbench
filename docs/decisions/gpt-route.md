# GPT local route decision — D006

Decision date: 2026-10-13. Completion level: route decided, connection not enabled.

Use the already installed official Codex CLI (`0.160.0`) as the first candidate. The official non-interactive mode reuses saved CLI authentication. The read-only login check yielded only the fixed summary “ChatGPT login present”; the probe did not read `auth.json` or request an API key. A ChatGPT login establishes CLI authentication status, not independent API authorization or model identity. Sources: [OpenAI non-interactive mode](https://developers.openai.com/codex/noninteractive/) and the installed `exec`/`login` help.

The isolated Chinese fixture used `exec --json --sandbox workspace-write --ignore-user-config --ephemeral --skip-git-repo-check`. Existing policy denied the file-reading tool. The process exited 0 and emitted `turn.completed`, but did not produce `result.txt`. Structured JSONL contained token usage and a thread ID but no response model ID. The adapter therefore records unknown identity and rejects the task. It does not treat model prose, command flags, CLI names, a successful login or process exit as model verification.

The chosen future route is `native`, with zero mandatory translation operations. B may still be invoked as the executor through the common protocol. This policy statement is not a claim of a verified real end-to-end route. GPT remains `not_connected` and `production_enabled=false`. Do not silently switch A to another provider. Re-enable only after the actual provider response identifies the GPT model, required file/terminal tools work under the existing permission policy, and artifact bytes, finish event and exit status agree.

Evidence: `docs/acceptance/D006/probe-report.json`, `real-discovery.stdout.redacted.txt`, `real-discovery.stderr.redacted.txt`, `supported-entry.json` and `gate-check.json`. Session sharing, quota sharing, cancellation and resume remain unknown or unverified.
