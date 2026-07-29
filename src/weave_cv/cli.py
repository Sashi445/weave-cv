import asyncio
import time
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from weave_cv.agents.orchestrator_agent import stream_resume_pipeline
from weave_cv.config import CONFIG_PATH, load_config, save_config

load_dotenv()

app = typer.Typer(help="Tailor a LaTeX resume to a job posting using AI agents.")
console = Console()

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
        None, "--model", help="Model name used for every agent (e.g. gpt-5-mini)."
    ),
):
    """Save one or more defaults. Flags you omit are left unchanged."""
    if master_resume is None and output_dir is None and api_key is None and model is None:
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
    """Consumes the pipeline's stage-by-stage stream and prints a line as
    each one completes (with elapsed time for that stage), so the CLI
    shows live progress instead of sitting silent for the couple of
    minutes a full run takes. Also accumulates every stage's state update
    into one dict, since streaming mode only yields the diff per node,
    not the final merged state."""
    final_state: dict = {}
    start = time.perf_counter()
    stage_start = start

    async for node_name, update in stream_resume_pipeline(job_url, cv_path, output_dir):
        now = time.perf_counter()
        elapsed = now - stage_start
        stage_start = now
        final_state.update(update)
        label = _STAGE_LABELS.get(node_name, node_name)

        if update.get("failed_stage"):
            console.print(f"[dim]{elapsed:5.1f}s[/dim] [red]✗[/red] {label} failed")
            break

        if node_name == "tailor":
            attempt = update.get("verification_attempts")
            console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label} (attempt {attempt})")
        elif node_name == "verify":
            if update.get("verification_passed"):
                console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label} — passed")
            else:
                feedback = update.get("verification_feedback") or "no reason given"
                console.print(
                    f"[dim]{elapsed:5.1f}s[/dim] [yellow]…[/yellow] {label} — "
                    f"failed, retrying: {feedback}"
                )
        else:
            console.print(f"[dim]{elapsed:5.1f}s[/dim] [green]✓[/green] {label}")

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


if __name__ == "__main__":
    app()
