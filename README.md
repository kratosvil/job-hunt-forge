# Job-Hunt-Forge

AI-powered job search automation suite — scraping, intelligent scoring, and direct outreach to hiring managers.

## What it does

1. **Scrapes** job listings from LinkedIn and Indeed for target roles
2. **Scores** each listing against your CV using an LLM (fit score 0–1)
3. **Generates** personalized outreach messages for hiring managers — bypassing ATS and generic recruiters
4. **Queues** form auto-fill for direct applications (Phase 2)

The system is designed to run daily in the background, feeding qualified opportunities into SQLite and dispatching outreach within LinkedIn's safe usage limits.

## Architecture

```
job-hunt-forge/
├── config/
│   ├── settings.py          # Pydantic Settings — all config via .env
│   └── prompts.py           # LLM prompt templates
├── src/
│   ├── database/
│   │   ├── db_manager.py    # SQLite engine + session context manager
│   │   └── models.py        # SQLAlchemy models: Job, HiringManager
│   ├── scrapers/
│   │   ├── base_scraper.py  # Abstract base with Playwright + rate limiting
│   │   ├── linkedin_scraper.py
│   │   └── indeed_scraper.py
│   ├── intelligence/
│   │   ├── llm_client.py    # Gemini / Anthropic unified client
│   │   ├── jd_analyzer.py   # JD vs CV fit scoring
│   │   └── pitch_generator.py
│   └── executors/
│       ├── outreach_bot.py  # LinkedIn direct messaging with daily limits
│       └── form_submitter.py
├── data/
│   ├── master_cv.example.json  # Schema — copy to master_cv.json and fill
│   └── jobs.db                 # Auto-created on first run
├── scripts/
│   └── capture_session.py   # One-time LinkedIn session capture
├── main.py                  # CLI entry point (Typer)
└── Makefile
```

## Setup

**1. Clone and install**
```bash
git clone https://github.com/kratosvil/job-hunt-forge.git
cd job-hunt-forge
make install
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env with your API keys and search preferences
```

**3. Configure your CV**
```bash
cp data/master_cv.example.json data/master_cv.json
# Fill master_cv.json with your real data
# This file is in .gitignore — never committed
```

**4. Capture LinkedIn session (one time)**
```bash
make capture-session
# A browser window opens — log in manually — press ENTER when done
```

**5. Initialize database**
```bash
make setup-db
```

## Usage

```bash
# Scrape LinkedIn jobs, score them, store results
make scrape

# Send outreach messages to queued hiring managers
make outreach

# Check current pipeline status
make status
```

## Data privacy

All personal data stays local:

| File | Contains | In .gitignore |
|------|----------|---------------|
| `data/master_cv.json` | Your full CV data | Yes |
| `data/session_state.json` | LinkedIn session cookies | Yes |
| `data/jobs.db` | Job pipeline data | Yes |
| `.env` | API keys | Yes |

Only the code is committed. Your data never leaves your machine.

## Anti-ban design

- **Session injection** — uses cookies from your real browser login, not automated login
- **Rate limiting** — configurable daily caps on connections and messages (default: 15/20)
- **Human delays** — randomized 3–8s pauses between all page interactions
- **No cloud infrastructure** — runs from your machine, same IP as your browser

## Stack

- Python 3.11+ · Playwright · SQLAlchemy · Pydantic Settings
- Google Gemini API / Anthropic Claude API
- SQLite · Docker (optional for headless runs)

## License

MIT
