"""Caches the derived CandidateRoleFit summary (see
agents/candidate_role_fit_agent.py), keyed on the master resume file's
own content hash — same convention as cv_cache.py, since this is a
second derived analysis of the same file, not an independent artifact.
Without this, `discover` would re-run the role-fit LLM call on every
invocation even though the underlying resume hasn't changed, the same
waste this cache exists to avoid for CVProfile itself.

Stored at ~/.weave-cv/cache/candidate_role_fit/<sha256>.json.
"""

import hashlib
import json
from pathlib import Path

from weave_cv.config import CONFIG_DIR
from weave_cv.schemas.candidate_role_fit import CandidateRoleFit

CACHE_DIR = CONFIG_DIR / "cache" / "candidate_role_fit"

# Same reasoning as cv_cache.CACHE_SCHEMA_VERSION: a version mismatch
# (including every pre-versioning entry, which has none) is a cache miss,
# not silently trusted — a schema change here shouldn't be able to keep
# serving a stale role-fit summary forever with no signal anything's off.
# Bumped to 2 when `location` was added: it defaults to None, so an
# entry cached under version 1 would otherwise keep validating "fine"
# forever with no location at all, silently skipping the location-based
# judgment the relevance agent now expects to have.
CACHE_SCHEMA_VERSION = 2


def _hash_file(cv_path: str) -> str:
    return hashlib.sha256(Path(cv_path).read_bytes()).hexdigest()


def get_cached_role_fit(cv_path: str) -> CandidateRoleFit | None:
    cache_path = CACHE_DIR / f"{_hash_file(cv_path)}.json"
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    try:
        return CandidateRoleFit.model_validate(raw["role_fit"])
    except (ValueError, KeyError):
        return None


def save_role_fit_to_cache(cv_path: str, role_fit: CandidateRoleFit) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_hash_file(cv_path)}.json"
    payload = {"schema_version": CACHE_SCHEMA_VERSION, "role_fit": role_fit.model_dump(mode="json")}
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_cache() -> int:
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for entry in CACHE_DIR.glob("*.json"):
        entry.unlink()
        removed += 1
    return removed
