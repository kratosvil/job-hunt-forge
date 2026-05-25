"""
Pipeline orchestrator — runs the full job-hunt cycle end to end.

Execution order:
  1. Scrape   → fetch new job listings from LinkedIn / Indeed
  2. Analyze  → score each JD against master_cv.json (done inside scrape)
  3. Find     → discover hiring managers for every qualified job
  4. Outreach → send personalized messages within daily limits
  5. Report   → print a summary of today's run

Designed to run once per day (cron or manual trigger).
Each stage is idempotent — re-running skips already-processed records.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.database.db_manager import get_session, init_db
from src.database.models import Job, HiringManager, JobStatus, ManagerStatus
from src.scrapers.linkedin_scraper import LinkedInScraper
from src.scrapers.indeed_scraper import IndeedScraper
from src.scrapers.manager_finder import ManagerFinder
from src.executors.outreach_bot import OutreachBot

console = Console()


@dataclass
class PipelineResult:
    jobs_scraped: int = 0
    jobs_qualified: int = 0
    jobs_skipped: int = 0
    managers_found: int = 0
    messages_sent: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def run(
    *,
    skip_scrape: bool = False,
    skip_outreach: bool = False,
    source: str = "linkedin",
    limit: int = 0,
    managers_limit: int = 0,
) -> PipelineResult:
    """
    Execute the full pipeline.

    Args:
        skip_scrape:   Skip scraping (use existing DB jobs). Useful for outreach-only runs.
        skip_outreach: Scrape and analyze but do not send messages.
        source:        Which job board to scrape — linkedin | indeed | all
    """
    init_db()
    result = PipelineResult()

    # ── Stage 1: Scrape ──────────────────────────────────────────────────
    if not skip_scrape:
        console.print("\n[bold cyan]Stage 1/4 — Scraping job listings...[/bold cyan]")
        result.jobs_scraped, result.jobs_qualified, result.jobs_skipped = (
            await _run_scrape(source, limit=limit)
        )
        console.print(
            f"  Scraped: [green]{result.jobs_scraped}[/green] | "
            f"Qualified: [green]{result.jobs_qualified}[/green] | "
            f"Skipped: [yellow]{result.jobs_skipped}[/yellow]"
        )
    else:
        console.print("\n[yellow]Stage 1/4 — Scrape skipped.[/yellow]")

    # ── Stage 2: Find managers ───────────────────────────────────────────
    console.print("\n[bold cyan]Stage 2/4 — Discovering hiring managers...[/bold cyan]")
    try:
        async with ManagerFinder() as finder:
            result.managers_found = await finder.find_for_qualified_jobs(limit=managers_limit)
        console.print(f"  Managers queued: [green]{result.managers_found}[/green]")
    except Exception as exc:
        msg = f"Manager finder failed: {exc}"
        logger.error(msg)
        result.errors.append(msg)

    # ── Stage 3: Outreach ────────────────────────────────────────────────
    if not skip_outreach:
        console.print("\n[bold cyan]Stage 3/4 — Running outreach...[/bold cyan]")
        try:
            async with OutreachBot() as bot:
                result.messages_sent = await bot.run()
            console.print(f"  Messages sent: [green]{result.messages_sent}[/green]")
        except Exception as exc:
            msg = f"Outreach failed: {exc}"
            logger.error(msg)
            result.errors.append(msg)
    else:
        console.print("\n[yellow]Stage 3/4 — Outreach skipped.[/yellow]")

    # ── Stage 4: Report ──────────────────────────────────────────────────
    console.print("\n[bold cyan]Stage 4/4 — Pipeline report[/bold cyan]")
    _print_report(result)

    return result


async def _run_scrape(source: str, limit: int = 0) -> tuple[int, int, int]:
    import json
    from src.intelligence.jd_analyzer import analyze
    from src.database.models import JobStatus

    scrapers = []
    if source in ("linkedin", "all"):
        scrapers.append(LinkedInScraper())
    if source in ("indeed", "all"):
        scrapers.append(IndeedScraper())

    total = qualified = skipped = 0

    for scraper_cls in scrapers:
        async with scraper_cls as s:
            async for raw in s.scrape():
                if limit and total >= limit:
                    logger.info(f"Limit of {limit} jobs reached — stopping scrape.")
                    return total, qualified, skipped

                if not raw.get("url") or not raw.get("jd_text"):
                    continue

                url = raw["url"]

                # Skip Bedrock call if URL already in DB — saves money on repeated runs
                with get_session() as session:
                    existing = session.query(Job).filter(Job.url == url).first()
                    if existing:
                        logger.debug(f"Already in DB, skipping: {url}")
                        continue

                try:
                    analysis = analyze(raw["jd_text"])
                    recommended = analysis.get("application_recommended", False)
                    fit = analysis.get("fit_score", 0.0)

                    job = Job(
                        url=url,
                        title=raw["title"].strip(),
                        company=raw["company"].strip(),
                        location=raw.get("location", ""),
                        jd_text=raw["jd_text"],
                        fit_score=fit,
                        matched_skills=json.dumps(analysis.get("matched_skills", [])),
                        missing_skills=json.dumps(analysis.get("missing_skills", [])),
                        growth_signals=json.dumps(analysis.get("company_growth_signals", [])),
                        hiring_manager_signals=json.dumps(analysis.get("hiring_manager_signals", [])),
                        salary_range=analysis.get("salary_range_visible"),
                        remote_friendly=analysis.get("remote_friendly"),
                        source=raw["source"],
                        status=JobStatus.ANALYZED if recommended else JobStatus.SKIPPED,
                    )
                    with get_session() as session:
                        session.add(job)

                    total += 1
                    if recommended:
                        qualified += 1
                    else:
                        skipped += 1

                except Exception as exc:
                    logger.error(f"Scrape error for {url}: {exc}")

    return total, qualified, skipped


def _print_report(result: PipelineResult) -> None:
    with get_session() as session:
        total_jobs = session.query(Job).count()
        total_qualified = (
            session.query(Job).filter(Job.status == JobStatus.ANALYZED).count()
        )
        total_managers = session.query(HiringManager).count()
        total_sent = (
            session.query(HiringManager)
            .filter(HiringManager.message_sent.is_(True))
            .count()
        )
        total_replied = (
            session.query(HiringManager)
            .filter(HiringManager.status == ManagerStatus.REPLIED)
            .count()
        )

    table = Table(title="Pipeline Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("This run", style="green")
    table.add_column("All time", style="magenta")

    table.add_row("Jobs scraped", str(result.jobs_scraped), str(total_jobs))
    table.add_row("Jobs qualified (fit ≥ threshold)", str(result.jobs_qualified), str(total_qualified))
    table.add_row("Managers found", str(result.managers_found), str(total_managers))
    table.add_row("Messages sent", str(result.messages_sent), str(total_sent))
    table.add_row("Replies received", "—", str(total_replied))

    if result.errors:
        table.add_row("[red]Errors[/red]", str(len(result.errors)), "")

    elapsed = (datetime.now(timezone.utc) - result.started_at).seconds
    table.add_row("Duration", f"{elapsed}s", "")

    console.print(table)

    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for err in result.errors:
            console.print(f"  • {err}")
