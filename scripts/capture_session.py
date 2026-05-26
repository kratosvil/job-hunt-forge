"""
Initializes the persistent browser profile for LinkedIn authentication.

Run this ONCE (or whenever your LinkedIn session expires). It opens a visible
Chromium window so you can log in manually. After login the profile is saved
to data/browser_profile/ and reused by all scrapers automatically — no
cookie export/import, same browser identity every time.

Usage:
    make capture-session
    # or:
    .venv/bin/python scripts/capture_session.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings


async def main() -> None:
    profile_dir = settings.browser_profile_path
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

        print("\n>>> A browser window opened — log in to LinkedIn.")
        print(">>> Use email + password (NOT 'Continue with Google').")
        print(">>> When you see your feed, press ENTER here.\n")
        input()

        await ctx.close()
        print(f"\nSession saved to: {profile_dir}")
        print("You can now run: make connect  (or make pipeline)")


if __name__ == "__main__":
    asyncio.run(main())
