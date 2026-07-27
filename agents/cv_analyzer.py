from langchain_mcp_adapters.client import MultiServerMCPClient
from language_models.index import openai_mini
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage
from schemas.cv_analysis import CVProfile

client = MultiServerMCPClient({
    "cv_analyzer": {
        "transport": "stdio",
        "command": "python",
        "args": ["mcp/cv_analyzer/index.py"]
    },
    "tex_tools": {
        "transport": "stdio",
        "command": "python",
        "args": ["mcp/tex/index.py"]
    }
})


async def _get_prompt_and_tools():
    prompt_data = await client.get_prompt("cv_analyzer", "system_prompt")
    prompt = SystemMessage(content=prompt_data[0].content)

    all_tools = await client.get_tools(server_name="tex_tools")
    tools = [t for t in all_tools if t.name == "parse_tex_as_text"]

    return prompt, tools


async def make_cv_analyzer_agent():
    prompt, tools = await _get_prompt_and_tools()

    return create_agent(
        model=openai_mini,
        system_prompt=prompt,
        tools=tools,
        response_format=CVProfile,
        name="CV-Analyzer"
    )