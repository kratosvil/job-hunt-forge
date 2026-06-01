"""
Initializes the persistent browser profile for the dedicated scraper account.

Run this ONCE to log in the secondary LinkedIn account used exclusively for
job searching. The session is saved to data/scraper_profile/ and reused by
LinkedInScraper and EasyApplyScraper automatically.

The main account (data/browser_profile/) is kept separate and is only used
by the outreach bot for connection requests.

Usage:
    make capture-scraper-session
    # or:
    DISPLAY=:0 .venv/bin/python scripts/capture_scraper_session.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings


async def main() -> None:
    profile_dir = settings.scraper_profile_path
    profile_dir.mkdir(parents=True, exist_ok=True)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                channel="chrome",
                viewport={"width": 1280, "height": 900},
                args=launch_args,
            )
            print("Launched real Chrome.")
        except Exception as exc:
            print(f"Chrome launch failed ({exc}) — falling back to Playwright Chromium.")
            ctx = await p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=launch_args,
            )
            print("Launched Playwright Chromium.")

        page = await ctx.new_page()
        await page.goto("https://www.linkedin.com/login")

        print("\n>>> Browser abierto — inicia sesión con la cuenta SCRAPER (la nueva).")
        print(">>> USA email + contraseña (NO 'Continuar con Google').")
        print(">>> Cuando veas tu feed, presiona ENTER aquí.\n")
        input()

        await ctx.close()
        print(f"\nSesión scraper guardada en: {profile_dir}")
        print("Ya puedes correr: make scrape  y  make easy-apply")


if __name__ == "__main__":
    asyncio.run(main())
