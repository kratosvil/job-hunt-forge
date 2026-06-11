import random
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger

from config.settings import settings
from src.scrapers.base_scraper import BaseScraper

# Search queries targeting recruiters who handle DevOps/MLOps/Cloud roles
_SEARCH_QUERIES = [
    "recruiter devops aws remote",
    "talent acquisition mlops cloud engineer",
    "technical recruiter platform engineer infrastructure",
    "recruiter site reliability engineer aws",
    "talent acquisition ai machine learning remote",
]

_SEARCH_URL = (
    "https://www.linkedin.com/search/results/people/"
    "?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
)


class RecruiterFinderScraper(BaseScraper):
    """
    Searches LinkedIn People for tech recruiters handling DevOps/MLOps/Cloud roles.

    Reads search results pages only — does NOT visit individual profiles.
    This is significantly safer than find-managers-batch which visited each profile.

    Output dicts: {name, title, company, linkedin_url, query}
    """

    _PROFILE_PATH: Path = settings.scraper_profile_path
    _HEADLESS: bool = True

    def __init__(self, queries: list[str] | None = None, max_per_query: int = 8) -> None:
        super().__init__()
        self._queries = queries or _SEARCH_QUERIES
        self._max_per_query = max_per_query

    async def scrape(self) -> AsyncGenerator[dict, None]:
        page = await self._new_page()

        for query in self._queries:
            url = _SEARCH_URL.format(query=query.replace(" ", "%20"))
            logger.info(f"Searching recruiters: '{query}'")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self._human_delay()

                # Wait for people results to load
                try:
                    await page.wait_for_selector(
                        "li.reusable-search__result-container, "
                        "div.entity-result, "
                        "li[data-chameleon-result-urn]",
                        timeout=10000,
                    )
                except Exception:
                    logger.warning(f"No results loaded for query: '{query}'")
                    continue

                await self._human_delay()

                # Extract all visible person cards
                cards = await page.query_selector_all(
                    "li.reusable-search__result-container, "
                    "div.entity-result__item, "
                    "li[data-chameleon-result-urn]"
                )
                logger.info(f"  Found {len(cards)} cards for '{query}'")

                found = 0
                for card in cards:
                    if found >= self._max_per_query:
                        break
                    try:
                        person = await self._extract_person(card)
                        if person and self._is_recruiter(person.get("title", "")):
                            person["query"] = query
                            yield person
                            found += 1
                            await asyncio.sleep(random.uniform(1.5, 3.0))
                    except Exception as exc:
                        logger.debug(f"Card extraction failed: {exc}")
                        continue

                logger.info(f"  → {found} recruiters found for '{query}'")

            except Exception as exc:
                logger.error(f"Search failed for '{query}': {exc}")
                continue

            # Delay between queries — more conservative
            await asyncio.sleep(random.uniform(8.0, 14.0))

        await page.close()

    async def _extract_person(self, card) -> dict | None:
        # Name — try multiple selectors across LinkedIn UI versions
        name = ""
        for sel in [
            "span.entity-result__title-text a span[aria-hidden='true']",
            "span[data-anonymize='person-name']",
            "a.app-aware-link span[aria-hidden='true']",
            ".entity-result__title-text",
        ]:
            el = await card.query_selector(sel)
            if el:
                name = (await el.inner_text()).strip()
                if name and name.lower() not in ("linkedin member",):
                    break

        if not name:
            return None

        # Title
        title = ""
        for sel in [
            ".entity-result__primary-subtitle",
            "div[data-anonymize='title']",
            ".entity-result__summary",
        ]:
            el = await card.query_selector(sel)
            if el:
                title = (await el.inner_text()).strip()
                break

        # Company
        company = ""
        for sel in [
            ".entity-result__secondary-subtitle",
            "div[data-anonymize='company-name']",
        ]:
            el = await card.query_selector(sel)
            if el:
                company = (await el.inner_text()).strip()
                break

        # Profile URL
        linkedin_url = ""
        for sel in [
            "a.app-aware-link[href*='/in/']",
            "a[href*='linkedin.com/in/']",
            ".entity-result__title-text a",
        ]:
            el = await card.query_selector(sel)
            if el:
                href = await el.get_attribute("href")
                if href and "/in/" in href:
                    linkedin_url = href.split("?")[0]
                    break

        if not linkedin_url:
            return None

        return {
            "name": name,
            "title": title,
            "company": company,
            "linkedin_url": linkedin_url,
        }

    @staticmethod
    def _is_recruiter(title: str) -> bool:
        t = title.lower()
        positive = [
            "recruiter", "recruiting", "recruitment", "talent acquisition",
            "talent partner", "headhunter", "head hunter", "staffing",
            "talent sourcer", "sourcer", "hr manager", "people partner",
            "hiring manager",
        ]
        # Exclude non-recruiters that might slip through
        negative = ["software engineer", "developer", "architect", "data scientist"]
        if any(n in t for n in negative):
            return False
        return any(p in t for p in positive)
