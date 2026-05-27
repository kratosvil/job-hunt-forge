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
    "recruiter", "recruitment", "headhunter", "head hunter",
    "talent acquisition", "talent advisor", "talent partner",
    "head of talent", "head of recruiting", "head of people",
    "hr ", "human resources", "people operations", "people partner",
    "technical recruiter", "tech recruiter", "sourcer", "sourcing",
    "staffing", "hiring manager",
]

# Direct hiring managers — close enough to the role to act on a cold message
_TECHNICAL_KEYWORDS = [
    "engineering manager", "engineering lead", "engineering leader",
    "team lead", "tech lead", "technical lead",
    "head of engineering", "head of platform", "head of infrastructure",
    "head of devops", "head of mlops", "head of data engineering",
    "head of sre", "head of cloud", "head of ai",
    "director of engineering", "director of platform", "director of infrastructure",
    "director of devops", "director of cloud", "director of sre",
    "director of mlops", "director of data engineering",
    "staff engineer", "principal engineer",
    "staff software", "principal software",
    "architect",
]

# Hard skip — always skip even if a positive keyword also matches (too senior)
_HARD_SKIP_KEYWORDS = [
    "cto", "ceo", "coo", "cpo", "cfo", "chief",
    "president", "vice president", "vp ", "vp,", "vp-",
    "svp", "evp", "avp",
    "founder", "co-founder",
]

# Soft skip — skip only when no positive (recruiter/technical) keyword matches
_SOFT_SKIP_KEYWORDS = [
    "software engineer", "senior software engineer",
    "backend", "frontend", "fullstack", "full stack",
    "test engineer", "automation engineer", "qa engineer", "qa analyst",
    "data analyst", "business analyst", "sales engineer", "account manager",
    "product manager", "scrum master", "agile coach",
]


