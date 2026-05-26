import asyncio
import json
from datetime import datetime, timezone, timedelta

from loguru import logger

from config.settings import settings
from src.database.db_manager import get_session
from src.database.models import HiringManager, Job, ManagerStatus
from src.intelligence.pitch_generator import generate_connection_note
from src.scrapers.base_scraper import BaseScraper

# ── Manager classification ───────────────────────────────────────────────────

# Highest priority — actively own the hiring process
_RECRUITER_KEYWORDS = [
    "recruiter", "talent acquisition", "talent advisor", "talent partner",
    "head of talent", "hr ", "human resources", "people operations",
    "technical recruiter", "tech recruiter", "sourcer", "sourcing",
    "staffing", "hiring manager",
]

# Direct hiring managers — close enough to the role to act on a cold message
_TECHNICAL_KEYWORDS = [
    "engineering manager", "engineering lead",
    "head of engineering", "head of platform", "head of infrastructure",
    "head of devops", "head of mlops", "head of data engineering",
    "head of sre", "head of cloud",
    "director of engineering", "director of platform", "director of infrastructure",
    "director of devops", "director of cloud", "director of sre",
    "director of mlops", "director of data engineering",
    "staff engineer", "principal engineer",
    "staff software", "principal software",
    "architect",
]

# Skip — too senior (won't act on cold messages), peer-level, or irrelevant
_SKIP_KEYWORDS = [
    # C-suite — too far from hiring decisions for IC roles
    "cto", "ceo", "coo", "cpo", "cfo", "chief",
    "president", "vice president", "vp ", "vp,", "vp-",
    "svp", "evp", "avp",
    "founder", "co-founder",
    # Peer-level engineers — not decision makers
    "software engineer", "senior software engineer",
    "backend", "frontend", "fullstack", "full stack",
    # Irrelevant functions
    "test engineer", "automation engineer", "qa engineer", "qa analyst",
    "data analyst", "business analyst", "sales engineer", "account manager",
    "product manager", "scrum master", "agile coach",
]


def _classify_manager(role: str) -> str:
    """Returns 'technical', 'recruiter', or 'skip'."""
    if not role:
        return "skip"
    role_lower = role.lower()

    # Skip check first — overrides everything
    if any(kw in role_lower for kw in _SKIP_KEYWORDS):
        return "skip"
    if any(kw in role_lower for kw in _RECRUITER_KEYWORDS):
        return "recruiter"
    if any(kw in role_lower for kw in _TECHNICAL_KEYWORDS):
        return "technical"
    return "skip"


