VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: install setup-db capture-session pipeline scrape find-managers outreach apply status clean docker-run

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install chromium

setup-db:
	$(PYTHON) -c "from src.database.db_manager import init_db; init_db()"

# Captures your LinkedIn session from your personal browser.
# Run once, then session_state.json is reused for all scraping.
capture-session:
	$(PYTHON) scripts/capture_session.py

# Full pipeline — scrape → find managers → outreach → report
pipeline:
	$(PYTHON) main.py pipeline

# Run only specific stages
# Max 20 nuevos jobs por día — evita gasto excesivo en Bedrock
scrape:
	$(PYTHON) main.py scrape --limit 20

find-managers:
	$(PYTHON) main.py pipeline --skip-scrape --skip-outreach

# Safe test run — only 3 jobs, no scrape, no outreach
find-managers-test:
	$(PYTHON) main.py pipeline --skip-scrape --skip-outreach --managers-limit 3

# Standard run — 10 jobs per batch, covers 36 recommended in ~4 runs
find-managers-batch:
	$(PYTHON) main.py pipeline --skip-scrape --skip-outreach --managers-limit 10

# Send connection requests (max 20/day, decision-makers only — requires DISPLAY=:0)
connect:
	$(PYTHON) main.py outreach

outreach:
	$(PYTHON) main.py outreach

# Pipeline without scraping (managers + outreach only)
pipeline-fast:
	$(PYTHON) main.py pipeline --skip-scrape

analyze:
	$(PYTHON) main.py analyze

# Scan LinkedIn Easy Apply jobs — outputs qualifying links to data/easy_apply.txt
easy-apply:
	$(PYTHON) main.py easy-apply --limit 30

apply:
	$(PYTHON) main.py apply

status:
	$(PYTHON) main.py status

# Run headless in Docker
docker-run:
	docker compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true
