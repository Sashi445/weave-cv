from langchain_mcp_adapters.client import MultiServerMCPClient
from weave_cv.language_models.index import cacheable_system_message, get_model
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.services.cv_cache import get_cached_cv_profile, save_cv_profile_to_cache

client = MultiServerMCPClient({
    "cv_analyzer": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("cv_analyzer", "index.py")]
    },
    "tex_tools": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("tex", "index.py")]
    }
})


async def _get_prompt_and_tools():
    prompt_data = await client.get_prompt("cv_analyzer", "system_prompt")
    prompt = cacheable_system_message(prompt_data[0].content)

    all_tools = await client.get_tools(server_name="tex_tools")
    tools = [t for t in all_tools if t.name == "parse_tex_as_text"]

    return prompt, tools


async def make_cv_analyzer_agent():
    prompt, tools = await _get_prompt_and_tools()

    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        tools=tools,
        response_format=CVProfile,
        name="CV-Analyzer"
    )


async def analyze_cv(cv_path: str) -> CVProfile:
    """Cache-first: the master resume rarely changes between runs, so a
    cache hit (keyed on the file's content hash — see services/cv_cache.py)
    skips both the agent-construction MCP round trip and the LLM call
    entirely, returning the previously extracted CVProfile as-is. Only a
    cache miss pays for a real analysis, whose result is then cached for
    next time. Shared by orchestrator_agent's tailor pipeline and the
    standalone `discover` command — both need "the user's CVProfile,
    computed once" and neither should duplicate this cache-or-analyze
    logic on its own.
    """
    cached = get_cached_cv_profile(cv_path)
    if cached is not None:
        return cached

    agent = await make_cv_analyzer_agent()
    result = await agent.ainvoke({
        "messages": [
            HumanMessage(content=f"Analyze my resume located at '{cv_path}'")
        ]
    })
    profile = result["structured_response"]
    save_cv_profile_to_cache(cv_path, profile)
    return profile