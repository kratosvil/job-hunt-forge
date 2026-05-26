import json
from pathlib import Path

from loguru import logger

from config.prompts import (
    PITCH_GENERATION_PROMPT,
    CONNECTION_NOTE_TECHNICAL_PROMPT,
    CONNECTION_NOTE_RECRUITER_PROMPT,
)
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


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Cut at the last complete sentence within max_chars."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for punct in (". ", "! ", "? "):
        last = truncated.rfind(punct)
        if last != -1:
            return truncated[:last + 1].strip()
    return truncated.rsplit(" ", 1)[0].strip()


def _cv_summary(cv: dict) -> str:
    projects = cv.get("projects", [])
    top = projects[0] if projects else {}
    cloud = cv.get("skills", {}).get("cloud", [])
    return (
        f"Recent project: {top.get('market_name', '')} — {top.get('impact', '')}. "
        f"Stack: {', '.join(cloud[:4])}."
    )


def generate_connection_note(
    *,
    company_name: str,
    job_title: str,
    manager_name: str,
    matched_skills: list[str],
    growth_signals: list[str],
    note_type: str = "technical",
) -> str:
    """
    Generate a LinkedIn connection request note — max 270 chars.

    note_type: "technical" (VP/CTO/Director) | "recruiter" (talent/HR)
    """
    cv = _load_cv()
    first_name = manager_name.split()[0]

    if note_type == "recruiter":
        prompt = CONNECTION_NOTE_RECRUITER_PROMPT.format(
            candidate_name=cv.get("name", ""),
            manager_first_name=first_name,
            company_name=company_name,
            job_title=job_title,
            matched_skills=", ".join(matched_skills[:4]),
        )
    else:
        prompt = CONNECTION_NOTE_TECHNICAL_PROMPT.format(
            candidate_name=cv.get("name", ""),
            manager_first_name=first_name,
            company_name=company_name,
            job_title=job_title,
            growth_signals=", ".join(growth_signals) if growth_signals else "N/A",
            matched_skills=", ".join(matched_skills[:4]),
            cv_summary=_cv_summary(cv),
        )

    note = llm.complete(prompt, json_mode=False).strip()

    # LinkedIn limit is 200 chars; use 198 to avoid off-by-one with trailing punctuation.
    MAX_NOTE = 198
    if note_type == "technical":
        # Closing is appended in code — reliable regardless of LLM output
        closing = " Thought it was worth connecting directly."
        body_limit = MAX_NOTE - len(closing)
        body = _truncate_at_sentence(note, body_limit)
        # Strip any LLM-generated closing attempt to avoid duplication
        for phrase in ("Thought it was worth", "thought it was worth"):
            idx = body.find(phrase)
            if idx != -1:
                body = body[:idx].strip().rstrip(".")
        note = body + closing
    else:
        note = _truncate_at_sentence(note, MAX_NOTE)

    logger.info(
        f"Connection note ({note_type}) for {manager_name} @ {company_name} "
        f"— {len(note)} chars"
    )
    return note
