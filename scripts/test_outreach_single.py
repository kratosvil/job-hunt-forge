"""
Test outreach with a single manager by ID.
Usage: .venv/bin/python scripts/test_outreach_single.py <manager_id>
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from loguru import logger

from src.database.db_manager import get_session
from src.database.models import HiringManager, Job, ManagerStatus
from src.executors.outreach_bot import OutreachBot, _classify_manager
from src.intelligence.pitch_generator import generate_connection_note


async def test_single(manager_id: int):
    with get_session() as session:
        mgr = session.get(HiringManager, manager_id)
        if not mgr:
            logger.error(f"Manager {manager_id} not found.")
            return
        job = session.get(Job, mgr.job_id)
        if not job:
            logger.error(f"Job {mgr.job_id} not found.")
            return

        # Capture all needed data before session closes
        data = {
            "id": mgr.id,
            "name": mgr.name,
            "role": mgr.role or "",
            "company": mgr.company,
            "linkedin_url": mgr.linkedin_url,
        }
        matched = json.loads(job.matched_skills or "[]")
        growth = json.loads(job.growth_signals or "[]")
        job_title = job.title

    logger.info(f"Test target: {data['name']} | {data['role']} | {data['company']}")
    logger.info(f"LinkedIn URL: {data['linkedin_url']}")

    note_type = _classify_manager(data["role"])
    logger.info(f"Classification: {note_type}")
    if note_type == "skip":
        logger.warning("Role classified as SKIP — forcing 'technical' for test.")
        note_type = "technical"

    note = generate_connection_note(
        company_name=data["company"],
        job_title=job_title,
        manager_name=data["name"],
        matched_skills=matched,
        growth_signals=growth,
        note_type=note_type,
    )
    logger.info(f"Generated note ({len(note)} chars):\n{note}")

    # SimpleNamespace avoids DetachedInstanceError — _send_connection_request
    # only needs id, name, company, linkedin_url.
    mgr_ns = SimpleNamespace(**data)

    bot = OutreachBot()
    async with bot:
        page = await bot._new_page()
        try:
            # Navigate to profile first so we can take a screenshot on failure
            import asyncio as _asyncio
            await page.goto(data["linkedin_url"], wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await _asyncio.sleep(3)
            await page.screenshot(path="/tmp/test_profile_loaded.png", full_page=False)
            logger.info("Screenshot saved to /tmp/test_profile_loaded.png — check the page state.")

            await bot._send_connection_request(page, mgr_ns, note)

            # Mark sent
            with get_session() as session:
                m = session.get(HiringManager, manager_id)
                if m:
                    m.status = ManagerStatus.CONNECTION_REQUESTED
                    m.connection_note = note
                    m.contacted_at = datetime.now(timezone.utc)
            logger.success(f"Connection request sent to {data['name']}. Status → CONNECTION_REQUESTED.")
        except RuntimeError as exc:
            logger.warning(f"Permanent failure (skipping): {exc}")
            with get_session() as session:
                m = session.get(HiringManager, manager_id)
                if m:
                    m.status = ManagerStatus.SKIPPED
        except Exception as exc:
            logger.error(f"Transient failure: {exc}")
        finally:
            await page.close()


if __name__ == "__main__":
    manager_id = int(sys.argv[1]) if len(sys.argv) > 1 else 214
    asyncio.run(test_single(manager_id))
