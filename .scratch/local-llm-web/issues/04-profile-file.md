# 04: Profile file

**What to build:** The Profile file replaces the Style file, the config background block and `resume_url`. It's markdown at `~/.linkreach/profile.md` with fixed sections, a parser and checks shared by the Setup page and drafting, and a committed `profile.example.md`.

**Blocked by:** 03 (for the token estimate)

**Status:** ready-for-agent

- [ ] Sections: Background, Facts, Banned phrases, Example emails, Example connection notes
- [ ] Parser returns structured parts: Facts as a list, with their number tokens extracted; Banned phrases as a list; examples as lists
- [ ] Checks:
  - every section present
  - Background under a word cap
  - 2–3 of each example type
  - Facts is a bullet list
  - the whole file within a token budget that leaves room for profile data, the Angle and output at the configured `num_ctx`
  - each failure gets a human-readable message
- [ ] `profile.example.md` committed with three deliberately different example emails and notes; no resume link anywhere
- [ ] The Style file, its example, `resume_url` and the background config are removed
- [ ] Tests: valid file; each failed check; number extraction from Facts
