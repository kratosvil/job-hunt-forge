"""
End-to-end intelligence demo — uses real master_cv.json via production modules.
Simulates what the pipeline does per job: analyze JD → score → generate pitch.
No LinkedIn session needed.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.intelligence.jd_analyzer import analyze
from src.intelligence.pitch_generator import generate_pitch

console = Console()

SAMPLE_JD = """
Senior MLOps / AI Infrastructure Engineer — Remote (USA/Europe)
Company: Acme AI — Series B, 120 employees, YC W21

We are building the next generation of agentic AI infrastructure for enterprise customers.
You will own our ML platform end-to-end: model training pipelines, inference infrastructure,
observability, and the internal tooling our applied AI team uses daily.

Responsibilities:
- Design and operate GPU training clusters on AWS (SageMaker, EKS, EC2 Spot)
- Build and maintain CI/CD pipelines for model training and deployment (MLflow, DVC, GitHub Actions)
- Implement real-time inference infrastructure with sub-100ms p99 latency (Triton, TorchServe)
- Instrument observability for model drift, data quality, and cost anomalies (Prometheus, Grafana)
- Work with applied AI team to productionize LLM-based agents (LangChain, LlamaIndex)
- Own Terraform modules for all ML infrastructure across dev/staging/prod

Requirements:
- 5+ years of platform/infrastructure engineering
- Strong Python and infrastructure-as-code (Terraform required)
- Hands-on with Kubernetes and container orchestration
- Experience with AWS ML services (SageMaker, Bedrock, or equivalent)
- Exposure to LLM fine-tuning or RAG pipelines is a strong plus
- Comfortable working async across timezones (we have no offices)

Compensation: $130k–$160k USD/year + equity. Fully remote.
"""


def main() -> None:
    from config.settings import settings
    console.print(Panel(
        f"[bold]Provider:[/bold] {settings.default_llm_provider}  |  "
        f"[bold]Model:[/bold] {settings.bedrock_model_id if settings.default_llm_provider == 'bedrock' else settings.ollama_model}",
        title="Job-Hunt-Forge — Intelligence Demo",
        border_style="cyan"
    ))

    # ── Stage 1: JD Analysis ─────────────────────────────────────────────
    console.print("\n[bold cyan]Stage 1/2 — Analyzing job description...[/bold cyan]")
    t0 = time.time()
    analysis = analyze(SAMPLE_JD)
    elapsed = time.time() - t0

    score = analysis.get("fit_score", 0)
    recommended = analysis.get("application_recommended", False)
    matched = analysis.get("matched_skills", [])
    missing = analysis.get("missing_skills", [])
    growth = analysis.get("company_growth_signals", [])

    score_color = "green" if score >= 0.75 else "yellow" if score >= 0.65 else "red"
    verdict = "[green]APPLY[/green]" if recommended else "[red]SKIP[/red]"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold cyan", width=22)
    table.add_column("Value")
    table.add_row("Fit score", f"[{score_color}]{score}[/{score_color}]")
    table.add_row("Verdict", verdict)
    table.add_row("Role level match", analysis.get("role_level_match", ""))
    table.add_row("Remote", "yes" if analysis.get("remote_friendly") else "no")
    table.add_row("Salary visible", analysis.get("salary_range_visible") or "not disclosed")
    table.add_row("Matched skills", f"[green]{len(matched)}[/green]  " + ", ".join(matched[:5]) + ("..." if len(matched) > 5 else ""))
    table.add_row("Missing skills", f"[yellow]{len(missing)}[/yellow]  " + ", ".join(missing) if missing else "[green]none[/green]")
    table.add_row("Growth signals", ", ".join(growth) if growth else "none")
    table.add_row("Duration", f"{elapsed:.1f}s")
    console.print(table)

    if not recommended:
        console.print("\n[red]Job does not meet threshold — pipeline would skip outreach.[/red]")
        console.print(f"Reason: {analysis.get('rejection_reason')}")
        return

    # ── Stage 2: Pitch Generation ────────────────────────────────────────
    console.print("\n[bold cyan]Stage 2/2 — Generating outreach message...[/bold cyan]")
    t0 = time.time()
    pitch = generate_pitch(
        company_name="Acme AI",
        job_title="Senior MLOps / AI Infrastructure Engineer",
        manager_name="Alex Chen",
        manager_title="VP of Engineering",
        matched_skills=matched,
        growth_signals=growth,
    )
    elapsed = time.time() - t0

    console.print(Panel(
        pitch,
        title="[bold green]Generated Message — Alex Chen, VP Engineering @ Acme AI[/bold green]",
        border_style="green",
        subtitle=f"{elapsed:.1f}s"
    ))

    console.print("\n[dim]In production: this message is sent via LinkedIn to the hiring manager.[/dim]")
    console.print("[dim]Manager record saved to DB with status MESSAGE_QUEUED.[/dim]")
    console.print("[dim]Daily limit tracked — max 20 messages/day to avoid LinkedIn ban.[/dim]")


if __name__ == "__main__":
    main()
