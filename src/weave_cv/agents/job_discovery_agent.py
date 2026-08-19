"""Standalone job-discovery pipeline — deliberately has nothing to do
with orchestrator_agent.py's tailor/verify/generate graph. Given a
candidate's CandidateRoleFit (a condensed distillation of their
CVProfile — see candidate_role_fit_agent.py, built once per resume and
reused here rather than re-sending the full CVProfile per posting) and a
list of target keywords, finds fresh (within max_age_hours) postings on
Ashby/Greenhouse/Lever/Workday that are a genuine match, searching each
platform separately (see tavily_search.py — Tavily has no pagination, so
this is what actually maximizes coverage instead of one shared,
crowded-out result budget) and fetching each matched posting directly
from its own platform's API (see job_boards.py) rather than pulling an
entire company's board for the sake of one URL.

Pipeline, cheapest checks first so nothing expensive runs on a posting
that was going to be discarded anyway:
    search (per keyword x platform) -> dedupe -> per-posting API fetch
    -> freshness filter -> seen-in-db filter -> keyword pre-filter
    (free) -> title-only seniority pre-filter (free — a "Senior"/
    "Staff"/"SDE-3"-style title well above the candidate's
    max_years_experience is rejected without ever fetching a
    description or spending an LLM call on it) -> LLM relevance
    judgment (not free, only for what survives all the free filters)
    -> persist verdict to db

stream_discover_jobs is an async generator (same pattern as
orchestrator_agent.stream_resume_pipeline) yielding (stage, data) events
for every one of those steps — the actual Tavily query sent per
platform, every posting fetched, and every job as it's judged with its
verdict — rather than only returning the final relevant list, so a
caller (cli.py's `discover` command) can show what's actually happening
under the hood while it runs, not just a spinner and a final table.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, NamedTuple

from weave_cv.agents.job_relevance_agent import score_relevance
from weave_cv.schemas.candidate_role_fit import CandidateRoleFit
from weave_cv.schemas.job_posting import DiscoveredJob
from weave_cv.services import db
from weave_cv.services.job_boards import SINGLE_JOB_FETCHERS, identify_posting
from weave_cv.services.tavily_search import PLATFORM_DOMAINS, search_for_keyword_and_platform


class RelevantJob(NamedTuple):
    job: DiscoveredJob
    reason: str


def _is_fresh(posted_at: datetime, max_age_hours: int) -> bool:
    now = datetime.now(timezone.utc)
    posted_at_utc = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    return now - posted_at_utc <= timedelta(hours=max_age_hours)


def _title_matches_keywords(title: str, keywords: list[str]) -> bool:
    """Cheap, deliberately loose pre-filter — its only job is to skip
    obviously-unrelated postings (e.g. a "Sales Manager" role when
    searching "backend engineer") before spending an LLM call, not to
    make the real relevance judgment. A single shared word is enough to
    pass a posting through to score_relevance; the precise call happens
    there, grounded in the full description."""
    title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
    for keyword in keywords:
        keyword_words = {w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) >= 2}
        if title_words & keyword_words:
            return True
    return False


# Rough, industry-typical minimum years of experience implied by a title
# alone — not a precise rule, just enough to short-circuit the clear-cut
# cases (a "Staff"/"Senior"/"SDE-3"/"SDE-2" posting for a 2-3 year
# candidate) before paying for a description fetch's worth of tokens and
# an LLM call. Genuinely ambiguous titles (no pattern match) still go to
# the real relevance judgment — this only ever removes cases the title
# already settles. SDE-2/Engineer II is deliberately set at 4, not the
# more literal "2" its name suggests — in practice that tier at most
# companies expects meaningfully more than 2-3 years, not just
# "post-entry-level."
_SENIORITY_MIN_YEARS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(principal|distinguished)\b", re.IGNORECASE), 8.0),
    (re.compile(r"\bstaff\b", re.IGNORECASE), 6.0),
    (re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE), 5.0),
    (re.compile(r"\blead\b", re.IGNORECASE), 5.0),
    (re.compile(r"\b(?:sde|swe|sse)[\s-]?(?:iii|3)\b", re.IGNORECASE), 5.0),
    (re.compile(r"\bengineer\s+(?:iii|3)\b", re.IGNORECASE), 5.0),
    (re.compile(r"\b(?:sde|swe|sse)[\s-]?(?:ii|2)\b", re.IGNORECASE), 4.0),
    (re.compile(r"\bengineer\s+(?:ii|2)\b", re.IGNORECASE), 4.0),
]
# Small and deliberately on the tight side — this only needs to cover
# "the candidate's own max_years_experience might be a slight
# underestimate," not "give postings a wide berth." A boundary case
# (candidate's max + buffer lands exactly on a tier's minimum) is
# resolved as a mismatch below (<=, not <), matching what "even SDE-2 is
# a stretch for a 2-3 year profile" actually means in practice.
_SENIORITY_BUFFER_YEARS = 1.0


def _seniority_mismatch_reason(title: str, candidate: CandidateRoleFit) -> str | None:
    """None if no known senior-signal pattern matches the title (still
    goes to the real LLM judgment) or the implied minimum is within
    reach of the candidate's own max_years_experience. Otherwise the
    human-readable reason a posting gets rejected on title alone,
    without ever fetching a description or spending an LLM call on it —
    checked against every pattern (not just the first match) so the
    reported minimum is the highest one the title actually triggers."""
    worst: tuple[re.Pattern, float] | None = None
    for pattern, min_years in _SENIORITY_MIN_YEARS:
        if pattern.search(title) and (worst is None or min_years > worst[1]):
            worst = (pattern, min_years)
    if worst is None:
        return None
    pattern, min_years = worst
    if candidate.max_years_experience + _SENIORITY_BUFFER_YEARS > min_years:
        return None
    return (
        f"Title implies a level requiring roughly {min_years:g}+ years "
        f"experience; candidate's range tops out at "
        f"{candidate.max_years_experience:g} years — filtered on title "
        "alone, before an LLM call."
    )


async def stream_discover_jobs(
    candidate: CandidateRoleFit, keywords: list[str], max_age_hours: int = 48,
    ignore_seen: bool = False,
) -> AsyncIterator[tuple[str, dict]]:
    """ignore_seen=True skips the "already scored before" filter, so a
    posting that was recorded (relevant or not) on an earlier run gets
    re-judged instead of silently staying skipped forever — useful when
    the actual problem is a shrinking pool of not-yet-seen postings
    rather than anything wrong with the judgment itself. The verdict is
    still persisted either way (db.save_discovered_job now upserts), so
    a rescan's fresh judgment replaces the old one rather than just
    being thrown away after this run ends."""
    postings_to_fetch: dict[tuple[str, str], None] = {}  # dict, not set: preserves first-seen order

    for keyword in keywords:
        for platform in PLATFORM_DOMAINS:
            results = await search_for_keyword_and_platform(keyword, platform)
            yield "search", {
                "keyword": keyword,
                "platform": platform,
                "domains": PLATFORM_DOMAINS[platform],
                "results_count": len(results),
            }
            for result in results:
                match = identify_posting(result.get("url", ""))
                if match:
                    postings_to_fetch[match] = None

    yield "urls_found", {"count": len(postings_to_fetch)}

    all_postings: list[DiscoveredJob] = []
    for platform, fetch_key in postings_to_fetch:
        try:
            job = await SINGLE_JOB_FETCHERS[platform](fetch_key)
        except Exception as e:
            yield "fetch_error", {"platform": platform, "error": str(e)}
            continue
        if job is None:
            yield "fetch_miss", {"platform": platform}
            continue
        yield "fetched", {"platform": platform, "title": job.title, "company": job.company_name or job.company}
        all_postings.append(job)

    fresh = [p for p in all_postings if _is_fresh(p.posted_at, max_age_hours)]
    unseen = fresh if ignore_seen else [
        p for p in fresh if not db.has_discovered(p.platform, p.company, p.job_id)
    ]
    keyword_matched = [p for p in unseen if _title_matches_keywords(p.title, keywords)]

    to_judge: list[DiscoveredJob] = []
    seniority_filtered_count = 0
    for posting in keyword_matched:
        reason = _seniority_mismatch_reason(posting.title, candidate)
        if reason is None:
            to_judge.append(posting)
            continue
        seniority_filtered_count += 1
        # Persisted same as an LLM verdict would be — discovered_jobs
        # tracks everything ever scored regardless of how, so a rerun
        # (or batch --from-db) sees a consistent, explained record
        # either way, not a silent gap.
        db.save_discovered_job(posting, False, reason)
        yield "seniority_filtered", {
            "title": posting.title,
            "company": posting.company_name or posting.company,
            "platform": posting.platform,
            "reason": reason,
        }

    yield "filtered", {
        "total_postings": len(all_postings),
        "fresh": len(fresh),
        "unseen": len(unseen),
        "keyword_matched": len(keyword_matched),
        "seniority_filtered": seniority_filtered_count,
        "to_judge": len(to_judge),
    }

    for posting in to_judge:
        yield "judging", {
            "title": posting.title,
            "company": posting.company_name or posting.company,
            "platform": posting.platform,
            "url": posting.url,
        }
        verdict = await score_relevance(candidate, posting)
        # Persisted regardless of the verdict — the goal is never
        # re-scoring the same posting on a future run, not just never
        # re-showing a match. batch --from-db later reads this same
        # table filtered to relevant=1 AND not yet in applied_jobs.
        db.save_discovered_job(posting, verdict.relevant, verdict.reason)
        yield "verdict", {
            "job": posting,
            "title": posting.title,
            "company": posting.company_name or posting.company,
            "relevant": verdict.relevant,
            "reason": verdict.reason,
        }