def _classify_manager(role: str) -> str:
    """Returns 'technical', 'recruiter', or 'skip'."""
    if not role:
        return "skip"
    role_lower = role.lower()

    # Hard skip always wins — use word boundaries to avoid false matches
    # e.g. "cto" inside "director", "coo" inside "coordinator"
    import re
    if any(re.search(r"\b" + re.escape(kw.strip()) + r"\b", role_lower) for kw in _HARD_SKIP_KEYWORDS):
        return "skip"
    # Positive match wins over soft-skip (e.g. "Software Engineering Leader")
    if any(kw in role_lower for kw in _RECRUITER_KEYWORDS):
        return "recruiter"
    if any(kw in role_lower for kw in _TECHNICAL_KEYWORDS):
        return "technical"
    # Peer-level or irrelevant — no positive match
    if any(kw in role_lower for kw in _SOFT_SKIP_KEYWORDS):
        return "skip"
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
        # Disable LinkedIn overlays that intercept pointer events.
        # Use pointer-events:none instead of .remove() — removing parent divs
        # can accidentally delete profile action buttons (Connect, Message, More).
        try:
            await page.evaluate("""
                () => {
                    // Known class selectors (may rotate with LinkedIn deploys)
                    ['div._607fba13', 'div._2a82eb9e', '[data-test-premium-custom-promo]']
                        .forEach(sel => document.querySelectorAll(sel).forEach(el => {
                            el.style.pointerEvents = 'none';
                        }));
                    // Content-based fallback: walk up to the nearest fixed/sticky ancestor
                    document.querySelectorAll('a').forEach(a => {
                        if (a.textContent.includes('Reactivate Premium')) {
                            let p = a.parentElement;
                            while (p && p !== document.body) {
                                const pos = window.getComputedStyle(p).position;
                                if (pos === 'fixed' || pos === 'sticky') {
                                    p.style.pointerEvents = 'none';
                                    return;
                                }
                                p = p.parentElement;
                            }
                            a.style.pointerEvents = 'none';
                        }
                    });
                }
            """)
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
                # JS click bypasses any fixed overlay intercepting pointer events
                await page.evaluate("el => el.click()", more_btn)
                await self._human_delay()
                for sel in [
                    'div[aria-label*="connect" i]',
                    'li[aria-label*="connect" i]',
                    'span:has-text("Connect")',
                    'span:has-text("Conectar")',
                    'button:has-text("Connect")',
                    'button:has-text("Conectar")',
                    '[role="menuitem"]:has-text("Connect")',
                    '[role="menuitem"]:has-text("Conectar")',
                ]:
                    connect_btn = await page.query_selector(sel)
                    if connect_btn and await connect_btn.is_visible():
                        break
                    connect_btn = None

        if not connect_btn:
            raise RuntimeError(
                "Connect button not found — already connected, following only, or profile restricted."
            )

        await page.evaluate("el => el.click()", connect_btn)

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

        # "Add a note" — English + Spanish aria-label / text variants
        add_note_btn = None
        for sel in [
            'button[aria-label="Add a note"]',
            'button[aria-label*="note"]',
            'button[aria-label*="nota"]',
            'button:has-text("Add a note")',
            'button:has-text("Agregar nota")',
        ]:
            add_note_btn = await page.query_selector(sel)
            if add_note_btn and await add_note_btn.is_visible():
                break
            add_note_btn = None

        # Skip "Add a note" — LinkedIn Premium required to attach a note on
        # connection requests for most profiles. Clicking it opens a Premium
        # upsell that changes modal state and hides "Send without a note".
        # Re-enable this block once a Premium subscription is active.
        if False and add_note_btn:  # noqa: SIM210  (disabled until Premium)
            await add_note_btn.click()
            await self._human_delay()
            try:
                textarea = await page.wait_for_selector(
                    'textarea[name="message"]', timeout=8000
                )
                await textarea.fill(note)
                await self._human_delay()
            except Exception:
                logger.warning(
                    f"Note textarea unavailable for {manager.name} — sending without note."
                )
        else:
            logger.info(
                f"Sending without note for {manager.name} (Premium required for notes)."
            )

        # "Send" — English + Spanish aria-label / text variants
        send_btn = None
        for sel in [
            'button[aria-label="Send now"]',
            'button[aria-label="Send without a note"]',
            'button[aria-label*="Send"]',
            'button[aria-label*="nviar"]',       # Enviar / Enviar ahora / Enviar sin nota
            'button:has-text("Send now")',
            'button:has-text("Send without a note")',
            'button:has-text("Send")',
            'button:has-text("Enviar ahora")',
            'button:has-text("Enviar sin nota")',
            'button:has-text("Enviar")',
        ]:
            send_btn = await page.query_selector(sel)
            if send_btn and await send_btn.is_visible():
                break
            send_btn = None

        if not send_btn:
            try:
                await page.screenshot(path="/tmp/linkedin_modal_debug.png", full_page=False, timeout=10000)
                logger.error("Modal screenshot saved to /tmp/linkedin_modal_debug.png")
                # Dump all visible button labels for diagnosis
                btns = await page.query_selector_all("button")
                labels = []
                for b in btns:
                    if await b.is_visible():
                        lbl = await b.get_attribute("aria-label") or ""
                        txt = (await b.inner_text()).strip()[:40]
                        labels.append(f"aria='{lbl}' text='{txt}'")
                logger.error(f"Visible buttons: {labels}")
            except Exception:
                pass
            raise RuntimeError("Send button not found.")

        await page.evaluate("el => el.click()", send_btn)

    # ── DB helpers ───────────────────────────────────────────────────────────

    def _get_pending_managers(self) -> list[tuple[HiringManager, Job]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.RECENCY_HOURS)
        with get_session() as session:
            return (
                session.query(HiringManager, Job)
                .join(Job, HiringManager.job_id == Job.id)
                .filter(
                    HiringManager.status == ManagerStatus.PENDING,
                    HiringManager.found_at >= cutoff,
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

        Sidebar 'People you may know' buttons have aria-label='Invite X to connect'
        — we skip those. Exact-match selectors first; text fallback last with
        an 'Invite' guard to avoid sidebar false-positives.
        """
        # Exact-match selectors (English + Spanish) — never match sidebar buttons
        for sel in [
            'button[aria-label="Connect"]',
            'button[aria-label="Conectar"]',
        ]:
            candidates = await page.query_selector_all(sel)
            for btn in candidates:
                if not await btn.is_visible():
                    continue
                box = await btn.bounding_box()
                if box and box["y"] < 700:
                    return btn

        # Text-based fallback — skip any button whose aria-label contains "Invite"
        # (those are sidebar 'Invite X to connect' suggestions, not the profile button)
        for btn in await page.query_selector_all(
            'button:has-text("Connect"), button:has-text("Conectar")'
        ):
            if not await btn.is_visible():
                continue
            aria = (await btn.get_attribute("aria-label") or "").lower()
            if "invite" in aria:
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
