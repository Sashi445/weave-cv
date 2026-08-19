"""Search is only ever used here to discover which specific postings are
worth acting on — never as the actual data source (see job_boards.py,
which re-fetches each posting from its platform's own API directly).
Ashby, Greenhouse, Lever, and Workday each have a clean public JSON API
per posting but no site-wide search of their own, so there's no way to
ask any of them "what's new" without already knowing a specific URL. A
keyword search restricted to their domains is what supplies that,
fresh on every run — nothing is pre-compiled or persisted between runs.

One search per (keyword, platform) pair, not one combined search across
all platforms — Tavily's max_results is a hard ceiling of 20 per call
with no pagination/offset (confirmed against its docs, not assumed), so
a single combined call sharing that budget across 4 platforms means
whichever platform ranks highest crowds out the other three. Scoping
each call to one platform's domain(s) gives every platform its own
20-result budget instead, which is the real lever for more coverage —
there's no actual "page 2" to ask Tavily for.
"""

from tavily import AsyncTavilyClient

from weave_cv.services.tavily_client import get_tavily_client

PLATFORM_DOMAINS: dict[str, list[str]] = {
    "ashby": ["jobs.ashbyhq.com"],
    "greenhouse": ["boards.greenhouse.io", "job-boards.greenhouse.io"],
    "lever": ["jobs.lever.co"],
    # Every Workday tenant gets its own numbered subdomain
    # ("autodesk.wd1.myworkdayjobs.com", "zebra.wd501.myworkdayjobs.com",
    # ...) with no bound on the number — a wildcard is the only way to
    # cover all of them; Tavily's docs confirm glob-style domain patterns
    # are supported (e.g. "*.com"), not just exact hostnames.
    "workday": ["*.myworkdayjobs.com"],
}


async def search_for_keyword_and_platform(keyword: str, platform: str, max_results: int = 20) -> list[dict]:
    """One Tavily search call scoped to a single platform's domain(s),
    via include_domains (Tavily's own filter, not a "site:" query hack),
    with time_range="week" as a loose bias toward recent results — not
    the real freshness check, which happens later against the posting's
    own timestamp once fetched directly from its platform's API. Returns
    the raw result list (title/url/content/score dicts) rather than
    pre-extracting matches, so the caller (see
    job_discovery_agent.stream_discover_jobs) can report exactly what
    was searched and what came back.
    """
    client: AsyncTavilyClient = get_tavily_client()
    response = await client.search(
        query=keyword,
        include_domains=PLATFORM_DOMAINS[platform],
        max_results=max_results,
        time_range="week",
        search_depth="basic",
    )
    return response.get("results", [])
