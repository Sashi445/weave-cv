from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from weave_cv.language_models.index import cacheable_system_message, get_model
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.cover_letter import CoverLetter
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.schemas.jd_analysis import JobDescriptionAnalysis

mcp_client = MultiServerMCPClient({
    "cover_letter": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("cover_letter.py")]
    }
})


async def _get_prompt():
    prompt = await mcp_client.get_prompt("cover_letter", "prompt")
    return cacheable_system_message(prompt[0].content)


async def make_cover_letter_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=CoverLetter,
        name="Cover-Letter"
    )


async def generate_cover_letter(
    cv_profile: CVProfile, jd_analysis: JobDescriptionAnalysis
) -> str:
    """Tailored CVProfile + JobDescriptionAnalysis -> plain-text cover
    letter content, ready to write straight to a .txt file."""
    agent = await make_cover_letter_agent()

    instruction = (
        "Write the cover letter for the CVProfile below, for the role "
        "described by the JobDescriptionAnalysis below.\n\n"
        f"CVProfile:\n{cv_profile.model_dump_json(indent=2)}\n\n"
        f"JobDescriptionAnalysis:\n{jd_analysis.model_dump_json(indent=2)}"
    )

    response = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
    result: CoverLetter = response["structured_response"]
    return result.content
