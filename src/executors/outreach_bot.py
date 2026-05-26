import json
from datetime import datetime, timezone, timedelta

from loguru import logger

from config.settings import settings
from src.database.db_manager import get_session
from src.database.models import HiringManager, Job, ManagerStatus
from src.intelligence.pitch_generator import generate_connection_note
from src.scrapers.base_scraper import BaseScraper

# ── Manager classification ───────────────────────────────────────────────────

_RECRUITER_KEYWORDS = [
    "recruiter", "talent acquisition", "talent advisor", "hiring manager",
    "head of talent", "hr ", "human resources", "people operations",
    "technical recruiter", "tech recruiter",
]

_TECHNICAL_KEYWORDS = [
    "vp", "vice president", "cto", "ceo", "coo", "chief",
    "head of engineering", "head of platform", "head of infrastructure",
    "head of devops", "head of data", "director of engineering",
    "engineering manager", "staff engineer", "principal engineer",
    "staff software", "principal software", "architect", "founder",
    "co-founder",
]

_SKIP_KEYWORDS = [
    "test engineer", "automation engineer", "qa engineer", "qa analyst",
    "data analyst", "business analyst", "sales engineer", "account manager",
    "software engineer", "senior software engineer", "backend", "frontend",
    "fullstack", "full stack",
]

# Companies where C-suite won't respond to cold LinkedIn from an unknown
_MEGA_CORPS = {
    "amazon", "google", "meta", "apple", "microsoft", "nvidia",
    "alphabet", "anthropic", "openai", "bytedance",
}

# Titles too senior at mega-corps to be reachable
_UNREACHABLE_TITLES = ["president", "chief executive", "chief technology", "cto", "ceo"]


def _classify_manager(role: str) -> str:
    """Returns 'technical', 'recruiter', or 'skip'."""
    if not role:
        return "skip"
    role_lower = role.lower()

    if any(kw in role_lower for kw in _SKIP_KEYWORDS):
        return "skip"
    if any(kw in role_lower for kw in _RECRUITER_KEYWORDS):
        return "recruiter"
    if any(kw in role_lower for kw in _TECHNICAL_KEYWORDS):
        return "technical"
    return "skip"


def _is_mega_corp_unreachable(company: str, role: str) -> bool:
    """Skip FAANG/Fortune-10 C-suite — they won't act on cold LinkedIn requests."""
    company_lower = company.lower()
    role_lower = role.lower() if role else ""
    if any(corp in company_lower for corp in _MEGA_CORPS):
        if any(title in role_lower for title in _UNREACHABLE_TITLES):
            return True
    return False


