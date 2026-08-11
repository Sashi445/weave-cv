"""Deterministic web scraping for job postings, extracted out of what used
to be an MCP tool the JD-Analyzer agent decided whether to call
(mcp/web_scrape/index.py, now removed). Scraping a URL has exactly one
right answer — there's no judgment call in "fetch this page" — so having
an LLM spend a tool-call round trip deciding to invoke it added cost and
latency for zero benefit. Calling this directly from orchestrator code and
handing the result straight to a single-shot extraction call removes that
round trip entirely.
"""

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


async def _run_crawl(browser_conf: BrowserConfig, run_conf: CrawlerRunConfig, url: str):
    async with AsyncWebCrawler(config=browser_conf) as crawler:
        return await crawler.arun(url, config=run_conf)


def _install_chromium() -> None:
    """Downloads Playwright's chromium build into its standard per-OS cache
    dir. A no-op if it's already installed, so safe to call speculatively."""
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        capture_output=True,
    )


async def scrape_url(url: str) -> str:
    """Scrape url and return its content as markdown. Never raises on a
    scrape that "succeeds" but returns unusable content (e.g. a bot-block
    page) — instead returns an "Error: ..." string the JD-Analyzer prompt
    is written to recognize and handle as `is_job_posting: false`, the
    same contract the old MCP tool had.
    """
    browser_conf = BrowserConfig(headless=True)
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        delay_before_return_html=2.0,
    )

    try:
        result = await _run_crawl(browser_conf, run_conf, url)
    except Exception as e:
        if "Executable doesn't exist" not in str(e):
            raise
        _install_chromium()
        result = await _run_crawl(browser_conf, run_conf, url)

    markdown = str(result.markdown)
    if len(markdown.strip()) < 50:
        return (
            "Error: scraping this page returned little to no content. The "
            "page may require additional rendering time or block automated "
            "access."
        )
    return markdown
