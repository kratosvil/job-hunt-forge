"""
Captures your LinkedIn session state from a real browser login.

Run this ONCE before scraping. It opens a Chromium window so you can
log in manually. After login the session is saved to data/session_state.json
and reused by all scrapers — no login automation, no 2FA triggers.

Usage:
    python scripts/capture_session.py
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "session_state.json"


async def main() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.linkedin.com/login")
        print("\n>>> Log in to LinkedIn in the browser window that just opened.")
        print(">>> When you see your feed, press ENTER here to save the session.\n")
        input()
        await context.storage_state(path=str(STATE_PATH))
        print(f"Session saved to {STATE_PATH}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
