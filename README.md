# Job-Hunt-Forge

AI-powered job search automation suite — LinkedIn scraping, LLM-based CV scoring, hiring manager discovery, and direct peer-to-peer outreach that bypasses ATS.

## What it does

1. **Scrapes** LinkedIn job listings for target roles using a real persistent Chrome browser profile
2. **Scores** each listing against your CV with an LLM (AWS Bedrock — Claude Haiku) — fit score 0–1
3. **Finds** hiring managers (recruiters + engineering managers) on LinkedIn for qualified jobs
4. **Connects** to those managers with personalized, role-aware connection requests — no ATS involved

The system runs daily on your local machine, staying within LinkedIn's safe usage limits to protect your account.

## Architecture

```
job-hunt-forge/
├── config/
│   ├── settings.py              # Pydantic Settings — all tuneable via .env
│   └── prompts.py               # LLM prompt templates (scoring + outreach notes)
├── src/
│   ├── database/
│   │   ├── db_manager.py        # SQLite engine + session context manager
│   │   └── models.py            # SQLAlchemy models: Job, HiringManager
│   ├── scrapers/
│   │   ├── base_scraper.py      # Playwright base — persistent Chrome profile, anti-bot delays
│   │   ├── linkedin_scraper.py  # LinkedIn job listing scraper (guest frontend)
│   │   ├── indeed_scraper.py    # Indeed scraper (optional)
│   │   └── manager_finder.py    # LinkedIn people search — finds managers for qualified jobs
│   ├── intelligence/
│   │   ├── llm_client.py        # AWS Bedrock unified client
│   │   ├── jd_analyzer.py       # JD vs CV fit scoring via LLM
│   │   └── pitch_generator.py   # Personalized connection note generator (≤198 chars)
│   ├── executors/
│   │   └── outreach_bot.py      # LinkedIn connection requests — daily limits, role filtering
│   └── pipeline.py              # Full pipeline orchestration with stage flags
├── scripts/
│   ├── capture_session.py       # One-time LinkedIn session capture (legacy helper)
│   └── test_outreach_single.py  # E2E test for a single manager by DB id
├── data/
│   ├── master_cv.example.json   # CV schema — copy to master_cv.json and fill in
│   └── jobs.db                  # Auto-created on first run (gitignored)
├── main.py                      # CLI entry point (Typer + Rich)
└── Makefile                     # Shorthand for all common operations
```

## Setup

**1. Clone and create the virtualenv**
```bash
git clone https://github.com/kratosvil/job-hunt-forge.git
cd job-hunt-forge
make install
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env — set BEDROCK_REGION and confirm the model ID
# AWS credentials come from ~/.aws/credentials (no key in .env needed)
```

**3. Configure your CV**
```bash
cp data/master_cv.example.json data/master_cv.json
# Fill master_cv.json with your real CV data
# This file is gitignored — never committed
```

**4. Log in to LinkedIn (one time)**
```bash
# Open the persistent Chrome profile manually and log in:
google-chrome --user-data-dir=$(pwd)/data/browser_profile
# Log in to LinkedIn, then close Chrome.
# All subsequent runs reuse this authenticated profile automatically.
```

**5. Initialize database**
```bash
make setup-db
```

## Daily routine

```bash
# Remove stale Chrome lock if present (e.g. after a crash)
rm -f data/browser_profile/SingletonLock

# Scrape up to 20 fresh job listings and score them
make scrape

# Find hiring managers for qualified jobs (run 2–3x to cover the queue)
make find-managers-batch

# Send up to 20 connection requests to recruiters and engineering managers
DISPLAY=:0 make connect
```

`make connect` requires a display (headful Chrome). On a headless server, set up a virtual display with `Xvfb`.

## Pipeline flags

```bash
# Full pipeline in one command
make pipeline

# Skip scraping (use existing DB jobs)
make pipeline-fast

# Only find managers — no scrape, no outreach
make find-managers-batch          # 10 jobs per run
make find-managers                # all qualified jobs at once

# Check pipeline stats
make status
```

## Manager classification

The outreach bot classifies each discovered manager and only contacts:

| Class | Targets | Examples |
|-------|---------|---------|
| `recruiter` | Actively own the hiring funnel | Recruiter, Talent Acquisition, Head of Recruiting, HR |
| `technical` | Direct hiring authority over the role | Engineering Manager, Director of Engineering, Head of AI, Team Lead, Architect |
| `skip` | Too senior or irrelevant | CTO, CEO, VP, SVP, Founder, Peer engineers, PM, QA |

Hard-skip (C-suite) always overrides even if a positive keyword also matches.
Positive keywords (recruiter / technical) override soft-skip (peer-level engineers).

## Anti-ban design

- **Persistent profile** — uses a real Chrome binary with your saved LinkedIn session, not automated login
- **Human delays** — randomized 3–8s pauses between every page interaction
- **Daily caps** — 20 connection requests/day maximum (configurable in `.env`)
- **Recency filter** — only processes managers found in the last 48h (fresh outreach queue)
- **Deduplication** — duplicate managers across jobs are skipped at discovery time

## Connection notes

Notes are personalized per manager type using AWS Bedrock (Claude Haiku):
- **Recruiter note**: role fit, matched skills, availability
- **Technical note**: specific stack overlap, project relevance

Note length is capped at **198 characters** (LinkedIn limit: 200, with 2-char safety margin).

> LinkedIn Premium is required to attach notes on connection requests to Creator Mode profiles.
> Without Premium, requests are sent without a note. To re-enable notes once Premium is active,
> change `if False and add_note_btn:` → `if add_note_btn:` in `outreach_bot.py`.

## Data privacy

All personal data is local only:

| File | Contains | Gitignored |
|------|----------|-----------|
| `data/master_cv.json` | Your full CV data | Yes |
| `data/jobs.db` | Scraped jobs and manager pipeline | Yes |
| `data/browser_profile/` | Chrome persistent profile with LinkedIn session | Yes |
| `data/session_state.json` | Legacy Playwright session export | Yes |
| `.env` | Runtime configuration | Yes |

Only source code is committed. Your CV, credentials, and browsing session never leave your machine.

## Stack

- **Python 3.10+** · Playwright (persistent Chrome) · SQLAlchemy · Pydantic Settings · Typer · Rich
- **AWS Bedrock** — `us.anthropic.claude-haiku-4-5-20251001-v1:0` — scoring + note generation
- **SQLite** — local job and manager pipeline database

## License

MIT
