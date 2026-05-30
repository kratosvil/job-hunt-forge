import asyncio
import datetime

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.database.db_manager import init_db, get_session
from src.database.models import Job, HiringManager

app = typer.Typer(help="Job-Hunt-Forge — AI-powered job search automation.")
console = Console()


@app.callback(invoke_without_command=True)
def startup(ctx: typer.Context) -> None:
    init_db()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def scrape(
    source: str = typer.Option("linkedin", help="linkedin | indeed | all"),
    limit: int = typer.Option(20, "--limit", help="Max new jobs to analyze per run (0=unlimited)."),
) -> None:
    """Scrape job listings and store them in the database."""
    from src.scrapers.linkedin_scraper import LinkedInScraper
    from src.scrapers.indeed_scraper import IndeedScraper
    from src.intelligence.jd_analyzer import analyze
    import json
    from sqlalchemy.exc import IntegrityError
    from src.database.models import JobStatus

    async def _run():
        scrapers = []
        if source in ("linkedin", "all"):
            scrapers.append(LinkedInScraper())
        if source in ("indeed", "all"):
            scrapers.append(IndeedScraper())

        analyzed = 0

        for scraper in scrapers:
            async with scraper as s:
                async for raw in s.scrape():
                    if limit and analyzed >= limit:
                        logger.info(f"Limit of {limit} jobs reached — stopping scrape.")
                        return
                    if not raw.get("url") or not raw.get("jd_text"):
                        continue
                    try:
                        analysis = analyze(raw["jd_text"])
                        job = Job(
                            url=raw["url"],
                            title=raw["title"].strip(),
                            company=raw["company"].strip(),
                            location=raw.get("location", ""),
                            jd_text=raw["jd_text"],
                            fit_score=analysis.get("fit_score"),
                            matched_skills=json.dumps(analysis.get("matched_skills", [])),
                            missing_skills=json.dumps(analysis.get("missing_skills", [])),
                            growth_signals=json.dumps(analysis.get("company_growth_signals", [])),
                            hiring_manager_signals=json.dumps(analysis.get("hiring_manager_signals", [])),
                            salary_range=analysis.get("salary_range_visible"),
                            remote_friendly=analysis.get("remote_friendly"),
                            source=raw["source"],
                            status=JobStatus.ANALYZED
                            if analysis.get("application_recommended")
                            else JobStatus.SKIPPED,
                        )
                        with get_session() as session:
                            session.add(job)
                        analyzed += 1
                        logger.info(
                            f"[{analyzed}/{limit or '∞'}] Saved: {job.title} @ {job.company} "
                            f"(fit={job.fit_score:.2f}, recommended={analysis.get('application_recommended')})"
                        )
                    except IntegrityError:
                        logger.debug(f"Duplicate skipped: {raw['url']}")
                    except Exception as exc:
                        logger.error(f"Error processing job: {exc}")

    asyncio.run(_run())


@app.command()
def outreach() -> None:
    """Send personalized LinkedIn messages to hiring managers."""
    from src.executors.outreach_bot import OutreachBot

    async def _run():
        async with OutreachBot() as bot:
            sent = await bot.run()
            console.print(f"[green]Outreach complete — {sent} messages sent.[/green]")

    asyncio.run(_run())


@app.command()
def analyze() -> None:
    """Re-analyze all pending jobs in the database."""
    console.print("[yellow]Re-analysis of pending jobs — coming in next phase.[/yellow]")


@app.command()
def apply() -> None:
    """Auto-fill and queue job applications (Phase 2)."""
    console.print("[yellow]Auto-apply — Phase 2 feature. Run outreach first.[/yellow]")


