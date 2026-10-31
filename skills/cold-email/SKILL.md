---
name: cold-email
description: Find fresh job openings that match your CV (free sources only), find a real, sourced contact email for each, and write short personal cold emails as Gmail DRAFTS for you to review. Never sends. Use when the user says "/cold-email", "cold email jobs", "find jobs and draft emails", "write cold emails to startups", "follow up on my cold emails", or wants a daily job-outreach run.
---

# /cold-email

You run a small, honest job-outreach loop for the user: **find → match → contact → draft → track**.
The user only reviews drafts. You never send anything.

Scripts live next to this file in `scripts/` (Python 3.9+, standard library only). Call them as
`python3 "<this skill dir>/scripts/cli.py" <command>`. Data lives in `~/.cold-email/` (override with
`COLD_EMAIL_HOME`), never in the repo.

## Hard rules (never break these)

1. **Drafts only.** Create Gmail drafts. Never call a send tool, never schedule a send, never reply on the user's behalf.
2. **Every email address needs a source URL** where it was found (job ad, LinkedIn post snippet, Impressum, team page). Store it and show it. **Never guess an address or an email format** (no `firstname.lastname@` guesses, no pattern tools). No sourced address → mark "no contact found" and skip.
3. **LinkedIn: search results only.** Use web search for public posts and read the result title/snippet. Never log in to LinkedIn, never open LinkedIn pages in a browser or headless browser, never scrape profiles. Paid scrapers (Apify etc.) only if the user explicitly asks and accepts the cost.
4. **Real facts only.** The human line about the company must come from a source you read (job ad, post, company page) and you keep that URL. Never invent a compliment, a mutual contact, a metric, or a project the user did not list.
5. **Low volume, personal.** Max ~10 new drafts per run (the user may lower it). Public business contacts only. Skip recruiting agencies unless the user asks.
6. **Skip anyone already emailed**: check the tracker and Gmail Sent before drafting.

## Step 0: profile (first run only, or "update my profile")

1. Ask for the CV file (PDF, DOCX or text). Run `cli.py profile init --cv <path>`.
   If `pdftotext` is missing, read the PDF yourself, save its text to `~/.cold-email/cv.txt`, and run `profile init --cv ~/.cold-email/cv.txt`.
2. Show the detected sections and top terms. Then ask, in one message:
   - target roles (2–5 job-title phrases, e.g. "Software Engineer, Backend Engineer, Werkstudent Software")
   - cities (and "Remote" if remote is fine)
   - level: `student`, `junior`, `mid`, `senior` (one or more)
   - **one project** they want to lead with: one sentence + a link (demo, GitHub, Loom). Must be real.
   - their first name, and the links for the signature (LinkedIn / GitHub / portfolio)
   - optional: companies to watch with a public job feed, as `greenhouse:<slug>=<domain>`, `lever:<slug>=<domain>`, `ashby:<slug>=<domain>`, `personio:<slug>=<domain>`
3. Save: `cli.py profile set --roles "..." --cities "..." --seniority "..." --sender-name "..." --project-line "..." --project-link "..." --links "..." [--watch "..."]`.

## Step 1: find jobs (free sources)

1. `cli.py find` pulls Arbeitnow, Bundesagentur für Arbeit (Jobsuche), Hacker News "Who is hiring?" and the watched ATS feeds,
   drops anything older than 30 days, and scores each job against the CV. Show the per-source status line.
2. **LinkedIn posts via web search** (2–4 searches per run, vary role and city), for example:
   - `site:linkedin.com/posts "hiring" "send your CV" <city> <role>`
   - `site:linkedin.com/posts "we're hiring" <role> <city> "email"`
   - `site:linkedin.com/posts "Werkstudent" <role> "<city>" "CV"`
   For each result that is a hiring post (not advice, not a course pitch), run
   `cli.py linkedin --url "<result url>" --title "<result title>" --snippet "<snippet text, verbatim>" [--company "<company>"]`.
   The script reads the post date from the URL's activity id (`id >> 22` = epoch ms) or from "N days ago" in the snippet,
   drops posts older than 30 days, and pulls any email that is written in the snippet.
   If your search tool gives no `linkedin.com/posts` URLs, try it with the domain filter set to linkedin.com; if there is still nothing, say so and move on.

## Step 2: shortlist and contacts

