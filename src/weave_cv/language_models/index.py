import os

import typer
from langchain.chat_models import init_chat_model
from dotenv import find_dotenv, load_dotenv

from weave_cv.config import load_config, save_config

_DEFAULT_MODEL = "gpt-5-mini"

# A .env file only exists in a repo checkout (dev mode) — a real pip
# install has no such file, so its presence is what distinguishes the two
# for API-key resolution below, not an explicit flag.
_dotenv_path = find_dotenv(usecwd=True)
_IS_DEV_MODE = bool(_dotenv_path)
if _IS_DEV_MODE:
    load_dotenv(_dotenv_path)

_model_instance = None


def _resolve_api_key(cfg) -> str:
    """Resolution order: saved config, then (dev mode only) OPENAI_API_KEY
    from the environment/.env, then an interactive prompt as the last
    resort — which saves what's entered back to config so it's only ever
    asked once. Prod/CLI mode (no .env found) has no environment-variable
    fallback, since there's no dev-only .env convention to fall back to
    there; it goes straight from config to prompting.
    """
    if cfg.api_key:
        return cfg.api_key

    if _IS_DEV_MODE:
        env_key = os.environ.get("OPENAI_API_KEY")
        if env_key:
            return env_key

    entered = typer.prompt("No OpenAI API key found — enter one", hide_input=True)
    cfg.api_key = entered
    save_config(cfg)
    typer.secho("Saved API key to your weave-cv config.", fg=typer.colors.GREEN)
    return entered


def get_model():
    """Single model used by every agent, per user config (`weave-cv config
    set --model ...`). Previously this project used a nano/mini tier
    split (cheap model for flat JD extraction, stronger model for the
    deeply nested CV/tailoring/verification/generation schemas, after
    nano proved unreliable on those) — collapsing to one configurable
    model was a deliberate choice to keep the config surface simple,
    traded off against that tiering. If a weak model is configured, the
    nested-schema reliability issues that motivated the tiering could
    resurface.

    Lazy and memoized: constructed on first real use, not at import time
    — importing this module (or anything that imports it, like every
    agent) must not require credentials, or commands that don't need the
    model at all (`--help`, `config set`) become unusable without one
    already being set, which is exactly backwards for `config set
    --api-key`.
    """
    global _model_instance
    if _model_instance is None:
        cfg = load_config()
        api_key = _resolve_api_key(cfg)
        _model_instance = init_chat_model(
            model=cfg.model or _DEFAULT_MODEL,
            api_key=api_key,
        )
    return _model_instance
