"""
    This agent is designed to analyze job descriptions and extract relevant
    information such as required skills, qualifications, and responsibilities.
    It can also provide insights into the job market and trends based on the
    analysis of multiple job descriptions.
"""

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import SystemMessage, HumanMessage
from weave_cv.language_models.index import get_model
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.jd_analysis import JobDescriptionAnalysis
from weave_cv.services.web_scraper import scrape_url

mcp_client = MultiServerMCPClient(
    {
        "jd_analyzer": {
            "transport": "stdio",
            "command": "python",
            "args": [mcp_script_path("jd_analyzer", "index.py")]
        }
    }
)

async def _get_prompt() -> SystemMessage:
    prompt = await mcp_client.get_prompt("jd_analyzer", "prompt")
    return SystemMessage(content=prompt[0].content)

async def make_jd_analyzer_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=JobDescriptionAnalysis,
        checkpointer=None,
        name="JD-Analyzer"
    )

async def analyze_job_posting(job_url: str) -> JobDescriptionAnalysis:
    """Scrapes job_url deterministically (no LLM/tool-call involved), then
    hands the scraped page straight to a single-shot structured-extraction
    call. Replaces the old design where the agent itself decided whether
    to call a scraping tool — there was never a real decision to make
    there ("fetch this page" has one right answer), so that was an LLM
    round trip bought for nothing.
    """
    scraped_content = await scrape_url(job_url)
    agent = await make_jd_analyzer_agent()
    result = await agent.ainvoke({
        "messages": [
            HumanMessage(
                content=f"Analyze this job posting, scraped from '{job_url}':\n\n{scraped_content}"
            )
        ]
    })
    return result["structured_response"]