1. `cli.py shortlist --limit 15` returns jobs whose title fits a target role and level and whose score is at least 0.3,
   with the best sourced contact (email in the ad first, then the company's Impressum / contact / team pages when the company site is known).
   Agencies and anything already in the tracker are skipped.
2. For a good job with `"contact": "no contact found"` and no company site: web-search `"<company>" Impressum` or `"<company>" imprint`,
   pick the company's **own** domain (not a job board), then run `cli.py contacts --site https://<domain> --job <id>` and re-run `shortlist`.
   Give up after one try per company.
3. Choosing the person (from the guide): startups (< 50 people) → a founder / CTO / founding engineer; bigger companies → the hiring manager,
   not HR. Use a name only if a source shows it (ad's contact person, post author, Impressum's Geschäftsführer, team page).
   If the only address is `info@` / `jobs@`, address the named person if the Impressum lists one ("Hi Anna,"), otherwise "Hi <Company> team,".
4. Present the shortlist as a table: company, role, score, matched terms, posted date, contact (email kind + source URL).
   Keep the ~10 best that have a contact. Email addresses may be shown to the user (it is their run); do not paste them anywhere else.

## Step 3: Gmail check (before drafting)

With the user's Gmail connector (tool names vary, e.g. `search_threads` / `search_messages`):
- Search `to:<email>` in Sent (`in:sent to:<email>`). If found → skip and `cli.py track add ... --status sent --notes "already emailed"`.
- Search `from:<email>`. If there is a reply to an earlier email → `cli.py track set --email <email> --status replied` and tell the user.
- If there is no Gmail connector, say so, and rely on the tracker only.

## Step 4: write the drafts

Read `references/style.md` and write **one email per contact**. Requirements (the linter checks the mechanical ones):
- under 120 words, subject `<Role> at <Company>: built something for you` (or a sharper true variant)
- first line = one real, specific thing about them (from a source you read; keep its URL for the log)
- "I prefer to let what I build speak louder than a traditional self-introduction:" + the user's project line + link
- one line on why it fits their stack/product, using only matched terms that are really in the CV
- one ask: "Would you be open to a 15-minute chat this week?"
- signature: first name + links from the profile
- no attachments, no "Dear Sir or Madam", no "any opportunities", no placeholders left

Check every body: `printf '%s' "<body>" | python3 cli.py lint -` must print `"ok": true`. Fix and re-check.

Then create the draft with the Gmail connector's **create draft** tool (to = the sourced address, subject, plain-text body).
Never use a send tool. If there is no Gmail connector or it cannot create drafts, output each email as a copy-ready block plus a
`mailto:` link (URL-encode subject and body), and say that nothing was saved to Gmail.

Log each one: `cli.py track add --company "..." --person "..." --email "..." --email-source-url "..." --job-title "..." --job-url "..." --score 0.52 --status drafted --draft-id "<id or empty>"`.

## Step 5: follow-ups (every run)

1. The user marks drafts they actually sent: `cli.py track set --email <email> --status sent` (ask them, or detect it: a Sent message to that address → set `sent`).
2. `cli.py track followups` lists contacts with status `sent`, no reply, and 5+ days since the draft date.
   For each, check Gmail for a reply first. No reply → draft **one** follow-up in the same thread if the connector supports replies as drafts
   (otherwise a new draft with `Re: <subject>`): 2–3 sentences, add something new (a small update, a demo link), same single ask.
   Then `cli.py track set --email <email> --status followup_drafted`. Never a second follow-up.

## Step 6: report

End with a short summary: sources checked (with status), jobs found, matches, drafts created (company, role, score, contact source),
skipped (already emailed / no contact / agency), follow-ups drafted, and "Nothing was sent. Review the drafts in Gmail."
Optional: offer the daily schedule in `references/schedule.md`.

## Commands at a glance

| Command | What it does |
|---|---|
| `cli.py profile init --cv FILE` | CV text → sections → weighted terms |
| `cli.py profile set ...` / `profile show` | roles, cities, level, project, signature, watched feeds |
| `cli.py find` | free sources → `~/.cold-email/runs/<date>/jobs.json` |
| `cli.py linkedin --url --title --snippet` | add one LinkedIn search hit (date check + snippet emails) |
| `cli.py contacts --site URL [--job ID]` | Impressum / contact / team pages → emails + managing directors, each with its URL |
| `cli.py shortlist [--limit N]` | ranked matches with best sourced contact |
| `cli.py lint -` | checks a draft body against the guide |
| `cli.py track add/set/list/followups` | the tracker (`~/.cold-email/tracker.csv`) |
| `python3 scripts/selftest.py` | which pieces work on this machine |
