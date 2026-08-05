from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(filename: str) -> str:
    """Reads a prompt file bundled in this package, resolved relative to
    weave_cv's own installed location — not the caller's current working
    directory. Same fix as weave_cv.mcp.mcp_script_path: a bare relative
    path like "prompts/cv_analyzer.txt" only resolves when the process
    cwd happens to be this repo's checkout root; pip-installed and run
    from anywhere else, it's just a missing file (this was doubly broken
    before — prompts/ used to live outside src/weave_cv/ entirely, so it
    wasn't even bundled into the wheel regardless of cwd).
    """
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
