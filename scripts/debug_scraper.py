"""
Debug: navigates to a single LinkedIn job URL and prints what gets extracted.
Run before the full pipeline to validate selectors.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings

TEST_URL = "https://www.linkedin.com/jobs/view/4418020525/"

SELECTORS = [
    ".jobs-description__content",
    "#job-details",
    ".jobs-box__html-content",
    "article.jobs-description__container",
    ".job-view-layout",
    "h1.job-details-jobs-unified-top-card__job-title",
    ".job-details-jobs-unified-top-card__company-name",
    ".job-details-jobs-unified-top-card__bullet",
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(settings.playwright_state_path)
        )
        page = await context.new_page()
        print(f"Navigating to {TEST_URL}...")
        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await asyncio.sleep(3)

        print(f"Page URL  : {page.url}")
        print(f"Page title: {await page.title()}")

        # dump first 3000 chars of HTML to see what's rendered
        html = await page.content()
        print(f"\n=== PAGE HTML (first 3000 chars) ===\n{html[:3000]}\n")

        print("\n=== SELECTOR RESULTS ===")
        for sel in SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()[:120]
                    print(f"[FOUND] {sel}\n        → {repr(text)}\n")
                else:
                    print(f"[MISS ] {sel}")
            except Exception as e:
                print(f"[ERROR] {sel} → {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
