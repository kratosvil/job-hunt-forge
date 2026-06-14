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

# Captures your LinkedIn session from your personal browser (main account — outreach).
# Run once, then session is reused by: make connect
capture-session:
	DISPLAY=:0 $(PYTHON) scripts/capture_session.py

# Captures the session for the dedicated scraper account (secondary account — job search only).
# Run once, then session is reused by: make scrape, make easy-apply
capture-scraper-session:
	DISPLAY=:0 $(PYTHON) scripts/capture_scraper_session.py

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
# PAUSADO — riesgo de ban LinkedIn por visitas masivas a perfiles. Reactivar cuando sea seguro.
find-managers-batch:
	@echo "PAUSADO: find-managers-batch deshabilitado por riesgo de ban LinkedIn."
	@echo "Usa 'make easy-apply' como alternativa. Ver README para reactivar."
	@exit 1

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

# Easy Apply AI/MLOps — España 50% / USA 25% / Colombia 25% / Mundo buffer → Excel en Drive
easy-apply:
	DISPLAY=:0 $(PYTHON) main.py easy-apply \
		--spain 15 --usa 8 --colombia 7 --world 5 \
		--min-display-fit 0.90 \
		--excel "/home/kratosvil/Desarrollo/gdrive/proyectos/JOB-HUNT-FORGE/easy_apply_ai_$$(date +%Y-%m-%d).xlsx"

# Easy Apply DevOps/Cloud/SRE — mismas cuotas regionales → Excel en Drive
easy-apply-devops:
	DISPLAY=:0 $(PYTHON) main.py easy-apply \
		--spain 15 --usa 8 --colombia 7 --world 5 \
		--min-display-fit 0.90 \
		--roles "Senior DevOps Engineer,DevOps Engineer,Cloud Engineer,Site Reliability Engineer,Infrastructure Engineer,Cloud Infrastructure Engineer" \
		--output data/easy_apply_devops.txt \
		--excel "/home/kratosvil/Desarrollo/gdrive/proyectos/JOB-HUNT-FORGE/easy_apply_devops_$$(date +%Y-%m-%d).xlsx"

# Top 15 best-fit sin Easy Apply — España primero, con mensaje reclutador → Excel en Drive
top-jobs:
	$(PYTHON) main.py top-jobs --top 15 --min-fit 0.80 --country Spain \
		--excel "/home/kratosvil/Desarrollo/gdrive/proyectos/JOB-HUNT-FORGE/top_jobs_$$(date +%Y-%m-%d).xlsx"

# Buscar reclutadores tech (DevOps/MLOps/Cloud) → Excel en Drive con mensajes listos
find-recruiters:
	DISPLAY=:0 $(PYTHON) main.py find-recruiters --max-per-query 8 \
		--excel "/home/kratosvil/Desarrollo/gdrive/proyectos/JOB-HUNT-FORGE/recruiters_$$(date +%Y-%m-%d).xlsx"

# Rutina diaria completa
daily-hunt:
	@echo "=== Iniciando rutina diaria Job Hunt ==="
	DISPLAY=:0 $(MAKE) easy-apply
	DISPLAY=:0 $(MAKE) easy-apply-devops
	$(MAKE) top-jobs
	@echo "=== Excels generados en Drive ==="

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
