# 12: Claude Code backend for Claude calls (no API key needed)

**What to build:** The user is on a Claude Enterprise plan and has no Anthropic API key, so linkreach can't call Claude today. Add a second way to reach Claude: run the locally installed Claude Code CLI in headless mode (`claude -p`), signed in with the user's own account. A new `llm_backend` config setting chooses between `api` (today's Anthropic SDK client, using the API key) and `claude_code`. The choice is hidden behind the existing injectable client seam (`Drafter(cfg, client=...)` in `linkreach/drafting.py`). A `ClaudeCodeClient` provides the same `client.beta.messages.create(...)` call the code already makes, so drafting, validation, retries, and `needs_detail` handling stay unchanged. Every Claude call linkreach makes, now and later (drafting today; Job extraction and drafting in 03; ranking in 05), goes through whichever client is configured.

The CLI must run as a plain text-in, JSON-out model call and never as an agent. The prompt carries untrusted scraped profile text, and the current safety model assumes the model can't act on anything (ADR-0002, spec user story 39).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `llm_backend` is a validated config setting with values `api` and `claude_code`, defaulting to `api`; the example config documents it, including the Enterprise-plan use case
- [ ] With `claude_code`, no API key is needed or looked up: `make_client()` (or its replacement) returns a `ClaudeCodeClient`, and nothing asks for an API key or runs `set-key`
- [ ] `ClaudeCodeClient` runs `claude -p --output-format json --json-schema <schema> --system-prompt <system text> --model <cfg.model> --no-session-persistence` and sends the user message on stdin, not as a command-line argument (length limits, and it keeps profile text out of process listings)
- [ ] The call is locked down so it can only produce text: all tools disabled (`--tools ""`), no MCP servers (`--strict-mcp-config` with no config), no user/project/local settings (`--setting-sources` empty or the equivalent), and the working directory is a fresh empty temp folder so no `CLAUDE.md` or project files are loaded. A test checks the exact argv
- [ ] The CLI's JSON result is mapped back to the shape `Drafter._call` reads (`content` with a text block holding the structured JSON, `stop_reason`, `usage` when present). The exact result field names (for example `result` vs `structured_output`, and how errors, refusals, and usage-limit messages appear) are confirmed with one live `claude -p` call on a dummy prompt before coding against them, and recorded in a comment on this ticket
- [ ] Failures become the errors the drafter already handles: a non-zero exit, a timeout (configurable, default 120 s), unparseable output, or a usage-limit/sign-in error becomes a clear message (for example "Claude Code isn't signed in: run `claude` once and sign in"), never a stack trace. A refusal maps to `stop_reason == "refusal"`
- [ ] `use_refusal_fallbacks` and prompt caching are API-only. With `claude_code` they are skipped silently (no beta flags passed), and the example config says so
- [ ] Drafting concurrency is limited to at most 2 parallel calls with `claude_code` (each call starts a process), and stays as it is today with `api`
- [ ] Token usage is still logged when the CLI reports it; prompts, outputs, subjects, bodies, and notes are never logged (redaction as today)
- [ ] `doctor` checks the configured backend: with `api`, the existing API-key check; with `claude_code`, that `claude` is on PATH and that a tiny no-tools test call succeeds (meaning it's signed in), reporting a clear fix when not
- [ ] The `claude` executable path can be overridden in config (`claude_code_path`, default `claude` resolved from PATH) for Windows installs outside PATH
- [ ] Tests use a fake subprocess runner injected into `ClaudeCodeClient` (real `claude` is never called in tests). They cover: argv lockdown, stdin delivery, a successful structured result driving a full `draft` run to `drafted`, non-zero exit, timeout, malformed JSON, refusal, sign-in error, and `doctor` reporting a missing or signed-out CLI
- [ ] README explains both backends, how to pick one, and a note for Enterprise users: calls count against the seat's usage limits, and they should check that their organization allows scripted and personal use

## Notes

- Seam: `Drafter` already takes `client`. Keep the backend choice in one factory, so the `job` pipeline in 03 gets it without knowing which backend is active. If 03 lands first, it should build its Claude calls on the same client object rather than calling `anthropic.Anthropic` directly.
- Verified on the user's machine (2026-11-21): Claude Code `2.1.322` is installed at `~/.local/bin/claude.exe`, not configured for Bedrock or Vertex, and its `--help` lists `-p`, `--output-format`, `--json-schema`, `--system-prompt`, `--tools`, `--model`, `--strict-mcp-config`, `--setting-sources`, and `--no-session-persistence`.
- Alternatives considered: an API key from the org's Anthropic Console (no code change), or `AnthropicBedrock`/`AnthropicVertex` if the org offers Claude through a cloud provider (a one-function change in `make_client()`). Neither is available to the user right now, which is why this ticket exists. Both could still be added later as more `llm_backend` values.
