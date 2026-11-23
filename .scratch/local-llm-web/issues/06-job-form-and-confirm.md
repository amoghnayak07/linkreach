# 06: Job form and confirm screen

**What to build:** The first half of starting a Job in the browser. Paste a Job description and profile links, get extracted fields from the local model, then confirm or edit them on a confirm screen. Clicking Run is wired in issue 07.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] The form accepts the Job description and any number of profile links; links are normalized and invalid ones flagged inline
- [ ] Submit runs the Extract call only and returns company, role, team and location; a missing company leaves the field empty and required
- [ ] The confirm screen allows editing all fields, shows the company's LinkedIn page (cached lookup, as today), and on confirmation creates the Job
- [ ] A Supplied pick whose Person already has a Pick at `emailed` or later on another Job is flagged with when and which Job, plus an "include anyway" checkbox, unticked by default
- [ ] Tests: extraction fills the form; missing company; duplicate flagged; links normalized; Vitest for the confirm screen