def _is_mega_corp_unreachable(company: str, role: str) -> bool:
    """Unused — C-suite is now skipped globally via _SKIP_KEYWORDS."""
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

    # Profile pages require a headful browser — LinkedIn blocks headless
    # fingerprints on authenticated actions (connection requests).
    # DISPLAY=:0 must be set; the window can be minimized.
    _HEADLESS = False

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
            except RuntimeError as exc:
                # Permanent failures — mark SKIPPED so this manager is never retried.
                # Covers: already connected, profile restricted, Connect button absent.
                logger.warning(
                    f"Skipping permanently {manager.name} @ {manager.company}: {exc}"
                )
                self._mark_skipped(manager)
                continue
            except Exception as exc:
                # Transient failures (timeout, network) — keep PENDING for next run.
                logger.error(f"Transient failure for {manager.name} @ {manager.company}: {exc}")
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

        # Authwall check — session might have expired mid-run
        if "authwall" in page.url or "login" in page.url:
            raise RuntimeError(
                f"Session expired mid-run (redirected to {page.url}). "
                "Run `make capture-session` and retry."
            )

        # Dismiss any overlay/modal that might intercept clicks (Premium banner, etc.).
        # Escape closes most LinkedIn modals and dismisses sticky promos.
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.4)
        # If a Premium promo banner is present, scroll it out of the click path.
        try:
            promo = await page.query_selector("div._607fba13, [data-test-premium-custom-promo]")
            if promo and await promo.is_visible():
                await page.evaluate("el => el.remove()", promo)
        except Exception:
            pass

        # Already-connected check — "Message" button in header means 1st-degree.
        # Pending-invite check — "Pending" means request already sent (e.g. sidebar bug).
        for already_sel, reason in [
            ('button[aria-label="Message"]', "already connected"),
            ('button[aria-label*="Pending"]', "connection request already pending"),
            ('button[aria-label*="pending"]', "connection request already pending"),
        ]:
            btn = await page.query_selector(already_sel)
            if btn and await btn.is_visible():
                box = await btn.bounding_box()
                if box and box["y"] < 700:
                    raise RuntimeError(
                        f"Profile not actionable — {reason}."
                    )

        # Connect button — must be in the profile header (y < 700px), not sidebar.
        # LinkedIn sidebar "People you may know" also has "Invite X to connect"
        # buttons that would trigger a wrong modal.
        connect_btn = await self._find_profile_connect_btn(page)
        if not connect_btn:
            # Check "More actions" overflow menu — Creator Mode profiles hide
            # Connect here. Profile action bar is at y 150–700px; nav "More"
            # (at y < 100) must be excluded to avoid opening the wrong dropdown.
            more_btn = None
            for sel in [
                'button[aria-label*="More actions"]',
                'button[aria-label="More"]',
                'button:has-text("More")',
            ]:
                candidates = await page.query_selector_all(sel)
                for btn in candidates:
                    if not await btn.is_visible():
                        continue
                    box = await btn.bounding_box()
                    if box and 150 < box["y"] < 700:
                        more_btn = btn
                        break
                if more_btn:
                    break
            if more_btn:
                await more_btn.click()
                await self._human_delay()
                for sel in [
                    'div[aria-label*="connect" i]',
                    'li[aria-label*="connect" i]',
                    'span:has-text("Connect")',
                    'button:has-text("Connect")',
                    '[role="menuitem"]:has-text("Connect")',
                ]:
                    connect_btn = await page.query_selector(sel)
                    if connect_btn and await connect_btn.is_visible():
                        break
                    connect_btn = None

        if not connect_btn:
            raise RuntimeError(
                "Connect button not found — already connected, following only, or profile restricted."
            )

        await connect_btn.click()

        # Wait for the connection modal to appear (up to 6s)
        try:
            await page.wait_for_selector(
                'button[aria-label="Add a note"], '
                'button[aria-label="Send without a note"], '
                'button[aria-label="Send now"], '
                'div[role="dialog"]',
                timeout=6000,
            )
        except Exception:
            pass
        await self._human_delay()

        # "Add a note" — try all known label variants
        add_note_btn = None
        for sel in [
            'button[aria-label="Add a note"]',
            'button[aria-label*="note"]',
            'button:has-text("Add a note")',
        ]:
            add_note_btn = await page.query_selector(sel)
            if add_note_btn and await add_note_btn.is_visible():
                break
            add_note_btn = None

        if add_note_btn:
            await add_note_btn.click()
            await self._human_delay()
            textarea = await page.wait_for_selector(
                'textarea[name="message"]', timeout=8000
            )
            await textarea.fill(note)
            await self._human_delay()
        else:
            logger.warning(
                f"'Add a note' button not found for {manager.name} — sending without note."
            )

        # "Send" — LinkedIn uses several labels depending on modal state
        send_btn = None
        for sel in [
            'button[aria-label="Send now"]',
            'button[aria-label="Send without a note"]',
            'button[aria-label*="Send"]',
            'button:has-text("Send now")',
            'button:has-text("Send without a note")',
            'button:has-text("Send")',
        ]:
            send_btn = await page.query_selector(sel)
            if send_btn and await send_btn.is_visible():
                break
            send_btn = None

        if not send_btn:
            # Screenshot for diagnosis
            try:
                await page.screenshot(path="/tmp/linkedin_modal_debug.png", full_page=False, timeout=10000)
                logger.error("Modal screenshot saved to /tmp/linkedin_modal_debug.png")
            except Exception:
                pass
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

    async def _find_profile_connect_btn(self, page):
        """Return the Connect button in the profile header (y < 700px).

        LinkedIn's sidebar 'People you may know' renders 'Invite X to connect'
        buttons — excluded by position. 700px covers tall profile headers.
        Text-based fallback covers aria-label variations across LinkedIn UI versions.
        """
        for sel in [
            'button[aria-label="Connect"]',
            'button[aria-label*="Invite"][aria-label*="connect"]',
            'button[aria-label*="to connect"]',
            'button:has-text("Connect")',   # fallback for aria-label variations
        ]:
            candidates = await page.query_selector_all(sel)
            for btn in candidates:
                if not await btn.is_visible():
                    continue
                box = await btn.bounding_box()
                if box and box["y"] < 700:
                    return btn
        return None

    async def _warmup_session(self, page) -> None:
        """Navigate to /feed/ to trigger LinkedIn's li_at session validation.

        Even if the page redirects to /login/ (expired short-lived cookies),
        the request primes LinkedIn's auth pipeline so that subsequent
        profile page navigations succeed with the persistent li_at cookie.
        """
        try:
            await page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            logger.debug(f"Session warm-up complete (landed at {page.url})")
        except Exception as exc:
            logger.debug(f"Session warm-up failed (non-fatal): {exc}")
