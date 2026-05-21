.PHONY: install setup-db capture-session pipeline scrape find-managers outreach apply status clean docker-run

install:
	pip install -r requirements.txt
	playwright install chromium

setup-db:
	python -c "from src.database.db_manager import init_db; init_db()"

# Captures your LinkedIn session from your personal browser.
# Run once, then session_state.json is reused for all scraping.
capture-session:
	python scripts/capture_session.py

# Full pipeline — scrape → find managers → outreach → report
pipeline:
	python main.py pipeline

# Run only specific stages
scrape:
	python main.py scrape

find-managers:
	python main.py pipeline --skip-scrape --skip-outreach

outreach:
	python main.py outreach

# Pipeline without scraping (managers + outreach only)
pipeline-fast:
	python main.py pipeline --skip-scrape

analyze:
	python main.py analyze

apply:
	python main.py apply

status:
	python main.py status

# Run headless in Docker
docker-run:
	docker compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true
