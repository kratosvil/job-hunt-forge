import random
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger

from config.settings import settings
from src.scrapers.base_scraper import BaseScraper

# Search queries targeting recruiters who handle DevOps/MLOps/Cloud roles
_SEARCH_QUERIES = [
    "reclutador IT devops cloud España",
    "talent acquisition devops aws Spain",
    "recruiter cloud engineer Madrid Barcelona",
    "technical recruiter Spain remote devops",
    "reclutador técnico cloud aws España remoto",
    "talent acquisition mlops Spain",
    "recruiter platform engineer Spain",
    "headhunter IT devops España",
    "talent acquisition ai engineer Spain remote",
    "reclutador infrastructure engineer España",
    "recruiter sre aws Spain",
    "talent acquisition cloud devops Madrid",
]

_SEARCH_URL = (
    "https://www.linkedin.com/search/results/people/"
    "?keywords={query}&origin=GLOBAL_SEARCH_HEADER&start={start}"
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

    def __init__(self, queries: list[str] | None = None, max_per_query: int = 8,
                 pages: int = 2) -> None:
        super().__init__()
        self._queries = queries or _SEARCH_QUERIES
        self._max_per_query = max_per_query
        self._pages = pages  # number of result pages to scan per query

    async def scrape(self) -> AsyncGenerator[dict, None]:
        page = await self._new_page()

        for query in self._queries:
            found_query = 0
            for page_num in range(self._pages):
                if found_query >= self._max_per_query:
                    break
                start = page_num * 10
                url = _SEARCH_URL.format(query=query.replace(" ", "%20"), start=start)
                logger.info(f"Searching: '{query}' page {page_num + 1}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self._human_delay()

                # LinkedIn uses obfuscated CSS classes — wait for profile links instead
                try:
                    await page.wait_for_selector("a[href*='/in/']", timeout=10000)
                except Exception:
                    logger.warning(f"No profile links loaded for query: '{query}'")
                    continue

                await self._human_delay()

                # Extract people via JavaScript — avoids obfuscated class issues
                people = await page.evaluate("""() => {
                    const SKIP = new Set(['Status is offline','Status is online',
                                          'Connect','Follow','Message','View profile',
                                          'LinkedIn Member','notifications','Home',
                                          'My Network','Jobs','Messaging']);

                    // Step 1: collect unique URLs with best name from link text
                    const byUrl = {};
                    document.querySelectorAll('a[href*="/in/"]').forEach(link => {
                        try {
                            const url = link.href.split('?')[0];
                            if (!url.includes('/in/')) return;
                            const name = (link.innerText || '').trim();
                            if (!byUrl[url] || byUrl[url].name.length < name.length)
                                byUrl[url] = { url, name };
                        } catch(e) {}
                    });

                    const results = [];
                    Object.values(byUrl).forEach(({ url, name }) => {
                        if (!name || name.length < 2 || SKIP.has(name)) return;

                        // Step 2: walk up to nearest LI
                        const slug = url.replace(/.*\\/in\\//, '');
                        const anchor = document.querySelector('a[href*="/in/' + slug + '"]');
                        if (!anchor) return;
                        let li = anchor;
                        for (let i = 0; i < 14; i++) {
                            if (!li.parentElement) break;
                            li = li.parentElement;
                            if (li.tagName === 'LI') break;
                        }

                        // Step 3: collect div texts (title/company), guarded against null
                        let title = '', company = '';
                        if (li) {
                            const texts = [...li.querySelectorAll('div')]
                                .map(d => {
                                    try { return (d.innerText || '').trim(); }
                                    catch(e) { return ''; }
                                })
                                .filter(t => t.length > 3 && t.length < 100
                                    && !t.startsWith('•')
                                    && t !== name
                                    && !SKIP.has(t)
                                    && !t.includes('\\n')
                                    && !/^\\d+$/.test(t));
                            title   = texts[0] || '';
                            company = texts[1] || '';
                        }

                        results.push({ name, title, company, linkedin_url: url });
                    });

                    return results;
                }""")

                logger.info(f"  Found {len(people)} profile links for '{query}'")

                page_found = 0
                for person in people:
                    if found_query >= self._max_per_query:
                        break
                    name  = person.get("name", "")
                    title = person.get("title", "")
                    if self._is_valid_name(name) and self._is_recruiter(title):
                        person["query"] = query
                        yield person
                        found_query += 1
                        page_found += 1

                logger.info(f"  → {page_found} recruiters page {page_num + 1} for '{query}'")

            except Exception as exc:
                logger.error(f"Search failed for '{query}' p{page_num+1}: {exc}")
                continue

            await asyncio.sleep(random.uniform(6.0, 10.0))

        await asyncio.sleep(random.uniform(8.0, 12.0))  # delay between queries

        await page.close()

    @staticmethod
    def _is_recruiter(title: str) -> bool:
        t = title.lower()
        positive = [
            "recruiter", "recruiting", "recruitment", "talent acquisition",
            "talent partner", "headhunter", "head hunter", "staffing",
            "talent sourcer", "sourcer", "hr manager", "people partner",
            "hiring manager",
        ]
        negative = ["software engineer", "developer", "architect", "data scientist"]
        if any(n in t for n in negative):
            return False
        return any(p in t for p in positive)

    @staticmethod
    def _is_valid_name(name: str) -> bool:
        if not name or len(name) > 60:
            return False
        # Filter out service descriptions and junk
        junk_signals = ["provides services", "application development",
                        "web development", "ACoA", "urn%3A"]
        return not any(j.lower() in name.lower() for j in junk_signals)
