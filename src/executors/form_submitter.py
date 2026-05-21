import json
from pathlib import Path

from loguru import logger

from config.prompts import FORM_FIELD_MAPPING_PROMPT
from config.settings import settings
from src.intelligence.llm_client import llm
from src.scrapers.base_scraper import BaseScraper


class FormSubmitter(BaseScraper):
    """
    Auto-fills and submits job application forms via Playwright.

    Phase 2 feature — stub ready for implementation after outreach_bot is validated.
    The LLM maps master_cv.json fields to detected form inputs before submission.
    """

    async def scrape(self):
        raise NotImplementedError

    async def submit(self, job_url: str) -> bool:
        page = await self._new_page()
        try:
            await page.goto(job_url, wait_until="networkidle")
            await self._human_delay()

            fields = await self._detect_form_fields(page)
            if not fields:
                logger.warning(f"No form fields detected at {job_url}")
                return False

            cv = json.loads(Path(settings.cv_json_path).read_text())
            prompt = FORM_FIELD_MAPPING_PROMPT.format(
                candidate_name=cv.get("name", ""),
                cv_json=json.dumps(cv, ensure_ascii=False),
                form_fields=json.dumps(fields, ensure_ascii=False),
            )
            mapping: dict = llm.complete(prompt, json_mode=True)

            await self._fill_form(page, mapping)
            logger.info(f"Form filled for {job_url} — awaiting human review before submit.")
            # Intentional: do NOT auto-submit. Human reviews before final click.
            return True

        except Exception as exc:
            logger.error(f"Form submission failed for {job_url}: {exc}")
            return False
        finally:
            await page.close()

    async def _detect_form_fields(self, page) -> list[dict]:
        inputs = await page.query_selector_all("input, textarea, select")
        fields = []
        for el in inputs:
            label = await el.get_attribute("aria-label") or await el.get_attribute("name") or ""
            field_id = await el.get_attribute("id") or ""
            field_type = await el.get_attribute("type") or "text"
            if label or field_id:
                fields.append({"id": field_id, "label": label, "type": field_type})
        return fields

    async def _fill_form(self, page, mapping: dict) -> None:
        for field_id_or_label, value in mapping.items():
            if value is None:
                continue
            selector = f"#{field_id_or_label}" if field_id_or_label.isidentifier() \
                else f"[aria-label='{field_id_or_label}']"
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.fill(str(value))
                    await self._human_delay()
            except Exception as exc:
                logger.debug(f"Could not fill field '{field_id_or_label}': {exc}")
