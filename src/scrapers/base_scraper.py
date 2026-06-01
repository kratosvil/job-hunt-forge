import asyncio
import random
import shutil
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page

from config.settings import settings


class BaseScraper(ABC):
    """
    Abstract base for all Playwright-based scrapers.

    Uses launch_persistent_context so the browser profile (cookies, localStorage,
    fingerprint) persists across runs. LinkedIn sees the same browser it was first
    authenticated with — no cookie import/export.

    Subclasses can override:
      _HEADLESS = False      for pages that need a visible window (OutreachBot)
      _PROFILE_PATH = Path   to use a different browser profile (scraper account)
    """

    _HEADLESS: bool = True
    _PROFILE_PATH: Path | None = None  # None → uses settings.browser_profile_path (main account)

    def __init__(self) -> None:
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "BaseScraper":
        self._playwright = await async_playwright().start()

        profile_dir = self._PROFILE_PATH or settings.browser_profile_path
        self._profile_dir = profile_dir  # stored for use in _restore_cookies_if_logged_out
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Backup cookies before each run so a LinkedIn-forced logout doesn't
        # permanently destroy the li_at token in the persistent profile.
        cookies_path = profile_dir / "Default" / "Cookies"
        self._cookies_backup = profile_dir / "Default" / "Cookies.bak"
        if cookies_path.exists():
            shutil.copy2(cookies_path, self._cookies_backup)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        ctx_kwargs = dict(
            headless=self._HEADLESS,
            viewport={"width": 1280, "height": 900},
            args=launch_args,
        )

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(profile_dir), channel="chrome", **ctx_kwargs
            )
            logger.info(f"Persistent browser profile loaded (chrome) from {profile_dir}")
        except Exception:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(profile_dir), **ctx_kwargs
            )
            logger.info(f"Persistent browser profile loaded (chromium) from {profile_dir}")

        return self

    async def __aexit__(self, *_) -> None:
        if self._context:
            await self._context.close()
        await self._playwright.stop()

        # If LinkedIn invalidated li_at during the run (forced logout), restore
        # from the pre-run backup so we don't permanently lose the session.
        self._restore_cookies_if_logged_out()

    def _restore_cookies_if_logged_out(self) -> None:
        cookies_path = self._profile_dir / "Default" / "Cookies"
        backup = getattr(self, "_cookies_backup", None)
        if not backup or not backup.exists() or not cookies_path.exists():
            return
        try:
            conn = sqlite3.connect(str(cookies_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM cookies WHERE host_key LIKE '%linkedin%' AND name='li_at'")
            has_li_at = cur.fetchone() is not None
            conn.close()
            if not has_li_at:
                shutil.copy2(backup, cookies_path)
                logger.warning(
                    "li_at cookie was removed during run (LinkedIn forced logout). "
                    "Restored cookies from pre-run backup — session preserved for next run."
                )
        except Exception as exc:
            logger.debug(f"Cookie restore check failed (non-fatal): {exc}")

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
