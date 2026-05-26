"""
Debug script — navigate to a LinkedIn profile and dump all button selectors.
Usage: .venv/bin/python scripts/debug_connect_button.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings


PROFILE_URL = "https://www.linkedin.com/in/luizfelipelaviola/"


async def main():
    async with async_playwright() as p:
        profile_dir = settings.browser_profile_path
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ]
        ctx_kwargs = dict(
            headless=False,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            args=launch_args,
        )
        try:
            ctx = await p.chromium.launch_persistent_context(str(profile_dir), channel="chrome", **ctx_kwargs)
            print("Launched persistent Chrome profile.")
        except Exception:
            ctx = await p.chromium.launch_persistent_context(str(profile_dir), **ctx_kwargs)
            print("Launched persistent Chromium profile.")

        page = await ctx.new_page()
        # Feed warm-up: triggers LinkedIn's li_at validation even if it redirects to login
        print("Feed warm-up...")
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        print(f"After warm-up: {page.url}")
        await asyncio.sleep(3)

        print(f"Navigating to {PROFILE_URL} ...")
        await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Wait for LinkedIn's SPA to render the action buttons
        await asyncio.sleep(8)

        # Screenshot (viewport only — no full_page to avoid font timeout)
        screenshot_path = "/tmp/linkedin_profile_debug.png"
        try:
            await page.screenshot(path=screenshot_path, full_page=False, timeout=15000)
            print(f"\nScreenshot saved to: {screenshot_path}")
        except Exception as exc:
            print(f"\nScreenshot failed (non-fatal): {exc}")

        # Current URL (check if redirected to login)
        print(f"Current URL: {page.url}")

        # Dump all buttons with aria-label
        print("\n--- All <button> elements ---")
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            label = await btn.get_attribute("aria-label") or ""
            text = (await btn.inner_text()).strip().replace("\n", " ")[:60]
            visible = await btn.is_visible()
            print(f"  aria-label={repr(label):<50} text={repr(text):<40} visible={visible}")

        # Specifically search for connect-related elements
        print("\n--- Elements containing 'Connect' (any tag) ---")
        for selector in [
            'button[aria-label*="Connect"]',
            'button[aria-label*="connect"]',
            'div[aria-label*="Connect"]',
            'button:has-text("Connect")',
            '[data-control-name*="connect"]',
            'li-icon[type="connect"]',
        ]:
            try:
                el = await page.query_selector(selector)
                print(f"  {selector:<60} → {'FOUND' if el else 'not found'}")
            except Exception as exc:
                print(f"  {selector:<60} → ERROR: {exc}")

        # Also check for "More actions" / overflow menu
        print("\n--- 'More actions' button ---")
        for selector in [
            'button[aria-label*="More actions"]',
            'button[aria-label*="More"]',
            'button[aria-label*="more"]',
        ]:
            el = await page.query_selector(selector)
            print(f"  {selector:<60} → {'FOUND' if el else 'not found'}")

        await ctx.close()


asyncio.run(main())
