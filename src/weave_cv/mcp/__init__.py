from pathlib import Path

_MCP_DIR = Path(__file__).resolve().parent


def mcp_script_path(*parts: str) -> str:
    """Absolute path to an MCP server script bundled in this package,
    resolved relative to weave_cv's own installed location on disk — not
    the caller's current working directory.

    Every agent's MultiServerMCPClient used to hardcode a path like
    "src/weave_cv/mcp/cv_analyzer/index.py" directly in its spawn args.
    That only resolves correctly when the process cwd happens to be this
    repo's checkout root — true for local dev (`uv run` from the repo),
    false for literally everyone who pip installs the package and runs
    `weave-cv` from an arbitrary directory, where there's no
    "src/weave_cv/..." under cwd at all. The subprocess spawn then fails
    with a bare "No such file or directory" pointing at a path built from
    the user's cwd, not the package's real location.
    """
    return str(_MCP_DIR.joinpath(*parts))
