import asyncio
import contextlib
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from weave_cv.agents.apply_agent import ApplyResult, apply_to_job
from weave_cv.agents.candidate_role_fit_agent import get_or_build_candidate_role_fit
from weave_cv.agents.cv_analyzer import analyze_cv
from weave_cv.agents.job_discovery_agent import RelevantJob, stream_discover_jobs
from weave_cv.agents.orchestrator_agent import MAX_PAGE_FIT_ATTEMPTS, stream_resume_pipeline
from weave_cv.batch import BatchFileError, read_job_urls
from weave_cv.config import CONFIG_PATH, load_config, save_config
from weave_cv.services import candidate_role_fit_cache, cv_cache, db, jd_cache

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
    tavily_api_key: Optional[str] = typer.Option(
        None,
        "--tavily-api-key",
        help="Tavily API key, used by `discover` for job-posting search "
        "(free at tavily.com, no card required). Only needed if you use "
        "`discover` — the other commands don't touch it.",
    ),
):
    """Save one or more defaults. Flags you omit are left unchanged."""
    if (
        master_resume is None
        and output_dir is None
        and api_key is None
        and model is None
        and provider is None
        and tavily_api_key is None
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
    if tavily_api_key is not None:
        cfg.tavily_api_key = tavily_api_key

    save_config(cfg)
    typer.secho(f"Saved to {CONFIG_PATH}", fg=typer.colors.GREEN)


@config_app.command("show")
def config_show():
    """Print the current saved defaults (API key redacted)."""
    if not CONFIG_PATH.exists():
        typer.secho("No config saved yet — see `weave-cv config set --help`.", fg=typer.colors.YELLOW)
        return

    cfg = load_config()

    def _redact(key: str | None) -> str | None:
        if not key:
            return None
        return f"****{key[-4:]}" if len(key) > 4 else "****"

    fields = {
        "master_resume": cfg.master_resume,
        "output_dir": cfg.output_dir,
        "api_key": _redact(cfg.api_key),
        "provider": cfg.provider,
        "model": cfg.model,
        "tavily_api_key": _redact(cfg.tavily_api_key),
    }
    for key, value in fields.items():
        shown = value if value is not None else "[dim](not set)[/dim]"
        console.print(f"{key}: {shown}")


cache_app = typer.Typer(help="Manage weave-cv's cached CV analyses.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear():
    """Delete every cached CV analysis, candidate role-fit summary, JD
    analysis, and discovered-job "seen" record, forcing a fresh
    re-analysis of the master resume/job posting on the next
    `tailor`/`batch` run and re-surfacing every previously-shown posting
    on the next `discover` run, regardless of whether anything actually
    changed. Useful after a prompt/model change you want reflected
    immediately."""
    cv_removed = cv_cache.clear_cache()
    role_fit_removed = candidate_role_fit_cache.clear_cache()
    jd_removed = jd_cache.clear_cache()
    discovered_removed = db.clear_discovered_jobs()
    if cv_removed == 0 and role_fit_removed == 0 and jd_removed == 0 and discovered_removed == 0:
        typer.secho("Cache was already empty.", fg=typer.colors.YELLOW)
    else:
        typer.secho(
            f"Cleared {cv_removed} cached CV analysis file(s), "
            f"{role_fit_removed} cached candidate role-fit summary(ies), "
            f"{jd_removed} cached JD analysis file(s), and "
            f"{discovered_removed} discovered-job record(s).",
            fg=typer.colors.GREEN,
        )


@cache_app.command("show")
def cache_show(
    master_resume: Optional[Path] = typer.Option(
        None,
        "--master-resume",
        "-m",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Master resume .tex file to check. Defaults to the saved config value.",
    ),
    job_url: Optional[str] = typer.Option(
        None, "--job-url", "-j", help="Job posting URL to check."
    ),
):
    """Report whether --master-resume (or the saved default) and/or
    --job-url currently have a cached analysis, plus a summary of
    everything in both caches."""
    cv_path = master_resume or (Path(_cfg.master_resume) if _cfg.master_resume else None)

    if cv_path is None:
        typer.secho(
            "No master resume given or configured — see `weave-cv config set --master-resume ...`.",
            fg=typer.colors.YELLOW,
        )
    else:
        entry = cv_cache.get_cache_entry(str(cv_path))
        if entry is None:
            typer.secho(f"Not cached (CV): {cv_path}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"Cached (CV): {cv_path}", fg=typer.colors.GREEN)
            console.print(f"  name: {entry.contact_name or '[dim](none)[/dim]'}")
            console.print(f"  cached at: {entry.cached_at:%Y-%m-%d %H:%M:%S}")

    console.print()

    if job_url is None:
        console.print("[dim]Pass --job-url to check a specific job posting's cache status.[/dim]")
    else:
        entry = jd_cache.get_cache_entry(job_url)
        if entry is None:
            typer.secho(f"Not cached (JD): {job_url}", fg=typer.colors.YELLOW)
        elif entry.expired:
            typer.secho(f"Expired (JD): {job_url}", fg=typer.colors.YELLOW)
            console.print(f"  cached at: {entry.cached_at:%Y-%m-%d %H:%M:%S} (TTL: {jd_cache.JD_CACHE_TTL})")
        else:
            typer.secho(f"Cached (JD): {job_url}", fg=typer.colors.GREEN)
            console.print(f"  company: {entry.company_name or '[dim](none)[/dim]'}")
            console.print(f"  title: {entry.title or '[dim](none)[/dim]'}")
            console.print(f"  cached at: {entry.cached_at:%Y-%m-%d %H:%M:%S}")

    console.print()

    cv_entries = cv_cache.list_cache_entries()
    if cv_entries:
        table = Table(title=f"All cached CV analyses ({len(cv_entries)})")
        table.add_column("Hash")
        table.add_column("Name")
        table.add_column("Cached At")
        table.add_column("Size")
        for e in cv_entries:
            table.add_row(
                e.hash[:12],
                e.contact_name or "[dim](none)[/dim]",
                f"{e.cached_at:%Y-%m-%d %H:%M:%S}",
                f"{e.size_bytes:,} B",
            )
        console.print(table)
    else:
        console.print("[dim]No cached CV analyses.[/dim]")

    console.print()

    jd_entries = jd_cache.list_cache_entries()
    if jd_entries:
        table = Table(title=f"All cached JD analyses ({len(jd_entries)})")
        table.add_column("Hash")
        table.add_column("Company")
        table.add_column("Title")
        table.add_column("Cached At")
        table.add_column("Status")
        for e in jd_entries:
            status = "[yellow]expired[/yellow]" if e.expired else "[green]fresh[/green]"
            table.add_row(
                e.hash[:12],
                e.company_name or "[dim](none)[/dim]",
                e.title or "[dim](none)[/dim]",
                f"{e.cached_at:%Y-%m-%d %H:%M:%S}",
                status,
            )
        console.print(table)
    else:
        console.print("[dim]No cached JD analyses.[/dim]")


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
                    still_retrying = (
                        update.get("page_fit_underfilled")
                        and update.get("page_fit_attempts", 0) < MAX_PAGE_FIT_ATTEMPTS
                    )
                    if still_retrying:
                        feedback = update.get("page_fit_feedback") or "no reason given"
                        console.print(
                            f"[dim]{elapsed:5.1f}s[/dim] [yellow]…[/yellow] {label}{suffix} — "
                            f"page under-filled, retrying: {feedback}"
                        )
                        current_label = f"{_STAGE_LABELS['tailor']} (retry)"
                    else:
                        console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}{suffix}")
                else:
                    console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}")

                # No "next stage" line once generate actually finishes (as
                # opposed to looping back to tailor for an under-fill
                # retry) — it's the terminal stage in that case, nothing
                # left to announce.
                is_terminal_generate = node_name == "generate" and not (
                    update.get("page_fit_underfilled")
                    and update.get("page_fit_attempts", 0) < MAX_PAGE_FIT_ATTEMPTS
                )
                if not update.get("failed_stage") and not is_terminal_generate:
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
    if state.get("cover_letter_path"):
        typer.secho(f"Cover letter saved to: {state['cover_letter_path']}", fg=typer.colors.GREEN)
    if state.get("job_posting_path"):
        typer.secho(f"Job posting details saved to: {state['job_posting_path']}", fg=typer.colors.GREEN)


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
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="CSV or XLSX file with a job_url/url/link/job_link header column. "
        "Exactly one of --file or --from-db is required.",
    ),
    from_db: bool = typer.Option(
        False,
        "--from-db",
        help="Pull job URLs from `discover`'s local database instead of --file — "
        "every posting marked relevant that hasn't already gone through "
        "`tailor`/`batch` before. Exactly one of --file or --from-db is required.",
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
    """Tailor --master-resume against every job URL in --file (or every
    relevant, not-yet-applied posting in the local database if --from-db
    is passed instead) — one output per job, same output folder, up to
    --concurrency at a time."""
    _print_banner()
    if bool(file) == from_db:
        typer.secho("Pass exactly one of --file or --from-db.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if from_db:
        urls = [row["url"] for row in db.list_relevant_unapplied_jobs()]
        if not urls:
            typer.secho("No relevant, unapplied jobs in the database — run `weave-cv discover` first.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=0)
        console.print(f"Found {len(urls)} relevant, unapplied job(s) in the database. Processing up to {concurrency} at a time.\n")
    else:
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


def _hours_ago(posted_at: datetime) -> str:
    posted_at_utc = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - posted_at_utc).total_seconds() / 3600
    if hours < 1:
        return f"{max(round(hours * 60), 0)}m ago"
    return f"{hours:.1f}h ago"


async def _run_discover(
    cv_path: str, keyword_list: list[str], max_age_hours: int, ignore_seen: bool = False,
) -> list[RelevantJob]:
    """Resolves the candidate's role-fit (cache-first, see
    candidate_role_fit_agent), then drains stream_discover_jobs, printing
    every stage as it arrives — the exact Tavily query and domain filter
    sent per (keyword, platform) pair, every posting fetched directly by
    URL, the funnel counts at each filter step, and every posting as
    it's handed to the relevance judge along with its verdict — rather
    than only surfacing the final relevant list at the end."""
    cv_profile = await analyze_cv(cv_path)
    candidate = await get_or_build_candidate_role_fit(cv_path, cv_profile)
    console.print(
        f"[dim]Candidate role fit — roles: {', '.join(candidate.target_roles)} | "
        f"experience: {candidate.min_years_experience:g}-{candidate.max_years_experience:g}y | "
        f"skills: {', '.join(candidate.core_skills)}[/dim]\n"
    )
    if ignore_seen:
        console.print("[dim]--ignore-seen: re-judging postings even if already scored on a previous run.[/dim]\n")

    results: list[RelevantJob] = []
    async for stage, data in stream_discover_jobs(candidate, keyword_list, max_age_hours, ignore_seen):
        if stage == "search":
            console.print(
                f"[cyan]Tavily search[/cyan] keyword={data['keyword']!r} platform={data['platform']} "
                f"domains={data['domains']} -> {data['results_count']} result(s)"
            )
        elif stage == "urls_found":
            console.print(f"\n[cyan]Unique postings found:[/cyan] {data['count']}\n")
        elif stage == "fetched":
            console.print(f"  [dim]{data['platform']}[/dim] -> {data['title']} @ {data['company']}")
        elif stage == "fetch_miss":
            console.print(f"  [dim]{data['platform']} -> posting no longer available, skipped[/dim]")
        elif stage == "fetch_error":
            console.print(f"  [red]{data['platform']} fetch failed:[/red] {data['error']}")
        elif stage == "seniority_filtered":
            console.print(
                f"  [dim]{data['title']} @ {data['company']} ({data['platform']}) — "
                f"skipped on title alone: {data['reason']}[/dim]"
            )
        elif stage == "filtered":
            console.print(
                f"\n[cyan]Funnel:[/cyan] {data['total_postings']} posting(s) fetched -> "
                f"{data['fresh']} fresh -> {data['unseen']} not already scored -> "
                f"{data['keyword_matched']} matched keywords -> "
                f"{data['seniority_filtered']} filtered on title alone -> "
                f"{data['to_judge']} judging now\n"
            )
        elif stage == "judging":
            console.print(
                f"[yellow]Judging[/yellow] {data['title']} @ {data['company']} "
                f"({data['platform']}) — {data['url']}"
            )
        elif stage == "verdict":
            if data["relevant"]:
                console.print(f"  [green]RELEVANT[/green] — {data['reason']}\n")
                results.append(RelevantJob(job=data["job"], reason=data["reason"]))
            else:
                console.print(f"  [dim]not relevant — {data['reason']}[/dim]\n")

    return results


@app.command()
def discover(
    keywords: str = typer.Option(
        ...,
        "--keywords",
        "-k",
        help="Comma-separated role/skill keywords to search for, e.g. "
        "'backend engineer,distributed systems'.",
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
        help="Path to your master resume .tex file, used to judge relevance. "
        "Defaults to the saved value (`weave-cv config set --master-resume ...`) if set.",
    ),
    max_age_hours: int = typer.Option(
        48, "--max-age-hours", min=1,
        help="Only show postings newer than this.",
    ),
    ignore_seen: bool = typer.Option(
        False,
        "--ignore-seen",
        help="Re-judge postings even if a previous `discover` run already "
        "scored them, instead of skipping anything already recorded — "
        "use this if the pool of genuinely new postings looks thin and "
        "you want another shot at ones seen before (e.g. after loosening "
        "keywords or relevance criteria). The fresh verdict replaces the "
        "old one, it doesn't just get discarded after this run.",
    ),
):
    """Search Ashby/Greenhouse/Lever/Workday for fresh job postings
    relevant to your resume. Standalone experiment, separate from
    `tailor`/`batch` —
    this only searches and judges relevance, it never tailors or
    generates anything. Postings already shown in a previous `discover`
    run are skipped automatically unless --ignore-seen is passed; use
    `weave-cv cache clear` to drop that history entirely instead. Prints
    every search query, every company/posting found, and every relevance
    verdict as it happens — this is meant to be watched, not just waited
    on."""
    _print_banner()
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        typer.secho("No keywords given.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    results = asyncio.run(_run_discover(str(cv_path), keyword_list, max_age_hours, ignore_seen))

    if not results:
        console.print("[dim]No new relevant postings found.[/dim]")
        return

    table = Table(title=f"{len(results)} relevant posting(s) found")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Platform")
    table.add_column("Posted")
    table.add_column("Why")
    for r in results:
        table.add_row(
            r.job.title,
            r.job.company_name or r.job.company,
            r.job.platform,
            _hours_ago(r.job.posted_at),
            r.reason,
        )
    console.print(table)
    console.print()
    for r in results:
        console.print(f"[green]{r.job.title}[/green] @ {r.job.company_name or r.job.company} — {r.job.url}")


async def _apply_one(job_url: str, cv_path: str) -> None:
    row = db.get_applied_job(job_url)
    if row is None:
        typer.secho(f"No tailored resume found for {job_url} — run `tailor`/`batch` for it first.", fg=typer.colors.RED)
        return
    if row["status"] != "success":
        typer.secho(
            f"Tailoring failed for {job_url} (stage: {row['failed_stage']}) — nothing to apply with.",
            fg=typer.colors.RED,
        )
        return

    cv_profile = await analyze_cv(cv_path)
    console.print(f"\n[cyan]Opening application form:[/cyan] {job_url}")
    try:
        result: ApplyResult = await apply_to_job(job_url, row["pdf_path"], row["cover_letter_path"], cv_profile)
    except Exception as e:
        db.save_application_attempt(job_url, status="error", error=str(e))
        typer.secho(f"Failed: {e}", fg=typer.colors.RED)
        return

    if not result.form_found:
        db.save_application_attempt(job_url, status="no_form_found")
        typer.secho("Could not locate an application form on this page — apply manually.", fg=typer.colors.YELLOW)
        return

    db.save_application_attempt(job_url, status="filled", filled_fields=result.filled, skipped_fields=result.skipped)
    console.print(f"[green]Filled {len(result.filled)} field(s):[/green] {', '.join(result.filled) or '(none)'}")
    if result.skipped:
        console.print(f"[yellow]Left {len(result.skipped)} field(s) for you:[/yellow]")
        for label, reason in result.skipped:
            console.print(f"  - {label}: {reason}")


@app.command()
def apply(
    job_url: Optional[str] = typer.Option(
        None,
        "--job-url",
        "-j",
        help="Apply to this specific job URL — it must already have a tailored "
        "resume (see `tailor`/`batch`). Exactly one of --job-url or --from-db "
        "is required.",
    ),
    from_db: bool = typer.Option(
        False,
        "--from-db",
        help="Apply, one at a time, to every successfully-tailored job not yet "
        "attempted. Exactly one of --job-url or --from-db is required.",
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
        help="Path to your master resume .tex file, used for contact info "
        "(name/email/phone/links). Defaults to the saved value "
        "(`weave-cv config set --master-resume ...`) if set.",
    ),
):
    """Opens a real, visible browser and fills what it confidently can on
    a job's actual application form — name, email, phone, links, and the
    tailored resume/cover letter file uploads. NEVER clicks Submit or
    Apply, and never touches an EEO/demographic/consent/work-
    authorization/citizenship/salary/CAPTCHA field (deterministically
    excluded, not an LLM judgment call — see services/browser.py). Leaves
    the browser open after filling so you can review, answer whatever it
    skipped, and submit it yourself. Standalone experiment, separate from
    `tailor`/`batch`/`discover` — only ever consumes what they already
    produced."""
    _print_banner()
    if bool(job_url) == from_db:
        typer.secho("Pass exactly one of --job-url or --from-db.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if job_url:
        asyncio.run(_apply_one(job_url, str(cv_path)))
        return

    rows = db.list_tailored_jobs_ready_to_apply()
    if not rows:
        typer.secho("No tailored jobs ready to apply to — run `tailor`/`batch` first.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    console.print(f"Found {len(rows)} job(s) to apply to, one at a time.\n")
    for row in rows:
        asyncio.run(_apply_one(row["job_url"], str(cv_path)))


def main() -> None:
    """Entry point (see [project.scripts] in pyproject.toml). Click's
    --help is an eager option that exits before any command callback
    runs, so `tailor`/`batch`'s own `_print_banner()` calls never fire
    for --help — print it here instead, ahead of handing off to `app`."""
    if len(sys.argv) == 1 or "--help" in sys.argv or "-h" in sys.argv:
        _print_banner()
    app()


if __name__ == "__main__":
    main()
