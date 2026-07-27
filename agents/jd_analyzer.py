"""
    This agent is designed to analyze job descriptions and extract relevant 
    information such as required skills, qualifications, and responsibilities. 
    It can also provide insights into the job market and trends based on the 
    analysis of multiple job descriptions.
"""

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import SystemMessage
from language_models.index import openai_nano
from schemas.jd_analysis import JobDescriptionAnalysis
import asyncio

mcp_client = MultiServerMCPClient(
    {
        "web_scrape": {
            "transport": "stdio",
            "command": "python",
            "args": ["mcp/web_scrape/index.py"]
        },
        "jd_analyzer": {
            "transport": "stdio",
            "command": "python",
            "args": ["mcp/jd_analyzer/index.py"]
        }
    }
)

async def _get_prompt_and_tools():
    tools = await mcp_client.get_tools()
    system_prompt = await (mcp_client.get_prompt("jd_analyzer", "prompt"))
    system_prompt = SystemMessage(content=system_prompt[0].content)
    return tools, system_prompt

async def make_jd_analyzer_agent():
    tools, prompt = await _get_prompt_and_tools()
    return create_agent(
        model=openai_nano,
        tools=tools,
        system_prompt=prompt,
        response_format=JobDescriptionAnalysis,
        checkpointer=None,
        name="JD-Analyzer"
    )
        
