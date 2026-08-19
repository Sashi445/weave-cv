"""Identifies which platform+specific-posting a URL points to, and fetches
that ONE posting directly from the platform's own public,
unauthenticated JSON API — verified live against real postings, not
assumed from docs alone. Deliberately excludes Work at a Startup: it has
no public API and requires a YC account login to browse at all.

Earlier versions of this module fetched a company's ENTIRE current
posting list on the theory that search might only surface one stale URL
while the company has other, fresher, more relevant postings a
company-wide pull would also catch. In practice this meant one Tavily
hit for a large employer (Autodesk: 508 open postings) turned into
hundreds of postings fetched (and for Workday, an expensive paginated
list-scan) to act on the one URL search actually found. Acting directly
on what search returned — one HTTP call per posting, no broader pull —
is both cheaper and more precise: repeated keyword searches naturally
resurface any other postings from the same company that are genuinely
relevant, rather than opportunistically harvesting everything nearby.

Every fetcher shares the same (fetch_key: str) -> DiscoveredJob | None
signature (see SINGLE_JOB_FETCHERS) — fetch_key is an opaque,
platform-specific string only that platform's fetcher gives meaning to
(see identify_posting).
"""

import html as html_lib
import re
from datetime import datetime, timezone

import httpx

from weave_cv.schemas.job_posting import DiscoveredJob

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTTP_TIMEOUT = 15.0


def _strip_html(content: str) -> str:
    """Good-enough plain text for an LLM relevance judgment — not meant
    to be a faithful rendering, just readable, so a regex strip (no new
    HTML-parsing dependency) is enough. Unescapes twice: Greenhouse's
    `content` field is double-HTML-encoded throughout — both tags
    ("&amp;lt;p&amp;gt;" for "<p>") and entities ("&amp;nbsp;" for
    "&nbsp;") — confirmed against a real posting, not assumed. A single
    unescape only peels off the outer layer, leaving literal "&nbsp;"
    text behind; a second pass is a no-op on already-plain text, so it's
    safe to always apply regardless of whether a given field turns out
    to be single- or double-encoded."""
    unescaped = html_lib.unescape(html_lib.unescape(content))
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", unescaped)).strip()


