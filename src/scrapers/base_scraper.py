import asyncio
import random
from abc import ABC, abstractmethod
from typing import AsyncGenerator

from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page

from config.settings import settings


class BaseScraper(ABC):
    """
    Abstract base for all Playwright-based scrapers.

    Subclasses implement `_search_jobs` and `_extract_job_data`.
    All scraping goes through this base to enforce consistent
    rate limiting and session injection.
    """

    def __init__(self) -> None:
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "BaseScraper":
        self._playwright = await async_playwright().start()
        browser = await self._playwright.chromium.launch(headless=True)
        state_path = settings.playwright_state_path
        if state_path.exists():
            self._context = await browser.new_context(storage_state=str(state_path))
            logger.info("Browser session loaded from state file.")
        else:
            self._context = await browser.new_context()
            logger.warning(
                f"No session state found at {state_path}. "
                "Run `make capture-session` to authenticate first."
            )
        return self

    async def __aexit__(self, *_) -> None:
        if self._context:
            await self._context.close()
        await self._playwright.stop()

    async def _new_page(self) -> Page:
        assert self._context, "Scraper not initialized — use as async context manager."
        return await self._context.new_page()

    async def _human_delay(self) -> None:
        delay = random.uniform(settings.scrape_delay_min, settings.scrape_delay_max)
        logger.debug(f"Waiting {delay:.1f}s (anti-bot delay)")
        await asyncio.sleep(delay)

    @abstractmethod
    async def scrape(self) -> AsyncGenerator[dict, None]:
        """Yield raw job dicts: {url, title, company, location, jd_text, source}"""
        ...
