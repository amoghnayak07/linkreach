# A local model via Ollama replaces Claude

Every model call (extract, rank, Angle, Email draft, Connection note) goes to a local model served by Ollama on the user's machine. The Anthropic API and Claude Code backends are deleted. The user wants no per-token cost and no Job description, profile data or background leaving the laptop. Forks must run on their owners' own hardware with no shared keys.

A small model (8–12B on an 8 GB GPU) writes worse and breaks rules more often than Claude, so the design compensates:

- one task per call, with the Angle made separately from the email and the note
- a short Profile file with 2–3 deliberately varied examples
- Facts as the only allowed numbers
- a Banned phrases list
- every one of those rules checked in code, with retries that name the broken rule

## Consequences

- The client uses Ollama's native `/api/chat` (JSON-schema `format`, `think: false`, `options.num_ctx`), not the OpenAI-compatible endpoint, because the latter can't set the context size per request and Ollama's default 4K context would silently cut off prompts.
- Prompts have a token budget checked in code before each call, and the Email draft call never sees the full Job description.
- The model is a `.env` setting. The default (`gemma4:12b-it-qat` or `qwen3.5:9b`) is chosen by measured comparison, not by code.
- Prompt caching and the `llm_backend` option go away.