# (platform, company, job-id) extraction, in document order per URL — a
# platform is picked by whichever pattern matches first, so ordering here
# doesn't affect correctness (patterns are mutually exclusive domains),
# only readability. Each captures both the company slug AND the specific
# job ID, since fetching now targets exactly the posting the URL points
# to — confirmed live that both Greenhouse and Lever expose a
# single-job-by-ID endpoint (Ashby doesn't; see fetch_ashby_job).
_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/]+)/([^/?#]+)")),
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs?/(\d+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/]+)/([^/?#]+)")),
]

# Workday doesn't fit the single-regex-captures-slug-and-id shape the
# other three do: every tenant's careers site lives at
# "{tenant}.wd{N}.myworkdayjobs.com/{...path...}", where the path may or
# may not include a locale segment ("en-US") and may or may not include a
# location segment before the job slug — confirmed by checking 4 real
# tenants (Autodesk, Zebra, Stord, Empower), which all differ on both.
# The one constant across every shape is a literal "/job/" segment, so
# the "site" slug the wday/cxs API needs is taken as whatever path
# segment immediately precedes it, not a fixed position — and everything
# from "/job/" onward IS the externalPath the detail endpoint needs, so
# no separate job-ID extraction is required for this platform.
_WORKDAY_HOST_RE = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com(/[^\s\"']*)", re.IGNORECASE)
_WORKDAY_SITE_RE = re.compile(r"/([^/]+)(/job/.*)")


def _detect_workday(url: str) -> tuple[str, str] | None:
    host_match = _WORKDAY_HOST_RE.search(url)
    if not host_match:
        return None
    tenant, wd_cluster, path = host_match.group(1), host_match.group(2), host_match.group(3)
    site_match = _WORKDAY_SITE_RE.search(path)
    if not site_match:
        return None
    tenant_host = f"{tenant}.{wd_cluster}.myworkdayjobs.com"
    site, external_path = site_match.group(1), site_match.group(2)
    # Encodes all 4 pieces fetch_workday_job needs into the single opaque
    # fetch_key string every fetcher's signature expects — the other
    # platforms' fetch_key is just "company::job_id"; only
    # fetch_workday_job gives this shape any special meaning.
    return "workday", f"{tenant_host}::{tenant}::{site}::{external_path}"


def identify_posting(url: str) -> tuple[str, str] | None:
    """None if the URL doesn't match any known ATS job-posting pattern —
    the caller's job to discard, not this function's to guess at.
    Otherwise (platform, fetch_key) for that ONE specific posting."""
    for platform, pattern in _URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return platform, f"{match.group(1)}::{match.group(2)}"
    return _detect_workday(url)


async def fetch_greenhouse_job(fetch_key: str) -> DiscoveredJob | None:
    company, job_id = fetch_key.split("::")
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await client.get(url, params={"content": "true"})
    if response.status_code != 200:
        return None

    job = response.json()
    return DiscoveredJob(
        platform="greenhouse",
        company=company,
        company_name=job.get("company_name"),
        job_id=str(job["id"]),
        title=job["title"],
        url=job["absolute_url"],
        location=(job.get("location") or {}).get("name"),
        posted_at=datetime.fromisoformat(job["updated_at"]),
        description=_strip_html(job.get("content") or ""),
    )


async def fetch_lever_job(fetch_key: str) -> DiscoveredJob | None:
    company, job_id = fetch_key.split("::")
    url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await client.get(url, params={"mode": "json"})
    if response.status_code != 200:
        return None

    posting = response.json()
    if not posting or "id" not in posting:
        return None
    return DiscoveredJob(
        platform="lever",
        company=company,
        company_name=None,  # Lever's postings API doesn't expose a separate display name
        job_id=posting["id"],
        title=posting["text"],
        url=posting["hostedUrl"],
        location=(posting.get("categories") or {}).get("location"),
        # createdAt is epoch milliseconds, not an ISO string, unlike the other platforms.
        posted_at=datetime.fromtimestamp(posting["createdAt"] / 1000, tz=timezone.utc),
        description=posting.get("descriptionPlain") or "",
    )


# Ashby's public API has no single-job endpoint — every call returns the
# whole board (confirmed against its docs and live) — so multiple postings
# found from the same Ashby company within one `discover` run share one
# fetch instead of re-pulling the same board per posting. Deliberately a
# plain module-level dict (not a decorator/LRU cache): scoped to the
# lifetime of one `weave-cv discover` process, which is exactly the
# window a board's contents can be safely treated as unchanging.
_ashby_board_cache: dict[str, list[dict]] = {}


async def _get_ashby_board(company: str) -> list[dict]:
    if company not in _ashby_board_cache:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(url)
        _ashby_board_cache[company] = response.json().get("jobs", []) if response.status_code == 200 else []
    return _ashby_board_cache[company]


async def fetch_ashby_job(fetch_key: str) -> DiscoveredJob | None:
    company, job_id = fetch_key.split("::")
    for job in await _get_ashby_board(company):
        # isListed=false postings are returned by this API but aren't meant to be
        # publicly surfaced (Ashby's own docs flag this) — skip it, same as a
        # company's own careers page would, even if the URL still resolves.
        if job.get("id") == job_id and job.get("isListed", True):
            return DiscoveredJob(
                platform="ashby",
                company=company,
                company_name=None,  # Ashby's job-board API doesn't expose a separate display name either
                job_id=job["id"],
                title=job["title"],
                url=job["jobUrl"],
                location=job.get("location"),
                posted_at=datetime.fromisoformat(job["publishedAt"]),
                description=job.get("descriptionPlain") or "",
            )
    return None


async def fetch_workday_job(fetch_key: str) -> DiscoveredJob | None:
    """A single detail GET using the externalPath already embedded in the
    URL search found — no list-endpoint pagination needed at all now
    that we're not trying to discover a company's other postings, only
    act on the one URL in hand."""
    tenant_host, tenant, site, external_path = fetch_key.split("::")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await client.get(f"https://{tenant_host}/wday/cxs/{tenant}/{site}{external_path}")
    if response.status_code != 200:
        return None

    info = response.json().get("jobPostingInfo", {})
    start_date = info.get("startDate")
    if not start_date:
        return None
    return DiscoveredJob(
        platform="workday",
        company=tenant,
        company_name=None,
        job_id=str(info.get("jobReqId") or info.get("id") or external_path),
        title=info.get("title") or "",
        url=info.get("externalUrl") or f"https://{tenant_host}/{site}{external_path}",
        location=info.get("location"),
        posted_at=datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc),
        description=_strip_html(info.get("jobDescription") or ""),
    )


SINGLE_JOB_FETCHERS = {
    "ashby": fetch_ashby_job,
    "greenhouse": fetch_greenhouse_job,
    "lever": fetch_lever_job,
    "workday": fetch_workday_job,
}
