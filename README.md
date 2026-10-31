# /cold-email: a free Claude skill that finds jobs and drafts cold emails for you

Give it your CV once. Every run it:

1. **finds fresh openings** from free sources only: Arbeitnow, the Bundesagentur für Arbeit job search, Hacker News "Who is hiring?",
   public Greenhouse / Lever / Ashby / Personio job feeds, and public LinkedIn hiring posts found through web search,
2. **keeps the ones that match your CV** (keyword match, weighted by where your CV shows the skill: experience 1.0, projects 0.75, skills 0.5),
3. **finds a real contact email** in the job ad, the post, or the company's Impressum / contact / team page, and **stores the URL it came from**,
4. **writes a short, personal cold email** (under 120 words, one real line about them, one project + link, one clear ask),
5. **saves it as a Gmail draft**. You read it, edit it, and press send yourself.

It also skips people you already emailed, notices replies, drafts **one** follow-up after 5 days of silence, and logs everything to a CSV tracker.

**It never sends anything.** Drafts only.

The email style comes from real cold emails that got founders, CTOs and a Head of Innovation to reply during a job hunt in Germany
(`skills/cold-email/references/style.md`).

---

## Install

You need a **paid Claude plan** (Pro or above) with **Gmail connected** (the connector must be allowed to create drafts).

**Claude Desktop / claude.ai**
Customize → Plugins → Add marketplace from repository → `nithval/cold-email-skill` → install **cold-email**.

**Claude Code**
```
/plugin marketplace add nithval/cold-email-skill
/plugin install cold-email@cold-email
```

**Any agent that supports skills**
```
npx skills add nithval/cold-email-skill
```

Then say: **"/cold-email"** (or "find jobs and draft cold emails"). The first run asks for your CV, target roles, cities, level,
and the one project you want to lead with.

Check your setup any time:
```
python3 skills/cold-email/scripts/selftest.py
```

## What it needs (honest list)

| Piece | Needed? | Notes |
|---|---|---|
| Claude paid plan | yes | skills + connectors |
| Gmail connector with draft access | for drafts | without it you get copy-ready emails + `mailto:` links |
| Python 3.9+ | yes | standard library only, nothing to `pip install` |
| `pdftotext` (poppler) | optional | for PDF CVs; otherwise Claude reads the PDF |
| Web search tool | for LinkedIn posts | job APIs work without it |
| API keys / paid scrapers | **no** | every source is free and public |

## Sources (all free)

- **Arbeitnow** job board API (Germany-focused, English jobs)
- **Bundesagentur für Arbeit** Jobsuche API + the public job page (full ad text, often with a contact email)
- **Hacker News "Who is hiring?"** via the Algolia API (filtered to your cities)
- **Greenhouse / Lever / Ashby / Personio** public job feeds for companies you add to your watch list
- **LinkedIn hiring posts**: found with normal web search (`site:linkedin.com/posts "hiring" "send your CV" <city> <role>`).
  Only the search result (URL + snippet) is used. It never logs in to LinkedIn and never opens LinkedIn pages.
  Post dates come from the post URL (the activity id is a timestamp); posts older than 30 days are dropped.

## Rules it follows

- **Drafts only, never sends.**
- **Every email address has a source URL** (shown to you and saved in the tracker). It never guesses an address or an email pattern.
  No sourced address → "no contact found", skipped.
- **The personal line must be true** and come from a page it read.
- **~10 drafts per run at most.** Skips recruiting agencies and anyone already emailed.

## Privacy and GDPR

This is a tool for **one person writing a few personal emails to companies about real job openings**, not for bulk mail.
- It only uses business contact details that companies publish themselves (job ads, Impressum, contact and team pages, public posts).
- Keep it low volume (5–10 a day) and personal. Each email is about a specific opening and easy to say no to.
- If someone asks you not to contact them again, mark them `closed` in the tracker and don't.
- Your CV, profile and tracker stay on your machine in `~/.cold-email/`. Nothing is uploaded anywhere except what your Claude
  session and Gmail already see.

## Files

```
.claude-plugin/          plugin + marketplace manifests
skills/cold-email/
  SKILL.md               the workflow Claude follows
  references/style.md    how the emails are written
  references/schedule.md how to run it daily
  scripts/cli.py         profile, find, linkedin, contacts, shortlist, lint, track
  scripts/coldmail.py    parsers + scoring (no network)
  scripts/sources.py     free job sources + Impressum crawler
  scripts/selftest.py    which pieces work on your machine
tests/                   parser evals (python3 -m unittest discover -s tests)
```

## Run it every day

See `skills/cold-email/references/schedule.md` (Claude scheduled task, Claude Code routine, or cron). It only creates drafts,
so you review them whenever you like.

---

If this helped you land a job, buy me a coffee ☕ (link coming soon)<!-- DONATION_LINK -->
Or pay it forward: help the next person with their first cold email.

Made by [@compiling.me_](https://www.instagram.com/compiling.me_/) · MIT licence
