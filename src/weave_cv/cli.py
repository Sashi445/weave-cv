import asyncio
import contextlib
import time
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from weave_cv.agents.orchestrator_agent import stream_resume_pipeline
from weave_cv.batch import BatchFileError, read_job_urls
from weave_cv.config import CONFIG_PATH, load_config, save_config

load_dotenv()

app = typer.Typer(help="Tailor a LaTeX resume to a job posting using AI agents.")
console = Console()

_BANNER = r"""[cyan]  ██╗    ██╗███████╗ █████╗ ██╗   ██╗███████╗     ██████╗██╗   ██╗
  ██║    ██║██╔════╝██╔══██╗██║   ██║██╔════╝    ██╔════╝██║   ██║
  ██║ █╗ ██║█████╗  ███████║██║   ██║█████╗      ██║     ██║   ██║
  ██║███╗██║██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝      ██║     ╚██╗ ██╔╝
  ╚███╔███╔╝███████╗██║  ██║ ╚████╔╝ ███████╗    ╚██████╗ ╚████╔╝
   ╚══╝╚══╝ ╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝     ╚═════╝  ╚═══╝ [/cyan]"""


def _app_version() -> str:
    try:
        return _pkg_version("weave-cv")
    except PackageNotFoundError:
        return "dev"


def _print_banner() -> None:
    console.print(_BANNER)
    console.print(f"[dim]  v{_app_version()}[/dim]\n")

# Loaded once at startup — config values become the *defaults* for
# tailor's --master-resume/--output-dir flags below, so a CLI flag still
# overrides them, but omitting the flag falls back to whatever's saved
# instead of failing or always prompting.
_cfg = load_config()


@app.callback()
def _root() -> None:
    """weave-cv — tailor a LaTeX resume to a job posting using AI agents.

    Registering this callback is what makes `tailor`/`config` real named
    subcommands (`weave-cv tailor ...`) instead of Typer collapsing a
    single-command app to a bare top-level command. Keep this even if
    there's ever only one command again — removing it changes the
    invocation shape.
    """


config_app = typer.Typer(help="View or update saved weave-cv defaults.")
app.add_typer(config_app, name="config")


