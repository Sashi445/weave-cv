"""User-level config for weave-cv (master resume path, output folder, LLM
API key, model). Stored at ~/.weave-cv/config.toml so it persists across
runs and across working directories — this matters once the tool is
installed via pip and invoked from anywhere, not just from within this
repo where a local .env file would otherwise be the only source of
credentials."""

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel

CONFIG_DIR = Path.home() / ".weave-cv"
CONFIG_PATH = CONFIG_DIR / "config.toml"


class WeaveCVConfig(BaseModel):
    master_resume: str | None = None
    output_dir: str | None = None
    api_key: str | None = None
    model: str | None = None
    provider: str | None = None


def load_config() -> WeaveCVConfig:
    if not CONFIG_PATH.exists():
        return WeaveCVConfig()
    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    return WeaveCVConfig(**data)


def save_config(cfg: WeaveCVConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in cfg.model_dump().items() if v is not None}
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)
    # The file can hold a raw API key — restrict to owner read/write only.
    CONFIG_PATH.chmod(0o600)
