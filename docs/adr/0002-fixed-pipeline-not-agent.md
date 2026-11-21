# A fixed pipeline, not an autonomous agent

Processing a Job runs fixed steps in code (read the job description → search → rank Picks → find emails → draft), with Claude called only at specific steps and never deciding which page to open. We rejected an agent that browses on its own because page-view caps, the domain allowlist, and stop-on-CAPTCHA are only enforceable when code picks every navigation, and because scraped profile text reaching a model that controls the browser is a direct prompt-injection path.
