import json
from dataclasses import dataclass

from loguru import logger
from playwright.async_api import Page

from config.settings import settings
from src.database.db_manager import get_session
from src.database.models import HiringManager, Job, JobStatus, ManagerStatus
from src.scrapers.base_scraper import BaseScraper

# Titles to search when no explicit name is found in the JD
_DECISION_MAKER_TITLES = [
    "VP of Engineering",
    "VP Engineering",
    "CTO",
    "Head of Platform",
    "Head of DevOps",
    "Head of Infrastructure",
    "Director of Engineering",
    "Engineering Manager",
]

_LI_PEOPLE_SEARCH = (
    "https://www.linkedin.com/search/results/people/"
    "?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
)


@dataclass
class _ManagerCandidate:
    name: str
    role: str
    linkedin_url: str


class ManagerFinder(BaseScraper):
    """
    Discovers hiring managers on LinkedIn for every qualified job in the DB.

    Strategy per job:
    1. If the JD analysis extracted explicit names (hiring_manager_signals),
       search those first — they're the highest-value targets.
    2. Then search generic decision-maker titles at the company as fallback.
    3. Deduplicates by linkedin_url — never inserts the same person twice.
    4. Marks job.managers_searched=True to avoid re-processing.
    """

    async def scrape(self):
        raise NotImplementedError("Use find_for_qualified_jobs() directly.")

    async def find_for_qualified_jobs(self) -> int:
        jobs = self._get_unsearched_jobs()
        if not jobs:
            logger.info("No qualified jobs pending manager search.")
            return 0

        page = await self._new_page()
        total_found = 0

        for job in jobs:
            logger.info(f"Searching managers for: {job.title} @ {job.company}")
            candidates = await self._find_candidates(page, job)

            inserted = self._save_candidates(candidates, job)
            total_found += inserted
            self._mark_searched(job)

            logger.info(
                f"  → {inserted} manager(s) queued for {job.company}"
            )
            await self._human_delay()

        await page.close()
        logger.info(f"Manager search complete — {total_found} total queued.")
        return total_found

    # ── Private helpers ──────────────────────────────────────────────────

    async def _find_candidates(self, page: Page, job: Job) -> list[_ManagerCandidate]:
        candidates: list[_ManagerCandidate] = []
        seen_urls: set[str] = set()

        # 1. Explicit names from JD analysis
        signals: list[str] = json.loads(job.hiring_manager_signals or "[]")
        for signal in signals[:2]:  # cap at 2 explicit names
            query = f"{signal} {job.company}"
            found = await self._search_people(page, query, limit=1)
            for c in found:
                if c.linkedin_url not in seen_urls:
                    candidates.append(c)
                    seen_urls.add(c.linkedin_url)
            await self._human_delay()

        # 2. Generic decision-maker titles at the company
        for title in _DECISION_MAKER_TITLES:
            if len(candidates) >= 3:  # 3 managers per job is enough
                break
            query = f"{title} {job.company}"
            found = await self._search_people(page, query, limit=1)
            for c in found:
                if c.linkedin_url not in seen_urls:
                    candidates.append(c)
                    seen_urls.add(c.linkedin_url)
            await self._human_delay()

        return candidates

    async def _search_people(
        self, page: Page, query: str, limit: int = 2
    ) -> list[_ManagerCandidate]:
        url = _LI_PEOPLE_SEARCH.format(query=query.replace(" ", "%20"))
        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception as exc:
            logger.warning(f"Navigation failed for query '{query}': {exc}")
            return []

        results = await page.query_selector_all(".entity-result__item")
        candidates = []

        for result in results[:limit]:
            try:
                candidate = await self._extract_result(result)
                if candidate:
                    candidates.append(candidate)
            except Exception as exc:
                logger.debug(f"Result extraction failed: {exc}")

        return candidates

    async def _extract_result(self, result) -> _ManagerCandidate | None:
        name_el = await result.query_selector(".entity-result__title-text a span[aria-hidden='true']")
        role_el = await result.query_selector(".entity-result__primary-subtitle")
        link_el = await result.query_selector(".entity-result__title-text a")

        if not name_el or not link_el:
            return None

        name = (await name_el.inner_text()).strip()
        role = (await role_el.inner_text()).strip() if role_el else ""
        href = await link_el.get_attribute("href") or ""
        linkedin_url = href.split("?")[0]  # strip tracking params

        if not name or not linkedin_url:
            return None

        return _ManagerCandidate(name=name, role=role, linkedin_url=linkedin_url)

    def _save_candidates(self, candidates: list[_ManagerCandidate], job: Job) -> int:
        inserted = 0
        with get_session() as session:
            for c in candidates:
                exists = (
                    session.query(HiringManager)
                    .filter(HiringManager.linkedin_url == c.linkedin_url)
                    .first()
                )
                if exists:
                    logger.debug(f"Duplicate manager skipped: {c.name}")
                    continue
                manager = HiringManager(
                    name=c.name,
                    role=c.role,
                    company=job.company,
                    linkedin_url=c.linkedin_url,
                    job_id=job.id,
                    status=ManagerStatus.PENDING,
                    message_sent=False,
                )
                session.add(manager)
                inserted += 1
        return inserted

    def _get_unsearched_jobs(self) -> list[Job]:
        with get_session() as session:
            return (
                session.query(Job)
                .filter(
                    Job.status == JobStatus.ANALYZED,
                    Job.managers_searched.is_(False),
                )
                .all()
            )

    def _mark_searched(self, job: Job) -> None:
        with get_session() as session:
            j = session.get(Job, job.id)
            if j:
                j.managers_searched = True
