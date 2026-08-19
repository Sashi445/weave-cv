"""Single local SQLite persistence layer for three things `discover`,
`tailor`/`batch`, and `apply` all need to know about each other's
history:

- discovered_jobs: every posting `discover` has ever scored (relevant or
  not) — the same "never re-score the same posting twice" role
  services/discovered_jobs_cache.py used to serve with one JSON file per
  job, now queryable (list, filter by relevance, join against
  applied_jobs) instead of only answerable one ID at a time.
- applied_jobs: every job_url that has ever gone through the tailor
  pipeline (success or failure), recorded by orchestrator_agent.py
  itself so every entrypoint (tailor, batch, discover -> batch) gets this
  for free rather than each caller remembering to record it.
- applications: every job_url the apply agent (agents/apply_agent.py)
  has ever attempted to fill a real application form for — a distinct
  concern from applied_jobs (which only means "a resume/cover letter was
  generated," not "a browser ever visited the application page").

Plain stdlib sqlite3, not an ORM — single-user, single-process, low
write volume (one row per job, not per token); a short-lived connection
per call is simple and fully sufficient at this scale. Safe under
`batch`'s concurrent tailoring despite that: asyncio concurrency in this
project is single-threaded, so two "concurrent" writes never actually
execute inside sqlite3 at the same instant — each blocking call still
runs to completion before the next one starts.

Stored at ~/.weave-cv/weave_cv.db, same ~/.weave-cv/ convention as
config.py and cv_cache.py.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from weave_cv.config import CONFIG_DIR
from weave_cv.schemas.job_posting import DiscoveredJob

DB_PATH = CONFIG_DIR / "weave_cv.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS discovered_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    company TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    location TEXT,
    posted_at TEXT NOT NULL,
    description TEXT NOT NULL,
    relevant INTEGER NOT NULL,
    reason TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    UNIQUE(platform, company, job_id)
);

CREATE TABLE IF NOT EXISTS applied_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL UNIQUE,
    company_name TEXT,
    title TEXT,
    status TEXT NOT NULL,
    tex_path TEXT,
    pdf_path TEXT,
    cover_letter_path TEXT,
    failed_stage TEXT,
    error TEXT,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    filled_fields TEXT,
    skipped_fields TEXT,
    error TEXT,
    attempted_at TEXT NOT NULL
);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- discovered_jobs -------------------------------------------------

def has_discovered(platform: str, company: str, job_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM discovered_jobs WHERE platform = ? AND company = ? AND job_id = ?",
            (platform, company, job_id),
        ).fetchone()
        return row is not None


def save_discovered_job(job: DiscoveredJob, relevant: bool, reason: str) -> None:
    """Upserts on (platform, company, job_id) — a rescan (see
    stream_discover_jobs' ignore_seen param) can re-judge a posting
    that's already recorded and legitimately reach a different verdict
    (a prompt/model change, or just genuine judgment variance); the
    latest verdict should win, not get silently discarded by an
    insert-or-ignore that leaves a stale one in place forever."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO discovered_jobs
                (platform, company, job_id, title, url, location, posted_at,
                 description, relevant, reason, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform, company, job_id) DO UPDATE SET
                 title = excluded.title,
                 url = excluded.url,
                 location = excluded.location,
                 posted_at = excluded.posted_at,
                 description = excluded.description,
                 relevant = excluded.relevant,
                 reason = excluded.reason,
                 discovered_at = excluded.discovered_at""",
            (
                job.platform, job.company, job.job_id, job.title, job.url,
                job.location, job.posted_at.isoformat(), job.description,
                int(relevant), reason, _now(),
            ),
        )


def list_relevant_unapplied_jobs() -> list[sqlite3.Row]:
    """Every discovered posting marked relevant that hasn't already gone
    through the tailor pipeline — exactly the set `batch --from-db`
    should pull. A job_url present in applied_jobs is excluded
    regardless of whether that earlier attempt succeeded or failed: a
    failed attempt gets fixed by rerunning `tailor` on it directly, not
    by silently resurfacing it in the next `discover`-driven batch."""
    with _connect() as conn:
        return conn.execute(
            """SELECT d.* FROM discovered_jobs d
               WHERE d.relevant = 1
                 AND NOT EXISTS (SELECT 1 FROM applied_jobs a WHERE a.job_url = d.url)
               ORDER BY d.discovered_at DESC"""
        ).fetchall()


def clear_discovered_jobs() -> int:
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM discovered_jobs").fetchone()[0]
        conn.execute("DELETE FROM discovered_jobs")
        return count


# --- applied_jobs ------------------------------------------------------

def save_applied_job(
    job_url: str,
    company_name: str | None,
    title: str | None,
    status: str,
    tex_path: str | None = None,
    pdf_path: str | None = None,
    cover_letter_path: str | None = None,
    failed_stage: str | None = None,
    error: str | None = None,
) -> None:
    """Upserts on job_url — unlike discovered_jobs, this tracks the
    *latest* outcome for a given job, so rerunning `tailor` on the same
    URL (e.g. after fixing something) replaces the previous record
    instead of leaving a stale failed one sitting alongside a new
    success."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO applied_jobs
                (job_url, company_name, title, status, tex_path, pdf_path,
                 cover_letter_path, failed_stage, error, applied_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_url) DO UPDATE SET
                 company_name = excluded.company_name,
                 title = excluded.title,
                 status = excluded.status,
                 tex_path = excluded.tex_path,
                 pdf_path = excluded.pdf_path,
                 cover_letter_path = excluded.cover_letter_path,
                 failed_stage = excluded.failed_stage,
                 error = excluded.error,
                 applied_at = excluded.applied_at""",
            (
                job_url, company_name, title, status, tex_path, pdf_path,
                cover_letter_path, failed_stage, error, _now(),
            ),
        )


def has_applied(job_url: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM applied_jobs WHERE job_url = ?", (job_url,)).fetchone()
        return row is not None


def get_applied_job(job_url: str) -> sqlite3.Row | None:
    """The tailored-resume/cover-letter paths for one job_url — what the
    apply agent needs to know what to upload. None if this job_url never
    went through the tailor pipeline at all."""
    with _connect() as conn:
        return conn.execute("SELECT * FROM applied_jobs WHERE job_url = ?", (job_url,)).fetchone()


def list_applied_jobs() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM applied_jobs ORDER BY applied_at DESC").fetchall()


def clear_applied_jobs() -> int:
    """Unlike clear_discovered_jobs (wired into `weave-cv cache clear`,
    since that table is a disposable "seen" log), this has no CLI command
    of its own — applied_jobs is a history/audit trail, not a cache, so
    clearing it is a deliberate reset a caller has to ask for explicitly
    rather than something bundled into routine cache maintenance."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM applied_jobs").fetchone()[0]
        conn.execute("DELETE FROM applied_jobs")
        return count


