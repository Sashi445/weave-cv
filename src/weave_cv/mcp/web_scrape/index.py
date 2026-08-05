import subprocess
import sys

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("web_scrape", log_level="ERROR")


async def _run_crawl(browser_conf: BrowserConfig, run_conf: CrawlerRunConfig, url: str):
    async with AsyncWebCrawler(config=browser_conf) as crawler:
        return await crawler.arun(url, config=run_conf)


def _install_chromium() -> None:
    """Downloads Playwright's chromium build into its standard per-OS cache
    dir. A no-op if it's already installed, so safe to call speculatively.

    This process is an MCP stdio server — its own stdout is the JSON-RPC
    channel back to the client, not a normal terminal. Without
    capture_output, the child inherits this process's stdout/stderr file
    descriptors directly, so playwright's own install progress ("Downloading
    Chrome for Testing...", percentage bars, ...) gets written straight onto
    that same JSON-RPC stream and corrupts every message the client tries to
    parse afterward. capture_output=True redirects both into pipes this
    process reads instead of inheriting, and — unlike subprocess.DEVNULL —
    still keeps the output available on .stdout/.stderr if the install ever
    fails and raises CalledProcessError, instead of silently discarding it.
    """
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        capture_output=True,
    )


@mcp_server.tool()
async def scrape_link(url: str) -> str:
    """Scrape the content of a web page given its URL and return the extracted text in markdown format."""

    browser_conf = BrowserConfig(headless=True)  # or False to see the browser
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
        return "Error: scraping this page returned little to no content. The page may require additional rendering time or block automated access."
    return markdown


if __name__ == "__main__":
    # import asyncio
    # test_url = "https://jobs.ashbyhq.com/temporal/3b5595a4-87ec-4a5d-8a25-1be00e28c0a4"
    # response = asyncio.run(scrape_link(test_url))
    # print("Response: ", response)
    mcp_server.run(transport="stdio")