@app.command(name="easy-apply")
def easy_apply(
    limit: int = typer.Option(50, "--limit", help="Max jobs to scan per run."),
    top: int = typer.Option(10, "--top", help="Top N qualifying jobs to show, ranked by fit score."),
    output: str = typer.Option("data/easy_apply.txt", "--output", help="Path for output file with qualifying job links."),
) -> None:
    """Scan LinkedIn Easy Apply jobs (48h) and list top N qualifying links for manual application."""
    from src.scrapers.easy_apply_scraper import EasyApplyScraper
    from src.intelligence.jd_analyzer import analyze
    from src.database.models import Job, JobStatus
    from sqlalchemy.exc import IntegrityError
    import json

    async def _run():
        results = []
        scanned = 0

        async with EasyApplyScraper() as scraper:
            async for raw in scraper.scrape():
                if limit and scanned >= limit:
                    break
                if not raw.get("url") or not raw.get("jd_text"):
                    continue

                url = raw["url"]
                scanned += 1

                # Skip if already in DB — reuse cached fit score
                with get_session() as session:
                    existing = session.query(Job).filter(Job.url == url).first()
                    if existing:
                        if existing.source == "linkedin_easy_apply" and existing.fit_score:
                            results.append({
                                "url": url,
                                "title": existing.title,
                                "company": existing.company,
                                "fit": existing.fit_score,
                            })
                        continue

                try:
                    analysis = analyze(raw["jd_text"])
                    fit = analysis.get("fit_score", 0.0)
                    recommended = analysis.get("application_recommended", False)

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
                        source="linkedin_easy_apply",
                        status=JobStatus.ANALYZED if recommended else JobStatus.SKIPPED,
                    )
                    with get_session() as session:
                        session.add(job)

                    if recommended:
                        results.append({
                            "url": url,
                            "title": raw["title"].strip(),
                            "company": raw["company"].strip(),
                            "fit": fit,
                        })

                    logger.info(
                        f"[{scanned}/{limit}] {raw['title'][:45]} @ {raw['company'][:25]} "
                        f"fit={fit:.0%} {'✓' if recommended else '✗'}"
                    )
                except IntegrityError:
                    logger.debug(f"Duplicate skipped: {url}")
                except Exception as exc:
                    logger.error(f"Error processing {url}: {exc}")

        results.sort(key=lambda x: x["fit"], reverse=True)
        top_results = results[:top]

        table = Table(title=f"Easy Apply — Top {len(top_results)} jobs (48h · fit ≥ {settings.min_fit_score:.0%} · scanned {scanned})")
        table.add_column("#", style="dim", width=3)
        table.add_column("Fit", style="green", width=6)
        table.add_column("Title", style="cyan")
        table.add_column("Company", style="magenta")
        table.add_column("URL")

        for i, r in enumerate(top_results, 1):
            table.add_row(
                str(i),
                f"{r['fit']:.0%}",
                r["title"][:50],
                r["company"][:28],
                r["url"],
            )
        console.print(table)

        with open(output, "w") as f:
            f.write(f"Easy Apply — Top {len(top_results)} jobs · 48h · scanned {scanned} · {datetime.date.today()}\n")
            f.write("=" * 70 + "\n\n")
            for i, r in enumerate(top_results, 1):
                f.write(f"{i}. [{r['fit']:.0%}] {r['title']} @ {r['company']}\n")
                f.write(f"   {r['url']}\n\n")

        console.print(f"[green]Saved top {len(top_results)} links → {output}[/green]")

    asyncio.run(_run())


@app.command()
def pipeline(
    skip_scrape: bool = typer.Option(False, "--skip-scrape", help="Skip scraping stage."),
    skip_outreach: bool = typer.Option(False, "--skip-outreach", help="Skip outreach stage."),
    source: str = typer.Option("linkedin", help="linkedin | indeed | all"),
    limit: int = typer.Option(0, "--limit", help="Max new jobs to analyze (0=unlimited). Use for test runs."),
    managers_limit: int = typer.Option(0, "--managers-limit", help="Max jobs to search managers for per run (0=unlimited)."),
) -> None:
    """Run the full pipeline: scrape → find managers → outreach → report."""
    from src.pipeline import run as run_pipeline
    asyncio.run(run_pipeline(
        skip_scrape=skip_scrape,
        skip_outreach=skip_outreach,
        source=source,
        limit=limit,
        managers_limit=managers_limit,
    ))


@app.command()
def status() -> None:
    """Show current database statistics."""
    with get_session() as session:
        jobs = session.query(Job).all()
        managers = session.query(HiringManager).all()

    table = Table(title="Job-Hunt-Forge Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    from collections import Counter
    job_counts = Counter(j.status.value for j in jobs)
    for status_name, count in sorted(job_counts.items()):
        table.add_row(f"Jobs — {status_name}", str(count))

    mgr_counts = Counter(m.status.value for m in managers)
    for status_name, count in sorted(mgr_counts.items()):
        table.add_row(f"Managers — {status_name}", str(count))

    table.add_row("Total jobs", str(len(jobs)))
    table.add_row("Total managers", str(len(managers)))
    console.print(table)


if __name__ == "__main__":
    app()
