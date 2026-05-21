from typing import AsyncGenerator

from loguru import logger

from config.settings import settings
from src.scrapers.base_scraper import BaseScraper

_INDEED_URL = (
    "https://www.indeed.com/jobs?q={query}&l=Remote&fromage=3&sort=date"
)


class IndeedScraper(BaseScraper):
    """
    Secondary scraper for Indeed.com.

    Indeed has lighter anti-bot measures than LinkedIn and does not
    require authenticated sessions for public job listings.
    No storageState injection needed.
    """

    async def scrape(self) -> AsyncGenerator[dict, None]:
        page = await self._new_page()

        for role in settings.target_roles:
            url = _INDEED_URL.format(query=role.replace(" ", "+"))
            logger.info(f"Scraping Indeed: {role}")
            await page.goto(url, wait_until="networkidle")
            await self._human_delay()

            cards = await page.query_selector_all(".job_seen_beacon")
            logger.info(f"Found {len(cards)} cards")

            for card in cards:
                try:
                    yield await self._extract_card(page, card)
                    await self._human_delay()
                except Exception as exc:
                    logger.warning(f"Card extraction failed: {exc}")
                    continue

        await page.close()

    async def _extract_card(self, page, card) -> dict:
        title_el = await card.query_selector("[data-testid='jobTitle']")
        company_el = await card.query_selector("[data-testid='company-name']")
        location_el = await card.query_selector("[data-testid='text-location']")
        link_el = await card.query_selector("a[id^='job_']")

        href = await link_el.get_attribute("href") if link_el else ""
        url = f"https://www.indeed.com{href}" if href and not href.startswith("http") else href

        await card.click()
        await self._human_delay()

        jd_text = ""
        try:
            jd_el = await page.wait_for_selector(
                "#jobDescriptionText", timeout=5000
            )
            jd_text = await jd_el.inner_text() if jd_el else ""
        except Exception:
            pass

        return {
            "url": url,
            "title": await title_el.inner_text() if title_el else "",
            "company": await company_el.inner_text() if company_el else "",
            "location": await location_el.inner_text() if location_el else "",
            "jd_text": jd_text,
            "source": "indeed",
        }
