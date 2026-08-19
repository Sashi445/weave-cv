from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from weave_cv.language_models.index import cacheable_system_message, get_model
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.candidate_role_fit import CandidateRoleFit
from weave_cv.schemas.job_posting import DiscoveredJob, RelevanceVerdict

mcp_client = MultiServerMCPClient({
    "job_relevance": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("job_relevance.py")]
    }
})


async def _get_prompt():
    prompt = await mcp_client.get_prompt("job_relevance", "prompt")
    return cacheable_system_message(prompt[0].content)


async def make_job_relevance_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=RelevanceVerdict,
        name="Job-Relevance"
    )


async def score_relevance(candidate: CandidateRoleFit, job: DiscoveredJob) -> RelevanceVerdict:
    agent = await make_job_relevance_agent()

    instruction = (
        "Judge this job posting against the candidate profile below. Title "
        "only — no description is provided on purpose.\n\n"
        f"Candidate profile:\n{candidate.model_dump_json(indent=2)}\n\n"
        f"Job posting:\nTitle: {job.title}\n"
        f"Location: {job.location or 'not specified'}"
    )

    response = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
    return response["structured_response"]
