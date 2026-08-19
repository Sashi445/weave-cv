from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from weave_cv.language_models.index import cacheable_system_message, get_model
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.candidate_role_fit import CandidateRoleFit
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.services.candidate_role_fit_cache import get_cached_role_fit, save_role_fit_to_cache

mcp_client = MultiServerMCPClient({
    "candidate_role_fit": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("candidate_role_fit.py")]
    }
})


async def _get_prompt():
    prompt = await mcp_client.get_prompt("candidate_role_fit", "prompt")
    return cacheable_system_message(prompt[0].content)


async def make_candidate_role_fit_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=CandidateRoleFit,
        name="Candidate-Role-Fit"
    )


async def get_or_build_candidate_role_fit(cv_path: str, cv_profile: CVProfile) -> CandidateRoleFit:
    """Cache-first, same shape as cv_analyzer.analyze_cv: a cache hit
    (keyed on the master resume file's content hash) skips the agent
    entirely, so this LLM call only ever happens once per resume, not
    once per `discover` run and never once per job posting."""
    cached = get_cached_role_fit(cv_path)
    if cached is not None:
        return cached

    agent = await make_candidate_role_fit_agent()
    instruction = f"Distill this CVProfile:\n\n{cv_profile.model_dump_json(indent=2)}"
    response = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
    role_fit = response["structured_response"]

    # Set directly, not left to the LLM to copy through — a plain 1:1
    # field with zero judgment involved shouldn't have any chance of
    # being mistyped or dropped by a model call.
    role_fit.location = cv_profile.contact.location

    save_role_fit_to_cache(cv_path, role_fit)
    return role_fit
