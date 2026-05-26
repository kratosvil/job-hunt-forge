import json
from datetime import datetime, timezone

from loguru import logger

from config.settings import settings
from src.database.db_manager import get_session
from src.database.models import HiringManager, ManagerStatus
from src.intelligence.pitch_generator import generate_connection_note
from src.scrapers.base_scraper import BaseScraper

# Roles that have hiring authority — only these receive connection requests
_DECISION_MAKER_KEYWORDS = [
    "vp", "vice president", "cto", "ceo", "coo", "chief",
    "head of", "director", "president", "founder", "co-founder",
    "engineering manager", "staff engineer", "principal engineer",
    "staff software", "principal software", "recruiter", "talent",
    "hiring manager", "architect",
]

_EXCLUDE_KEYWORDS = [
    "test engineer", "automation engineer", "qa engineer", "qa analyst",
    "data analyst", "business analyst", "sales engineer", "account manager",
]


def _is_decision_maker(role: str) -> bool:
    if not role:
        return False
    role_lower = role.lower()
    if any(kw in role_lower for kw in _EXCLUDE_KEYWORDS):
        return False
    return any(kw in role_lower for kw in _DECISION_MAKER_KEYWORDS)


class OutreachBot(BaseScraper):
    """
    Sends LinkedIn connection requests with a short personalized note.

    Model:
      1. Bot sends connection request + short note (≤280 chars) — automated.
      2. If the manager accepts and replies — Samir handles the conversation manually.
      3. No automated follow-up. Daily limit: max_daily_connections (default 15).

    Only targets managers with decision-making roles (VP, CTO, Director, etc.).
    """

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
            logger.info("No pending decision-maker managers to contact.")
            return 0

        page = await self._new_page()
        dispatched = 0

        for manager in pending:
            if sent_today + dispatched >= settings.max_daily_connections:
                logger.info("Daily connection limit reached mid-run. Stopping.")
                break

            if not _is_decision_maker(manager.role):
                logger.info(f"Skipping {manager.name} ({manager.role}) — not a decision maker.")
                self._mark_skipped(manager)
                continue

            try:
                note = self._build_note(manager)
                await self._send_connection_request(page, manager, note)
                self._mark_requested(manager, note)
                dispatched += 1
                logger.info(f"Connection request sent → {manager.name} @ {manager.company}")
                await self._human_delay()
            except Exception as exc:
                logger.error(f"Failed for {manager.name} @ {manager.company}: {exc}")
                continue

        await page.close()
        logger.info(f"Outreach complete — {dispatched} connection requests sent.")
        return dispatched

    # ── LinkedIn automation ──────────────────────────────────────────────

    async def _send_connection_request(self, page, manager: HiringManager, note: str) -> None:
        if not manager.linkedin_url:
            raise ValueError(f"No LinkedIn URL for {manager.name}")

        await page.goto(manager.linkedin_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await self._human_delay()

        # Find Connect button — may be primary or inside "More" dropdown
        connect_btn = await page.query_selector('button[aria-label*="Connect"]')
        if not connect_btn:
            more_btn = await page.query_selector('button[aria-label*="More actions"]')
            if more_btn:
                await more_btn.click()
                await self._human_delay()
                connect_btn = await page.query_selector('div[aria-label*="Connect"]')

        if not connect_btn:
            raise RuntimeError("Connect button not found — already connected or profile restricted.")

        await connect_btn.click()
        await self._human_delay()

        # Add a note to the connection request
        add_note_btn = await page.query_selector('button[aria-label="Add a note"]')
        if not add_note_btn:
            add_note_btn = await page.query_selector('button:has-text("Add a note")')

        if not add_note_btn:
            # Some profiles skip directly to the message box
            logger.warning(f"'Add a note' button not found for {manager.name} — sending without note.")
        else:
            await add_note_btn.click()
            await self._human_delay()

        textarea = await page.wait_for_selector('textarea[name="message"]', timeout=8000)
        await textarea.fill(note)
        await self._human_delay()

        send_btn = await page.query_selector('button[aria-label="Send now"]')
        if not send_btn:
            send_btn = await page.query_selector('button:has-text("Send")')
        if not send_btn:
            raise RuntimeError("Send button not found.")

        await send_btn.click()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_note(self, manager: HiringManager) -> str:
        matched, growth = self._load_job_context(manager.job_id)
        job_title = self._load_job_title(manager.job_id)
        return generate_connection_note(
            company_name=manager.company,
            job_title=job_title,
            manager_name=manager.name,
            matched_skills=matched,
            growth_signals=growth,
        )

    def _get_pending_managers(self) -> list[HiringManager]:
        with get_session() as session:
            return (
                session.query(HiringManager)
                .filter(HiringManager.status == ManagerStatus.PENDING)
                .limit(settings.max_daily_connections * 2)  # fetch extra to account for skips
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

    def _load_job_context(self, job_id: int | None) -> tuple[list[str], list[str]]:
        if not job_id:
            return [], []
        with get_session() as session:
            from src.database.models import Job
            job = session.get(Job, job_id)
            if not job:
                return [], []
            return json.loads(job.matched_skills or "[]"), json.loads(job.growth_signals or "[]")

    def _load_job_title(self, job_id: int | None) -> str:
        if not job_id:
            return "Engineering role"
        with get_session() as session:
            from src.database.models import Job
            job = session.get(Job, job_id)
            return job.title if job else "Engineering role"

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
