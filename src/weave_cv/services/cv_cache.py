"""Caches CV-analysis results (CVProfile) keyed on the master resume
file's own content hash, not its path — the master resume rarely changes
between runs, so re-running the CV-Analyzer agent (an LLM call plus an
MCP tool call) on unchanged content is pure waste. Keying on content
rather than path also means the cache transparently survives the file
being renamed/moved, or the user pointing weave-cv at a different file
that happens to have identical content, with no path bookkeeping.

Stored at ~/.weave-cv/cache/cv_analysis/<sha256>.json, alongside
config.toml's ~/.weave-cv/ convention (see config.py).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from weave_cv.config import CONFIG_DIR
from weave_cv.schemas.cv_analysis import CVProfile

CACHE_DIR = CONFIG_DIR / "cache" / "cv_analysis"

# Bump whenever CVProfile gains a field the analyzer should be extracting
# (not a purely derived/default one) — a cached entry written under an
# older version is treated as a miss rather than served as-is. Without
# this, adding e.g. Project.links validates fine against an old cache
# entry that predates the field (default_factory=list silently fills it
# in as empty) — the entry looks "valid" but was never actually asked to
# extract that data, so it would keep serving links-less profiles forever
# regardless of any extraction-prompt fix, with no error and no signal
# that anything's wrong. A version mismatch forces one re-extraction per
# stale entry instead.
CACHE_SCHEMA_VERSION = 1


@dataclass
class CacheEntry:
    """Metadata about one cached CV analysis — for `weave-cv cache show`,
    which reports whether/what is cached without needing the full
    CVProfile the way get_cached_cv_profile's callers do."""
    hash: str
    cached_at: datetime
    size_bytes: int
    contact_name: str | None


def _hash_file(cv_path: str) -> str:
    return hashlib.sha256(Path(cv_path).read_bytes()).hexdigest()


def _read_versioned_profile(cache_path: Path) -> CVProfile | None:
    """None on a cache miss, an unreadable/corrupt entry, OR a
    schema-version mismatch — all three are just "can't trust this,
    re-extract" to every caller, never a crash over what's only a
    performance optimization. A version mismatch also covers every
    pre-versioning entry (the raw-CVProfile-JSON format this replaced),
    since those have no `schema_version` key to match at all."""
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    try:
        return CVProfile.model_validate(raw["profile"])
    except (ValueError, KeyError):
        return None


def _read_entry(cache_path: Path) -> CacheEntry | None:
    profile = _read_versioned_profile(cache_path)
    if profile is None:
        return None
    stat = cache_path.stat()
    return CacheEntry(
        hash=cache_path.stem,
        cached_at=datetime.fromtimestamp(stat.st_mtime),
        size_bytes=stat.st_size,
        contact_name=profile.contact.name,
    )


def get_cached_cv_profile(cv_path: str) -> CVProfile | None:
    """None on any cache miss, unreadable/corrupt entry, or version
    mismatch — see _read_versioned_profile."""
    cache_path = CACHE_DIR / f"{_hash_file(cv_path)}.json"
    return _read_versioned_profile(cache_path)


def save_cv_profile_to_cache(cv_path: str, profile: CVProfile) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_hash_file(cv_path)}.json"
    payload = {"schema_version": CACHE_SCHEMA_VERSION, "profile": profile.model_dump(mode="json")}
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_cache_entry(cv_path: str) -> CacheEntry | None:
    """Like get_cached_cv_profile, but returns cache metadata (when it was
    cached, whose name it holds) instead of the CVProfile itself — for
    reporting whether a cache exists rather than consuming it."""
    return _read_entry(CACHE_DIR / f"{_hash_file(cv_path)}.json")


def list_cache_entries() -> list[CacheEntry]:
    """Every cached entry, regardless of whether the source file that
    produced it still exists on disk — entries are hash-keyed with no
    stored path, so a renamed/deleted source's entry can only be listed
    this way, not matched back to a file."""
    if not CACHE_DIR.exists():
        return []
    entries = (_read_entry(p) for p in sorted(CACHE_DIR.glob("*.json")))
    return [e for e in entries if e is not None]


def clear_cache() -> int:
    """Deletes every cached CV analysis. Returns the count removed, for
    the CLI to report back."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for entry in CACHE_DIR.glob("*.json"):
        entry.unlink()
        removed += 1
    return removed
