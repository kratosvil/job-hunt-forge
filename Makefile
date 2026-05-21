.PHONY: install setup-db capture-session scrape analyze outreach apply status clean

install:
	pip install -r requirements.txt
	playwright install chromium

setup-db:
	python -c "from src.database.db_manager import init_db; init_db()"

# Captures your LinkedIn session from your personal browser.
# Run once, then session_state.json is reused for all scraping.
capture-session:
	python scripts/capture_session.py

scrape:
	python main.py scrape

analyze:
	python main.py analyze

outreach:
	python main.py outreach

apply:
	python main.py apply

status:
	python main.py status

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true
