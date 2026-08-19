"""Lazy, memoized Tavily search client for the `discover` command — same
pattern as language_models.index.get_model(): constructed on first real
use, not at import time, so importing this module (or the discovery
agent that uses it) never requires credentials up front.

This is deliberately its own small resolver rather than folded into
language_models/index.py's _resolve_api_key — that one is about which
LLM *provider* is active (openai/anthropic/...), a distinct axis from
"do we have a Tavily key," and conflating the two would mean an LLM
provider switch could accidentally touch Tavily resolution or vice versa.
"""

import os

import typer
from dotenv import find_dotenv, load_dotenv
from tavily import AsyncTavilyClient

from weave_cv.config import WeaveCVConfig, load_config, save_config

# Same dev-mode detection as language_models/index.py: a .env file only
# exists in a repo checkout, so its presence is what gates the
# environment-variable fallback below, not an explicit flag.
_dotenv_path = find_dotenv(usecwd=True)
_IS_DEV_MODE = bool(_dotenv_path)
if _IS_DEV_MODE:
    load_dotenv(_dotenv_path)

_client_instance: AsyncTavilyClient | None = None


def _resolve_tavily_api_key(cfg: WeaveCVConfig) -> str:
    """Resolution order: saved config, then (dev mode only) TAVILY_API_KEY
    from the environment/.env, then an interactive prompt as the last
    resort — which saves what's entered back to config so it's only ever
    asked once. Same shape as language_models.index._resolve_api_key."""
    if cfg.tavily_api_key:
        return cfg.tavily_api_key

    if _IS_DEV_MODE:
        env_key = os.environ.get("TAVILY_API_KEY")
        if env_key:
            return env_key

    entered = typer.prompt(
        "No Tavily API key found — enter one (free at tavily.com, no card required)",
        hide_input=True,
    )
    cfg.tavily_api_key = entered
    save_config(cfg)
    typer.secho("Saved Tavily API key to your weave-cv config.", fg=typer.colors.GREEN)
    return entered


def get_tavily_client() -> AsyncTavilyClient:
    global _client_instance
    if _client_instance is None:
        cfg = load_config()
        api_key = _resolve_tavily_api_key(cfg)
        _client_instance = AsyncTavilyClient(api_key)
    return _client_instance
