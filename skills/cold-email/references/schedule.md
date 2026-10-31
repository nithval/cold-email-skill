# Run it every day (optional)

The run only creates drafts, so it is safe to schedule: you review in Gmail whenever you like.

## Claude Desktop / claude.ai (scheduled task)
Create a scheduled task, daily at 08:00, with the prompt:

> Run /cold-email for today: find new matching jobs, draft up to 5 cold emails as Gmail drafts, draft follow-ups that are due, and give me the summary. Never send anything.

## Claude Code (routine or cron)
Inside Claude Code: `/schedule` → daily 08:00 → same prompt.

Or with cron on your own machine (the Gmail connector must be available to headless Claude Code):

```
0 8 * * 1-5  cd ~ && claude -p "Run /cold-email for today. Drafts only, never send. Max 5 drafts." >> ~/.cold-email/cron.log 2>&1
```

## Keep it small
5–10 drafts a day is plenty. More than that stops being personal, and it is what spam filters and GDPR complaints look for.
