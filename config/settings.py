from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    default_llm_provider: str = "gemini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"

    # ── Paths ─────────────────────────────────────────────────
    db_path: Path = BASE_DIR / "data" / "jobs.db"
    cv_json_path: Path = BASE_DIR / "data" / "master_cv.json"
    playwright_state_path: Path = BASE_DIR / "data" / "session_state.json"
    browser_profile_path: Path = BASE_DIR / "data" / "browser_profile"
    scraper_profile_path: Path = BASE_DIR / "data" / "scraper_profile"

    # ── Scraping safety limits ────────────────────────────────
    max_daily_connections: int = 20
    max_daily_messages: int = 20
    scrape_delay_min: int = 3
    scrape_delay_max: int = 8

    # ── Qualification filter ──────────────────────────────────
    min_fit_score: float = 0.65
    salary_min_usd_month: int = 7000

    # ── Target roles for search queries ──────────────────────
    # Reordenado 2026-08-06: DevOps/Cloud/SRE primero (Tier A — fit directo,
    # track record pagado real). AI Infra/MLOps queda como cola secundaria
    # (Tier B — diferenciador, no la afirmación central) tras diagnóstico de
    # mercado: roles "AI Infra/MLOps" puros filtran por production track
    # record empleador-validado que el CV no sostiene todavía.
    target_roles: list[str] = [
        "Senior DevOps Engineer",
        "Cloud Infrastructure Engineer",
        "Site Reliability Engineer",
        "Platform Engineer",
        "Senior Cloud Engineer",
        "AI Infrastructure Engineer",
        "MLOps Engineer",
    ]
    target_locations: list[str] = ["Remote", "United States", "Europe"]

    @field_validator("default_llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"gemini", "anthropic", "ollama", "bedrock"}
        if v not in allowed:
            raise ValueError(f"default_llm_provider must be one of {allowed}")
        return v

    @field_validator("min_fit_score")
    @classmethod
    def validate_fit_score(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("min_fit_score must be between 0.0 and 1.0")
        return v


settings = Settings()