class OutreachBot(BaseScraper):
    """
    Sends LinkedIn connection requests with a short personalized note.

    Model:
      1. Bot sends connection request + short note (≤270 chars) — automated.
      2. Only targets managers from jobs scraped in the last 48h (fresh postings).
      3. Filters: decision-makers only, no mega-corp C-suite, no peer-level engineers.
      4. Two note styles: technical (VP/CTO) vs recruiter (talent/HR).
      5. When manager responds — Samir handles the conversation manually.
      6. Daily limit: max_daily_connections (default 15) to avoid LinkedIn ban.
    """

    # Only contact managers for jobs posted/scraped within this window
    RECENCY_HOURS = 48

    async def scrape(self):
        raise NotImplementedError("OutreachBot does not scrape — use run() directly.")

    async def run(self) -> int:
        sent_today = self._get_daily_sent_count()
        if sent_today >= settings.max_daily_connections:
            logger.warning(
                f"Daily connection limit reached ({settings.max_daily_connections}). "
                "Stopping to protect account."
            )
            return 0

        pending = self._get_pending_managers()
        if not pending:
            logger.info("No pending managers for recent jobs.")
            return 0

        page = await self._new_page()
        dispatched = 0

        for manager, job in pending:
            if sent_today + dispatched >= settings.max_daily_connections:
                logger.info("Daily limit reached mid-run. Stopping.")
                break

            # ── Filter: mega-corp unreachable ────────────────────────────
            if _is_mega_corp_unreachable(manager.company, manager.role or ""):
                logger.info(
                    f"Skipping {manager.name} @ {manager.company} "
                    "— mega-corp C-suite, unreachable via cold outreach."
                )
                self._mark_skipped(manager)
                continue

            # ── Filter: classify role ────────────────────────────────────
            note_type = _classify_manager(manager.role or "")
            if note_type == "skip":
                logger.info(
                    f"Skipping {manager.name} ({manager.role}) "
                    "— not a decision maker or recruiter."
                )
                self._mark_skipped(manager)
                continue

            try:
                matched = json.loads(job.matched_skills or "[]")
                growth = json.loads(job.growth_signals or "[]")
                note = generate_connection_note(
                    company_name=manager.company,
                    job_title=job.title,
                    manager_name=manager.name,
                    matched_skills=matched,
                    growth_signals=growth,
                    note_type=note_type,
                )
                await self._send_connection_request(page, manager, note)
                self._mark_requested(manager, note)
                dispatched += 1
                logger.info(
                    f"[{note_type}] Connection request sent → "
                    f"{manager.name} @ {manager.company}"
                )
                await self._human_delay()
            except Exception as exc:
                logger.error(f"Failed for {manager.name} @ {manager.company}: {exc}")
                continue

        await page.close()
        logger.info(f"Outreach complete — {dispatched} connection requests sent.")
        return dispatched

    # ── LinkedIn automation ──────────────────────────────────────────────────

    async def _send_connection_request(
        self, page, manager: HiringManager, note: str
    ) -> None:
        if not manager.linkedin_url:
            raise ValueError(f"No LinkedIn URL for {manager.name}")

        await page.goto(
            manager.linkedin_url, wait_until="domcontentloaded", timeout=60000
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await self._human_delay()

        # Connect button — primary or inside "More actions" dropdown
        connect_btn = await page.query_selector('button[aria-label*="Connect"]')
        if not connect_btn:
            more_btn = await page.query_selector('button[aria-label*="More actions"]')
            if more_btn:
                await more_btn.click()
                await self._human_delay()
                connect_btn = await page.query_selector('div[aria-label*="Connect"]')

        if not connect_btn:
            raise RuntimeError(
                "Connect button not found — already connected or profile restricted."
            )

        await connect_btn.click()
        await self._human_delay()

        # Add a note
        add_note_btn = await page.query_selector('button[aria-label="Add a note"]')
        if not add_note_btn:
            add_note_btn = await page.query_selector('button:has-text("Add a note")')

        if add_note_btn:
            await add_note_btn.click()
            await self._human_delay()
        else:
            logger.warning(
                f"'Add a note' button not found for {manager.name} — sending without note."
            )

        textarea = await page.wait_for_selector(
            'textarea[name="message"]', timeout=8000
        )
        await textarea.fill(note)
        await self._human_delay()

        send_btn = await page.query_selector('button[aria-label="Send now"]')
        if not send_btn:
            send_btn = await page.query_selector('button:has-text("Send")')
        if not send_btn:
            raise RuntimeError("Send button not found.")

        await send_btn.click()

    # ── DB helpers ───────────────────────────────────────────────────────────

    def _get_pending_managers(self) -> list[tuple[HiringManager, Job]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.RECENCY_HOURS)
        with get_session() as session:
            return (
                session.query(HiringManager, Job)
                .join(Job, HiringManager.job_id == Job.id)
                .filter(
                    HiringManager.status == ManagerStatus.PENDING,
                    Job.scraped_at >= cutoff,
                )
                .order_by(Job.fit_score.desc())
                .limit(settings.max_daily_connections * 3)
                .all()
            )

    def _get_daily_sent_count(self) -> int:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with get_session() as session:
            return (
                session.query(HiringManager)
                .filter(
                    HiringManager.contacted_at >= today_start,
                    HiringManager.status == ManagerStatus.CONNECTION_REQUESTED,
                )
                .count()
            )

    def _mark_requested(self, manager: HiringManager, note: str) -> None:
        with get_session() as session:
            m = session.get(HiringManager, manager.id)
            if m:
                m.status = ManagerStatus.CONNECTION_REQUESTED
                m.connection_note = note
                m.contacted_at = datetime.now(timezone.utc)

    def _mark_skipped(self, manager: HiringManager) -> None:
        with get_session() as session:
            m = session.get(HiringManager, manager.id)
            if m:
                m.status = ManagerStatus.SKIPPED
