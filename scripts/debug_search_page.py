"""
Debug: navega a la página de búsqueda de LinkedIn y vuelca el HTML
para identificar el selector correcto de job cards.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings

SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords=MLOps%20Engineer&location=Remote&f_WT=2&f_TPR=r86400"
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(settings.playwright_state_path),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"Navigating to search URL...")
        await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await asyncio.sleep(2)

        print(f"Page title: {await page.title()}")

        job_cards = await page.query_selector_all("div.job-search-card, .job-card-container")
        print(f"Cards found: {len(job_cards)}")

        card_urls = []
        for card in job_cards[:5]:  # preview first 5
            try:
                link_el = await card.query_selector(
                    "a.base-card__full-link, a.job-card-container__link"
                )
                href = await link_el.get_attribute("href") if link_el else ""
                if href and not href.startswith("http"):
                    href = f"https://www.linkedin.com{href}"
                url = href.split("?")[0] if href else ""
                card_urls.append(url)
                print(f"  URL: {url}")
            except Exception as e:
                print(f"  ERROR: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
