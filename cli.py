import asyncio
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from agents.orchestrator_agent import stream_resume_pipeline

load_dotenv()

app = typer.Typer(help="Tailor a LaTeX resume to a job posting using AI agents.")
console = Console()

_STAGE_LABELS = {
    "gather_inputs": "Scraping job posting & analyzing resume",
    "tailor": "Tailoring resume",
    "verify": "Verifying tailored resume",
    "generate": "Generating PDF",
}


async def _run_with_progress(job_url: str, cv_path: str, output_dir: str) -> dict:
    """Consumes the pipeline's stage-by-stage stream and prints a line as
    each one completes, so the CLI shows live progress instead of sitting
    silent for the couple of minutes a full run takes. Also accumulates
    every stage's state update into one dict, since streaming mode only
    yields the diff per node, not the final merged state."""
    final_state: dict = {}

    async for node_name, update in stream_resume_pipeline(job_url, cv_path, output_dir):
        final_state.update(update)
        label = _STAGE_LABELS.get(node_name, node_name)

        if update.get("failed_stage"):
            console.print(f"[red]✗[/red] {label} failed")
            break

        if node_name == "tailor":
            attempt = update.get("verification_attempts")
            console.print(f"[green]✓[/green] {label} (attempt {attempt})")
        elif node_name == "verify":
            if update.get("verification_passed"):
                console.print(f"[green]✓[/green] {label} — passed")
            else:
                feedback = update.get("verification_feedback") or "no reason given"
                console.print(f"[yellow]…[/yellow] {label} — failed, retrying: {feedback}")
        else:
            console.print(f"[green]✓[/green] {label}")

    return final_state


@app.command()
def tailor(
    job_url: str = typer.Argument(..., help="Job posting URL to tailor the resume against."),
    cv_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to your master resume .tex file.",
    ),
    output_dir: Path = typer.Option(
        ...,
        "--output-dir",
        "-o",
        prompt="Enter the folder path to save the generated resume in",
        help="Folder to save the generated .tex/.pdf into (created if missing).",
    ),
):
    """Tailor CV_PATH against JOB_URL and save the result to --output-dir."""
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
