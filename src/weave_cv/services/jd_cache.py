"""Caches JD-analysis results (JobDescriptionAnalysis) keyed on the job
posting's URL. Unlike the CV cache (services/cv_cache.py, keyed on file
content and kept forever — a master resume is a file the user fully
controls), a job posting lives on someone else's server and can be edited
or taken down without the URL changing, so entries expire after JD_CACHE_TTL
instead of being trusted indefinitely.

Keying on the URL rather than the scraped content means a cache hit skips
both the scrape (services/web_scraper.py spins up a headless browser —
real latency on its own) and the LLM extraction call, not just the LLM
call.

Stored at ~/.weave-cv/cache/jd_analysis/<sha256>.json, alongside
config.toml's ~/.weave-cv/ convention (see config.py).
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from weave_cv.config import CONFIG_DIR
from weave_cv.schemas.jd_analysis import JobDescriptionAnalysis

CACHE_DIR = CONFIG_DIR / "cache" / "jd_analysis"
JD_CACHE_TTL = timedelta(hours=48)


@dataclass
class CacheEntry:
    hash: str
    cached_at: datetime
    size_bytes: int
    company_name: str | None
    title: str | None
    expired: bool


def _hash_url(job_url: str) -> str:
    return hashlib.sha256(job_url.strip().encode("utf-8")).hexdigest()


def _read_entry(cache_path: Path) -> CacheEntry | None:
    if not cache_path.exists():
        return None
    try:
        profile = JobDescriptionAnalysis.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return None
    stat = cache_path.stat()
    cached_at = datetime.fromtimestamp(stat.st_mtime)
    return CacheEntry(
        hash=cache_path.stem,
        cached_at=cached_at,
        size_bytes=stat.st_size,
        company_name=profile.company_name,
        title=profile.title,
        expired=datetime.now() - cached_at > JD_CACHE_TTL,
    )


def get_cached_jd_profile(job_url: str) -> JobDescriptionAnalysis | None:
    """None on a cache miss, an expired entry, or an unreadable/corrupt
    entry — a stale or bad cache file should fall back to re-scraping and
    re-analyzing, never crash the pipeline over what's just a performance
    optimization."""
    cache_path = CACHE_DIR / f"{_hash_url(job_url)}.json"
    entry = _read_entry(cache_path)
    if entry is None or entry.expired:
        return None
    try:
        return JobDescriptionAnalysis.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return None


def save_jd_profile_to_cache(job_url: str, profile: JobDescriptionAnalysis) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_hash_url(job_url)}.json"
    cache_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def get_cache_entry(job_url: str) -> CacheEntry | None:
    """Like get_cached_jd_profile, but returns cache metadata (including
    whether it's expired) instead of the profile itself — for reporting
    cache state rather than consuming it."""
    return _read_entry(CACHE_DIR / f"{_hash_url(job_url)}.json")


def list_cache_entries() -> list[CacheEntry]:
    if not CACHE_DIR.exists():
        return []
    entries = (_read_entry(p) for p in sorted(CACHE_DIR.glob("*.json")))
    return [e for e in entries if e is not None]


def clear_cache() -> int:
    """Deletes every cached JD analysis (expired or not). Returns the
    count removed, for the CLI to report back."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for entry in CACHE_DIR.glob("*.json"):
        entry.unlink()
        removed += 1
    return removed