@config_app.command("set")
def config_set(
    master_resume: Optional[Path] = typer.Option(
        None,
        "--master-resume",
        "-m",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Default master resume .tex path.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", "-o", help="Default output folder."
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="LLM API key, used for every agent call."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", help="Model name used for every agent (e.g. gpt-5-mini, claude-sonnet-4-5)."
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Model provider (e.g. openai, anthropic, google_genai, groq). "
        "Defaults to openai if never set. Determines which API key env var "
        "(dev mode) and which integration package is used.",
    ),
):
    """Save one or more defaults. Flags you omit are left unchanged."""
    if (
        master_resume is None
        and output_dir is None
        and api_key is None
        and model is None
        and provider is None
    ):
        typer.secho("No values given — nothing changed.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    cfg = load_config()
    if master_resume is not None:
        cfg.master_resume = str(master_resume)
    if output_dir is not None:
        cfg.output_dir = str(output_dir)
    if api_key is not None:
        cfg.api_key = api_key
    if model is not None:
        cfg.model = model
    if provider is not None:
        cfg.provider = provider

    save_config(cfg)
    typer.secho(f"Saved to {CONFIG_PATH}", fg=typer.colors.GREEN)


@config_app.command("show")
def config_show():
    """Print the current saved defaults (API key redacted)."""
    if not CONFIG_PATH.exists():
        typer.secho("No config saved yet — see `weave-cv config set --help`.", fg=typer.colors.YELLOW)
        return

    cfg = load_config()
    redacted_key = f"****{cfg.api_key[-4:]}" if cfg.api_key and len(cfg.api_key) > 4 else (
        "****" if cfg.api_key else None
    )
    fields = {
        "master_resume": cfg.master_resume,
        "output_dir": cfg.output_dir,
        "api_key": redacted_key,
        "provider": cfg.provider,
        "model": cfg.model,
    }
    for key, value in fields.items():
        shown = value if value is not None else "[dim](not set)[/dim]"
        console.print(f"{key}: {shown}")


_STAGE_LABELS = {
    "gather_inputs": "Scraping job posting & analyzing resume",
    "tailor": "Tailoring resume",
    "verify": "Verifying tailored resume",
    "generate": "Generating PDF",
}


async def _run_with_progress(job_url: str, cv_path: str, output_dir: str) -> dict:
    """Consumes the pipeline's stage-by-stage stream and shows three
    distinct states per stage: an init line printed the moment a stage
    starts, a live-ticking spinner while it's processing (LangGraph's
    "updates" stream mode only yields once a node *finishes*, so without
    this there's dead silence for however long the slowest stage takes —
    gather_inputs alone routinely runs 60-80s), and a checkmark/failure
    line once it's done. Also accumulates every stage's state update into
    one dict, since streaming mode only yields the diff per node, not the
    final merged state."""
    final_state: dict = {}
    start = time.perf_counter()
    stage_start = start
    current_label = _STAGE_LABELS["gather_inputs"]

    async def _tick(status) -> None:
        while True:
            elapsed = time.perf_counter() - stage_start
            status.update(f"[cyan]{current_label}...[/cyan] [dim]({elapsed:0.0f}s)[/dim]")
            await asyncio.sleep(0.5)

    console.print(f"[cyan]▶[/cyan] {current_label}...")

    with console.status(f"[cyan]{current_label}...[/cyan]", spinner="dots") as status:
        ticker = asyncio.create_task(_tick(status))
        try:
            async for node_name, update in stream_resume_pipeline(job_url, cv_path, output_dir):
                now = time.perf_counter()
                elapsed = now - stage_start
                stage_start = now
                final_state.update(update)
                label = _STAGE_LABELS.get(node_name, node_name)

                if update.get("failed_stage"):
                    console.print(f"[dim]{elapsed:5.1f}s[/dim] [red]✗[/red] {label} failed")
                    break

                if node_name == "gather_inputs":
                    console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}")
                    current_label = _STAGE_LABELS["tailor"]
                elif node_name == "tailor":
                    attempt = update.get("verification_attempts")
                    console.print(
                        f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label} (attempt {attempt})"
                    )
                    current_label = _STAGE_LABELS["verify"]
                elif node_name == "verify":
                    if update.get("verification_passed"):
                        console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label} — passed")
                        current_label = _STAGE_LABELS["generate"]
                    else:
                        feedback = update.get("verification_feedback") or "no reason given"
                        console.print(
                            f"[dim]{elapsed:5.1f}s[/dim] [yellow]…[/yellow] {label} — "
                            f"failed, retrying: {feedback}"
                        )
                        current_label = f"{_STAGE_LABELS['tailor']} (retry)"
                elif node_name == "generate":
                    attempts = update.get("generation_attempts")
                    suffix = f" ({attempts} attempt{'s' if attempts != 1 else ''})" if attempts else ""
                    console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}{suffix}")
                else:
                    console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}")

                # No "next stage" line once generate succeeds — it's the
                # terminal stage, there's nothing left to announce.
                if not update.get("failed_stage") and node_name != "generate":
                    console.print(f"[cyan]▶[/cyan] {current_label}...")
        finally:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker

    total = time.perf_counter() - start
    console.print(f"[dim]Total: {total:.1f}s[/dim]")

    return final_state


