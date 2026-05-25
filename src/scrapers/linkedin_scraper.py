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
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self._human_delay()

                # Guest frontend uses div.job-search-card; authenticated uses .job-card-container
                job_cards = await page.query_selector_all("div.job-search-card, .job-card-container")
                logger.info(f"Found {len(job_cards)} cards")

                # Extract URLs first before the DOM refreshes on hover/click
                card_urls = []
                for card in job_cards:
                    try:
                        link_el = await card.query_selector(
                            "a.base-card__full-link, a.job-card-container__link"
                        )
                        href = await link_el.get_attribute("href") if link_el else ""
                        if href and not href.startswith("http"):
                            href = f"https://www.linkedin.com{href}"
                        card_urls.append(href.split("?")[0] if href else "")
                    except Exception:
                        card_urls.append("")

                for card_url in card_urls:
                    if not card_url:
                        continue
                    try:
                        yield await self._extract_from_url(page, card_url)
                        await self._human_delay()
                    except Exception as exc:
                        logger.warning(f"Card extraction failed: {exc}")
                        continue

        await page.close()

    async def _extract_from_url(self, page, url: str) -> dict:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await self._human_delay()

        body_text = await page.inner_text("body")

        # Title + company + location from page title:
        # Format: "Company hiring Job Title in Location | LinkedIn"
        page_title = await page.title()
        title = company = location = ""
        if " hiring " in page_title:
            company = page_title.split(" hiring ")[0].strip()
            rest = page_title.split(" hiring ")[1].split(" | ")[0].strip()
            if " in " in rest:
                title = rest.rsplit(" in ", 1)[0].strip()
                location = rest.rsplit(" in ", 1)[1].strip()
            else:
                title = rest
        elif " | " in page_title:
            title = page_title.split(" | ")[0].strip()
            company = page_title.split(" | ")[1].strip()

        # JD text: everything after "Tailor my resume" (last UI button before content)
        jd_text = ""
        markers = ["Tailor my resume", "About the job", "Job description"]
        for marker in markers:
            if marker in body_text:
                jd_text = body_text.split(marker, 1)[1].strip()
                break
        if not jd_text:
            # Fallback: skip first 500 chars (navigation) and take the rest
            jd_text = body_text[500:].strip()

        return {
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "jd_text": jd_text,
            "source": "linkedin",
        }
