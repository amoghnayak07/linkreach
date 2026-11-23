# 13: Model comparison (Gemma 4 12B QAT vs Qwen3.5 9B)

**What to build:** A script that runs the real Angle, Email and Note prompts for 3–4 saved Job descriptions and profile samples against each configured model. It writes the drafts side by side with speed and GPU-fit numbers, so the user can pick the default model.

**Blocked by:** 03, 04, 08

**Status:** ready-for-human (the user reads the drafts and picks)

- [ ] Inputs: a folder of sample Job descriptions and profile snippets (gitignored) plus the user's Profile file
- [ ] For each model (`gemma4:12b-it-qat`, `qwen3.5:9b` by default): the outputs, how many attempts code validation took, tokens/sec, and the `ollama ps` CPU/GPU split at the configured `num_ctx`
- [ ] Output: one markdown report in `.scratch/local-llm-web/`
- [ ] Decision recorded in the report and `.env.example` updated: Gemma is the default unless it doesn't stay 100% on the GPU at 8K or clearly writes worse