@app.command()
def tailor(
    job_url: str = typer.Option(
        ...,
        "--job-url",
        "-j",
        prompt="Enter the job posting URL",
        help="Job posting URL to tailor the resume against.",
    ),
    cv_path: Path = typer.Option(
        _cfg.master_resume if _cfg.master_resume else ...,
        "--master-resume",
        "-m",
        # Only prompt as a last resort — if config already supplies a
        # default, prompting anyway would block non-interactive/scripted
        # runs (Click still prompts even with a default set; it just
        # shows the default in brackets, and aborts instead of falling
        # back to it if stdin isn't attached).
        prompt=False if _cfg.master_resume else "Enter the path to your master resume .tex file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to your master resume .tex file. "
        "Defaults to the saved value (`weave-cv config set --master-resume ...`) if set.",
    ),
    output_dir: Path = typer.Option(
        _cfg.output_dir if _cfg.output_dir else ...,
        "--output-dir",
        "-o",
        prompt=False if _cfg.output_dir else "Enter the folder path to save the generated resume in",
        help="Folder to save the generated .tex/.pdf into (created if missing). "
        "Defaults to the saved value (`weave-cv config set --output-dir ...`) if set.",
    ),
):
    """Tailor --master-resume against --job-url and save the result to --output-dir."""
    _print_banner()
    state = asyncio.run(_run_with_progress(job_url, str(cv_path), str(output_dir)))

    if state.get("failed_stage"):
        typer.secho(
            f"\nFailed at stage '{state['failed_stage']}': {state.get('error')}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    console.print()
    typer.secho(f"Tex saved to: {state['generated_tex_path']}", fg=typer.colors.GREEN)
    typer.secho(f"PDF saved to: {state['generated_pdf_path']}", fg=typer.colors.GREEN)


def _short_label(url: str, max_len: int = 57) -> str:
    return url if len(url) <= max_len else url[: max_len - 3] + "..."


async def _run_one_batch_job(
    url: str, cv_path: str, output_dir: str, semaphore: asyncio.Semaphore,
    progress: Progress, task_id,
) -> dict:
    """Runs one job's full pipeline, updating its own Progress row as it
    advances through stages — safe to run concurrently with other jobs'
    calls to this function since each pipeline invocation is independent
    (see agents/orchestrator_agent.py: no shared mutable state across
    concurrent .astream() calls, and langchain_mcp_adapters opens a fresh
    subprocess session per tool/prompt call rather than sharing one)."""
    label = _short_label(url)
    final_state: dict = {"job_url": url}

    async with semaphore:
        progress.update(task_id, description=f"{label} — queued...")
        try:
            async for node_name, update in stream_resume_pipeline(url, cv_path, output_dir):
                final_state.update(update)
                stage_label = _STAGE_LABELS.get(node_name, node_name)

                if update.get("failed_stage"):
                    progress.update(
                        task_id, description=f"[red]✗[/red] {label} — failed at {stage_label}"
                    )
                    break

                progress.update(task_id, description=f"{label} — {stage_label}")
            else:
                # Loop exhausted without break == every stage succeeded.
                jd_profile = final_state.get("jd_profile")
                company = getattr(jd_profile, "company_name", None) if jd_profile else None
                progress.update(task_id, description=f"[green]✓[/green] {company or label} — done")
        except Exception as e:
            final_state["failed_stage"] = "unexpected"
            final_state["error"] = str(e)
            progress.update(task_id, description=f"[red]✗[/red] {label} — unexpected error: {e}")

    return final_state


async def _run_batch(urls: list[str], cv_path: str, output_dir: str, concurrency: int) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_ids = [progress.add_task(_short_label(url), total=None) for url in urls]
        return await asyncio.gather(*(
            _run_one_batch_job(url, cv_path, output_dir, semaphore, progress, task_id)
            for url, task_id in zip(urls, task_ids)
        ))


def _print_batch_summary(results: list[dict]) -> None:
    table = Table(title="Batch tailoring summary")
    table.add_column("Job URL")
    table.add_column("Status")
    table.add_column("Output / Error")

    succeeded = 0
    for r in results:
        url = r.get("job_url", "?")
        if r.get("failed_stage"):
            table.add_row(url, f"[red]failed ({r['failed_stage']})[/red]", str(r.get("error", ""))[:100])
        else:
            succeeded += 1
            table.add_row(url, "[green]done[/green]", r.get("generated_pdf_path", ""))

    console.print()
    console.print(table)
    console.print(f"\n{succeeded}/{len(results)} succeeded.")


@app.command()
def batch(
    file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="CSV or XLSX file with a job_url/url/link/job_link header column.",
    ),
    cv_path: Path = typer.Option(
        _cfg.master_resume if _cfg.master_resume else ...,
        "--master-resume",
        "-m",
        prompt=False if _cfg.master_resume else "Enter the path to your master resume .tex file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to your master resume .tex file, reused for every job in the batch. "
        "Defaults to the saved value (`weave-cv config set --master-resume ...`) if set.",
    ),
    output_dir: Path = typer.Option(
        _cfg.output_dir if _cfg.output_dir else ...,
        "--output-dir",
        "-o",
        prompt=False if _cfg.output_dir else "Enter the folder path to save the generated resume in",
        help="Folder every generated .tex/.pdf is saved into (created if missing). "
        "Defaults to the saved value (`weave-cv config set --output-dir ...`) if set.",
    ),
    concurrency: int = typer.Option(
        3, "--concurrency", "-c", min=1,
        help="Max number of job postings to process in parallel.",
    ),
):
    """Tailor --master-resume against every job URL in --file (one output
    per job, same output folder), up to --concurrency at a time."""
    _print_banner()
    try:
        urls = read_job_urls(str(file))
    except BatchFileError as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(code=1)

    console.print(f"Found {len(urls)} job URL(s) in {file}. Processing up to {concurrency} at a time.\n")

    results = asyncio.run(_run_batch(urls, str(cv_path), str(output_dir), concurrency))
    _print_batch_summary(results)

    if any(r.get("failed_stage") for r in results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
