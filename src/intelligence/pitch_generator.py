import json
from pathlib import Path

from loguru import logger

from config.prompts import PITCH_GENERATION_PROMPT, CONNECTION_NOTE_PROMPT
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


def generate_connection_note(
    *,
    company_name: str,
    job_title: str,
    manager_name: str,
    matched_skills: list[str],
    growth_signals: list[str],
) -> str:
    """
    Generate a LinkedIn connection request note — max 280 chars.
    Peer-to-peer tone, no ask, ends with 'Thought it was worth connecting directly.'
    """
    cv = _load_cv()
    first_name = manager_name.split()[0]

    cv_summary = (
        f"Recent project: {cv.get('projects', [{}])[0].get('market_name', '')} — "
        f"{cv.get('projects', [{}])[0].get('impact', '')}. "
        f"Stack: {', '.join(cv.get('skills', {}).get('cloud', [])[:4])}."
    )

    prompt = CONNECTION_NOTE_PROMPT.format(
        candidate_name=cv.get("name", ""),
        manager_first_name=first_name,
        company_name=company_name,
        job_title=job_title,
        growth_signals=", ".join(growth_signals) if growth_signals else "N/A",
        matched_skills=", ".join(matched_skills[:4]),
        cv_summary=cv_summary,
    )

    note = llm.complete(prompt, json_mode=False).strip()

    # Hard cap — LinkedIn rejects notes over 300 chars
    if len(note) > 295:
        note = note[:292] + "..."

    logger.info(f"Connection note generated for {manager_name} at {company_name} ({len(note)} chars)")
    return note
