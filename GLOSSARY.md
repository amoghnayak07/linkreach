# linkreach

A personal job-search outreach tool. For each job you're applying to, it finds the people worth contacting at that company, prepares an email draft and a connection note for each, and leaves the sending to you.

## Language

### Jobs and people

**Job**:
One role you're pursuing at one company, created from a pasted job description. Everything linkreach finds and writes hangs off a Job.
_Avoid_: Posting, opening, application

**Job description**:
The text of the role's posting as pasted by the user; the raw input a Job is created from.
_Avoid_: JD (in docs and UI), listing

**Person**:
Someone at a company who might be contacted, identified by their LinkedIn profile. A Person exists once, no matter how many Jobs they're picked for.
_Avoid_: Contact, lead, prospect

**Pick**:
A Person chosen as worth reaching out to for a specific Job. A Person can be a Pick for several Jobs, and outreach progress (drafted, emailed, replied…) belongs to the Pick, not the Person.
_Avoid_: Target, match, candidate

**Supplied pick**:
A Pick from a profile link the user researched and pasted themselves.

**Found pick**:
A Pick linkreach chose by searching, used to fill the remaining slots after Supplied picks.

**Pick target**:
How many Picks a Job aims for (5 by default). Found picks only fill up to it; Supplied picks are never cut to fit it.
_Avoid_: Limit, cap

**Decision-maker roles**:
The kinds of people linkreach picks: hiring managers, recruiters, team leads, managers, the CTO, and the CEO. Peers in the same role are not picked.

### Outreach

**Email draft**:
An unsent email to a Pick, saved in the user's Gmail Drafts folder for them to edit and send themselves. linkreach never sends email.
_Avoid_: Message, outreach email

**Connection note**:
The short text to include with a LinkedIn connection request, shown to the user and stored. The user sends it themselves.
_Avoid_: Invite message, InMail

**Style file**:
The user's own instructions and example emails and notes that every Email draft and Connection note is written to match.
_Avoid_: Template, prompt file

**Email finder**:
The step that turns a Pick's LinkedIn profile into a work email address.

**Reveal**:
One email lookup in an email-finder extension; it may spend a credit with that vendor.
_Avoid_: Lookup, unlock

### Browser

**Dedicated profile**:
The Chrome profile linkreach owns and drives, kept outside the user's everyday Chrome data, holding the LinkedIn session and the email-finder extensions.
_Avoid_: Automation profile, Chrome profile (unqualified)
