# 03: Local model client (Ollama)

**What to build:** `structured_call` backed by Ollama's native `/api/chat`, replacing the Anthropic and Claude Code backends (ADR-0004). Existing callers (extract, rank, draft) keep working through it.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] Client sends `format` = the JSON schema, `think: false`, `options.num_ctx` and the temperature for each call; base URL, model and context size come from settings (`.env`)
- [ ] Replies are parsed and checked against the schema; malformed JSON counts as a failed attempt for the caller's retry logic
- [ ] A conservative token estimate runs before each call; prompt + output reserve over `num_ctx` raises a clear "prompt over budget" error naming the largest parts
- [ ] Ollama unreachable or model not pulled → a clear error naming `ollama pull <model>`
- [ ] `anthropic` removed from dependencies and the lock; `claude_code.py`, `llm_backend`, `ANTHROPIC_API_KEY` and `set-key` deleted; the cache-control prompt wrapping removed
- [ ] The fake model client in `tests/fakes.py` is updated to the new interface
- [ ] Tests: schema-valid reply, malformed reply, over budget, unreachable; `live_model`-marked smoke test against real Ollama