# --- applications --------------------------------------------------------
# Deliberately separate from applied_jobs: that table tracks "did this job
# go through the tailor pipeline" (a resume/cover letter got generated),
# a distinct concern from "did the apply agent actually visit the site and
# fill out its form." Conflating the two would mean either table's name
# stops matching what it actually records.

def save_application_attempt(
    job_url: str,
    status: str,
    filled_fields: list[str] | None = None,
    skipped_fields: list[tuple[str, str]] | None = None,
    error: str | None = None,
) -> None:
    """Upserts on job_url, same "latest attempt wins" reasoning as
    applied_jobs — rerunning `apply` on a job replaces the previous
    attempt's record rather than accumulating stale ones."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO applications
                (job_url, status, filled_fields, skipped_fields, error, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_url) DO UPDATE SET
                 status = excluded.status,
                 filled_fields = excluded.filled_fields,
                 skipped_fields = excluded.skipped_fields,
                 error = excluded.error,
                 attempted_at = excluded.attempted_at""",
            (
                job_url, status,
                json.dumps(filled_fields) if filled_fields is not None else None,
                json.dumps(skipped_fields) if skipped_fields is not None else None,
                error, _now(),
            ),
        )


def has_attempted_application(job_url: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM applications WHERE job_url = ?", (job_url,)).fetchone()
        return row is not None


def list_applications() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM applications ORDER BY attempted_at DESC").fetchall()


def list_tailored_jobs_ready_to_apply() -> list[sqlite3.Row]:
    """Every successfully-tailored job_url (a real resume was generated
    for it) that the apply agent hasn't attempted yet — exactly the set
    `apply --from-db` should work through."""
    with _connect() as conn:
        return conn.execute(
            """SELECT a.* FROM applied_jobs a
               WHERE a.status = 'success'
                 AND NOT EXISTS (SELECT 1 FROM applications p WHERE p.job_url = a.job_url)
               ORDER BY a.applied_at DESC"""
        ).fetchall()
