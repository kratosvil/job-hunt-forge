import json
from datetime import datetime, timezone

from loguru import logger

from config.settings import settings
from src.database.db_manager import get_session
from src.database.models import HiringManager, ManagerStatus
from src.intelligence.pitch_generator import generate_pitch
from src.scrapers.base_scraper import BaseScraper


class OutreachBot(BaseScraper):
    """
    Sends personalized LinkedIn messages to hiring managers.

    Enforces daily send limits to avoid LinkedIn rate limiting.
    Only processes managers in PENDING status with no prior message sent.
    """

    async def scrape(self):
        raise NotImplementedError("OutreachBot does not scrape — use run() directly.")

    async def run(self) -> int:
        sent_count = self._get_daily_sent_count()
        if sent_count >= settings.max_daily_messages:
            logger.warning(
                f"Daily message limit reached ({settings.max_daily_messages}). "
                "Stopping outreach to protect account."
            )
            return 0

        pending = self._get_pending_managers()
        if not pending:
            logger.info("No pending managers to contact.")
            return 0

        page = await self._new_page()
        dispatched = 0

        for manager in pending:
            if sent_count + dispatched >= settings.max_daily_messages:
                logger.info("Daily limit reached mid-run. Stopping.")
                break
            try:
                matched, growth = self._load_job_context(manager.job_id)
                pitch = generate_pitch(
                    company_name=manager.company,
                    job_title=manager.role or "Engineering role",
                    manager_name=manager.name,
                    manager_title=manager.role or "",
                    matched_skills=matched,
                    growth_signals=growth,
                )
                await self._send_linkedin_message(page, manager, pitch)
                self._mark_sent(manager, pitch)
                dispatched += 1
                await self._human_delay()
            except Exception as exc:
                logger.error(f"Failed to message {manager.name}: {exc}")
                continue

        await page.close()
        logger.info(f"Outreach complete — {dispatched} messages sent this run.")
        return dispatched

    async def _send_linkedin_message(self, page, manager: HiringManager, text: str) -> None:
        if not manager.linkedin_url:
            raise ValueError(f"No LinkedIn URL for {manager.name}")

        await page.goto(manager.linkedin_url, wait_until="networkidle")
        await self._human_delay()

        message_btn = await page.query_selector("button[aria-label*='Message']")
        if not message_btn:
            raise RuntimeError("Message button not found — profile may be private.")

        await message_btn.click()
        await self._human_delay()

        text_area = await page.wait_for_selector(
            ".msg-form__contenteditable", timeout=5000
        )
        await text_area.fill(text)
        await self._human_delay()

        send_btn = await page.query_selector("button[type='submit'].msg-form__send-button")
        if not send_btn:
            raise RuntimeError("Send button not found.")
        await send_btn.click()
        logger.info(f"Message sent to {manager.name} @ {manager.company}")

    def _get_pending_managers(self) -> list[HiringManager]:
        with get_session() as session:
            return (
                session.query(HiringManager)
                .filter(
                    HiringManager.status == ManagerStatus.PENDING,
                    HiringManager.message_sent.is_(False),
                )
                .limit(settings.max_daily_messages)
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
                    HiringManager.message_sent.is_(True),
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
            matched = json.loads(job.matched_skills or "[]")
            growth = json.loads(job.growth_signals or "[]")
            return matched, growth

    def _mark_sent(self, manager: HiringManager, pitch: str) -> None:
        with get_session() as session:
            m = session.get(HiringManager, manager.id)
            if m:
                m.message_sent = True
                m.message_text = pitch
                m.status = ManagerStatus.MESSAGE_SENT
                m.contacted_at = datetime.now(timezone.utc)
