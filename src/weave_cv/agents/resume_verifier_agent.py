from weave_cv.language_models.index import cacheable_system_message, get_model
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.messages import SystemMessage, HumanMessage
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.verification import SemanticVerification
from weave_cv.services.cv_diff import BulletChange

mcp_client = MultiServerMCPClient({
    "resume_verifier": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("resume_verifier.py")]
    }
})

async def _get_prompt():
    prompt = await mcp_client.get_prompt("resume_verifier", "prompt")
    return cacheable_system_message(prompt[0].content)

async def make_resume_verifier_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=SemanticVerification,
        name="Resume-Verifier"
    )

async def check_reworded_bullets(bullet_changes: list[BulletChange]) -> SemanticVerification:
    """Judge each (original, reworded) bullet pair for fact preservation.
    This is deliberately the *only* thing this agent is asked to do — the
    structural half of verification (new IDs, changed factual fields, new
    skill strings) is already handled deterministically by
    services/cv_diff.py before this ever runs, so the model's job here is
    narrow: read a bullet pair, judge whether the underlying fact changed.
    """
    if not bullet_changes:
        return SemanticVerification(bullet_verdicts=[], overall_passed=True)

    agent = await make_resume_verifier_agent()

    pairs_text = "\n\n".join(
        f"id: {bc.id}\nbefore: {bc.original_text}\nafter:  {bc.tailored_text}"
        for bc in bullet_changes
    )
    response = await agent.ainvoke({
        "messages": [
            HumanMessage(content=f"Judge these reworded bullet pairs:\n\n{pairs_text}")
        ]
    })
    return response["structured_response"]
