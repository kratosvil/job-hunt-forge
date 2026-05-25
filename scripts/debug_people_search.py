"""
Debug: valida extracción de manager candidates con selectores ARIA.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright
from config.settings import settings

QUERY = "VP of Engineering Cisco"
SEARCH_URL = (
    "https://www.linkedin.com/search/results/people/"
    f"?keywords={QUERY.replace(' ', '%20')}&origin=GLOBAL_SEARCH_HEADER"
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

        print(f"Query: {QUERY}")
        await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await asyncio.sleep(3)

        results = await page.query_selector_all('div[role="listitem"]')
        print(f"Listitems found: {len(results)}")

        for i, result in enumerate(results[:5]):
            try:
                link_el = await result.query_selector('a[href*="/in/"]')
                img_el = await result.query_selector("img[alt]")

                href = await link_el.get_attribute("href") if link_el else ""
                linkedin_url = href.split("?")[0] if href else ""
                name = (await img_el.get_attribute("alt")).strip() if img_el else ""

                full_text = (await result.inner_text()).strip()
                lines = [
                    ln.strip() for ln in full_text.splitlines()
                    if ln.strip() and not ln.strip().startswith("•")
                ]
                role = lines[1] if len(lines) > 1 else ""

                print(f"\n  [{i+1}] Name : {name!r}")
                print(f"       Role : {role!r}")
                print(f"       URL  : {linkedin_url}")
            except Exception as e:
                print(f"\n  [{i+1}] ERROR: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
