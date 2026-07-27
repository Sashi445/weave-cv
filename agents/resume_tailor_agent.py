from language_models.index import openai_mini
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.messages import SystemMessage, HumanMessage
from schemas.cv_analysis import CVProfile
from schemas.jd_analysis import JobDescriptionAnalysis

mcp_client = MultiServerMCPClient({
    "resume_tailoring": {
        "transport": "stdio",
        "command": "python",
        "args": ["mcp/resume_tailoring.py"]
    }
})

async def _get_prompt():
    prompt = await mcp_client.get_prompt("resume_tailoring", "prompt")
    return SystemMessage(content=prompt[0].content)

async def make_resume_tailor_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=openai_mini,
        system_prompt=prompt,
        response_format=CVProfile,
        name="Resume-Tailor"
    )

async def tailor(
    jd_profile: JobDescriptionAnalysis,
    cv_profile: CVProfile,
    feedback: str | None = None,
) -> CVProfile:
    """Tailor cv_profile against jd_profile and return the result.

    `feedback` is optional context from a prior failed verification pass
    (see agents/orchestrator_agent.py's retry loop) — pass the verifier's
    complaint back in so a retry can actually correct course instead of
    repeating the same mistake.
    """
    agent = await make_resume_tailor_agent()

    instruction = (
        "Tailor the CVProfile below against the JobDescriptionAnalysis "
        "below and return the tailored CVProfile.\n\n"
        f"JobDescriptionAnalysis:\n{jd_profile.model_dump_json(indent=2)}\n\n"
        f"CVProfile:\n{cv_profile.model_dump_json(indent=2)}"
    )
    if feedback:
        instruction += (
            "\n\nYour previous attempt failed verification for this reason "
            f"— fix it in this attempt:\n{feedback}"
        )

    response = await agent.ainvoke({
        "messages": [HumanMessage(content=instruction)]
    })
    return response["structured_response"]
