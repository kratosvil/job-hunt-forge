import json
from pathlib import Path

from loguru import logger

from config.prompts import PITCH_GENERATION_PROMPT
from config.settings import settings
from src.intelligence.llm_client import llm


def _load_cv() -> dict:
    path: Path = settings.cv_json_path
    if not path.exists():
        raise FileNotFoundError(f"master_cv.json not found at {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


def generate_pitch(
    *,
    company_name: str,
    job_title: str,
    manager_name: str,
    manager_title: str,
    matched_skills: list[str],
    growth_signals: list[str],
) -> str:
    """
    Generate a personalized outreach message for a specific hiring manager.

    Each call produces a unique message — the LLM uses growth_signals
    and matched_skills to make the message company-specific, not templated.
    """
    cv = _load_cv()
    prompt = PITCH_GENERATION_PROMPT.format(
        candidate_name=cv.get("name", ""),
        company_name=company_name,
        cv_json=json.dumps(cv, ensure_ascii=False),
        job_title=job_title,
        growth_signals=", ".join(growth_signals) if growth_signals else "N/A",
        matched_skills=", ".join(matched_skills[:5]),
        manager_name=manager_name,
        manager_title=manager_title,
    )
    pitch = llm.complete(prompt, json_mode=False)
    logger.info(f"Pitch generated for {manager_name} at {company_name}")
    return pitch.strip()
