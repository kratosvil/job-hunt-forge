import json
from pathlib import Path

from loguru import logger

from config.prompts import JD_ANALYSIS_PROMPT
from config.settings import settings
from src.intelligence.llm_client import llm


def _load_cv() -> dict:
    path: Path = settings.cv_json_path
    if not path.exists():
        raise FileNotFoundError(
            f"master_cv.json not found at {path}. "
            "Copy data/master_cv.example.json → data/master_cv.json and fill your data."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(jd_text: str) -> dict:
    """
    Score a job description against the candidate's CV.

    Returns the raw analysis dict from the LLM including fit_score,
    matched/missing skills, and application_recommended flag.
    """
    cv = _load_cv()
    prompt = JD_ANALYSIS_PROMPT.format(
        cv_json=json.dumps(cv, ensure_ascii=False),
        jd_text=jd_text,
    )
    result = llm.complete(prompt, json_mode=True)
    logger.info(
        f"JD analyzed — fit_score={result.get('fit_score')}, "
        f"recommended={result.get('application_recommended')}"
    )
    return result
