from typing import AsyncGenerator

from loguru import logger

from config.settings import settings
from src.scrapers.base_scraper import BaseScraper

_LINKEDIN_JOBS_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={query}&location={location}&f_WT=2&f_TPR=r86400"
)


class LinkedInScraper(BaseScraper):
    """
    Scrapes LinkedIn job listings using an authenticated session.

    Requires a valid session_state.json captured from your personal browser.
    See `make capture-session` in the Makefile.

    Anti-ban measures applied:
    - Randomized delays between page loads
    - Limits page traversal to avoid burst patterns
    - Uses injected cookies (not bot-originated login)
    """

    async def scrape(self) -> AsyncGenerator[dict, None]:
        page = await self._new_page()
        for role in settings.target_roles:
            for location in settings.target_locations:
                url = _LINKEDIN_JOBS_URL.format(
                    query=role.replace(" ", "%20"),
                    location=location.replace(" ", "%20"),
                )
                logger.info(f"Scraping LinkedIn: {role} in {location}")
                await page.goto(url, wait_until="networkidle")
                await self._human_delay()

                job_cards = await page.query_selector_all(".job-card-container")
                logger.info(f"Found {len(job_cards)} cards")

                for card in job_cards:
                    try:
                        yield await self._extract_card(page, card)
                        await self._human_delay()
                    except Exception as exc:
                        logger.warning(f"Card extraction failed: {exc}")
                        continue

        await page.close()

    async def _extract_card(self, page, card) -> dict:
        link_el = await card.query_selector("a.job-card-container__link")
        title_el = await card.query_selector(".job-card-list__title")
        company_el = await card.query_selector(".job-card-container__primary-description")
        location_el = await card.query_selector(".job-card-container__metadata-item")

        url = await link_el.get_attribute("href") if link_el else ""
        if url and not url.startswith("http"):
            url = f"https://www.linkedin.com{url}"

        await card.click()
        await self._human_delay()

        jd_text = ""
        try:
            jd_el = await page.wait_for_selector(
                ".jobs-description__content", timeout=5000
            )
            jd_text = await jd_el.inner_text() if jd_el else ""
        except Exception:
            pass

        return {
            "url": url.split("?")[0] if url else "",
            "title": await title_el.inner_text() if title_el else "",
            "company": await company_el.inner_text() if company_el else "",
            "location": await location_el.inner_text() if location_el else "",
            "jd_text": jd_text,
            "source": "linkedin",
        }
