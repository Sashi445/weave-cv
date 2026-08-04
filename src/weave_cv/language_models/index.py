import os

import typer
from langchain.chat_models import init_chat_model
from dotenv import find_dotenv, load_dotenv

from weave_cv.config import load_config, save_config

_DEFAULT_PROVIDER = "openai"
_DEFAULT_MODEL = "gpt-5-mini"  # only used when provider is (or defaults to) openai

# Dev-mode env-var fallback and the pip package needed for each provider,
# for the handful of providers we can give a good out-of-the-box
# experience for. This list isn't exhaustive — init_chat_model itself
# supports many more providers (bedrock, ibm, nvidia, ...) — any provider
# string is accepted and passed straight through; providers outside this
# table just skip the env-var fallback and the friendly "pip install ..."
# hint on a missing package, falling back to the interactive prompt /
# langchain's own ImportError respectively.
_PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
_PROVIDER_PACKAGES = {
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
    "google_genai": "langchain-google-genai",
    "groq": "langchain-groq",
    "xai": "langchain-xai",
    "deepseek": "langchain-deepseek",
}

# A .env file only exists in a repo checkout (dev mode) — a real pip
# install has no such file, so its presence is what distinguishes the two
# for API-key resolution below, not an explicit flag.
_dotenv_path = find_dotenv(usecwd=True)
_IS_DEV_MODE = bool(_dotenv_path)
if _IS_DEV_MODE:
    load_dotenv(_dotenv_path)

_model_instance = None


def _resolve_api_key(cfg, provider: str) -> str:
    """Resolution order: saved config, then (dev mode only) the
    provider's own API-key env var from the environment/.env (e.g.
    ANTHROPIC_API_KEY for provider="anthropic"), then an interactive
    prompt as the last resort — which saves what's entered back to
    config so it's only ever asked once. Prod/CLI mode (no .env found)
    has no environment-variable fallback, since there's no dev-only .env
    convention to fall back to there; it goes straight from config to
    prompting.
    """
    if cfg.api_key:
        return cfg.api_key

    if _IS_DEV_MODE:
        env_var = _PROVIDER_ENV_VARS.get(provider)
        if env_var:
            env_key = os.environ.get(env_var)
            if env_key:
                return env_key

    entered = typer.prompt(f"No API key found for provider '{provider}' — enter one", hide_input=True)
    cfg.api_key = entered
    save_config(cfg)
    typer.secho("Saved API key to your weave-cv config.", fg=typer.colors.GREEN)
    return entered


def _resolve_model_name(cfg, provider: str) -> str:
    """cfg.model, else the openai default if that's the active provider
    (preserves the old zero-config behavior), else an interactive prompt
    — there's no sensible default model name for an arbitrary provider,
    so guessing one would silently pick something the user didn't
    choose. Saves what's entered back to config, same as the API key."""
    if cfg.model:
        return cfg.model
    if provider == _DEFAULT_PROVIDER:
        return _DEFAULT_MODEL

    entered = typer.prompt(f"No model set for provider '{provider}' — enter one (e.g. claude-sonnet-4-5)")
    cfg.model = entered
    save_config(cfg)
    typer.secho("Saved model to your weave-cv config.", fg=typer.colors.GREEN)
    return entered


def get_model():
    """Single model used by every agent, per user config (`weave-cv
    config set --provider ... --model ... --api-key ...`). Previously
    this project used a nano/mini tier split (cheap model for flat JD
    extraction, stronger model for the deeply nested
    CV/tailoring/verification/generation schemas, after nano proved
    unreliable on those) — collapsing to one configurable model was a
    deliberate choice to keep the config surface simple, traded off
    against that tiering. If a weak model is configured, the
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
        provider = cfg.provider or _DEFAULT_PROVIDER
        model_name = _resolve_model_name(cfg, provider)
        api_key = _resolve_api_key(cfg, provider)
        try:
            _model_instance = init_chat_model(
                model=model_name,
                model_provider=provider,
                api_key=api_key,
            )
        except ImportError as e:
            package = _PROVIDER_PACKAGES.get(provider, f"langchain-{provider}")
            typer.secho(
                f"Missing integration package for provider '{provider}'. "
                f"Install it with: pip install {package}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1) from e
    return _model_instance
