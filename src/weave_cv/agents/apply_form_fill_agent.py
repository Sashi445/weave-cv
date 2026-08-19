import json

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from weave_cv.language_models.index import cacheable_system_message, get_model
from weave_cv.mcp import mcp_script_path
from weave_cv.schemas.application_form import ExtractedField, FormFillPlan
from weave_cv.schemas.cv_analysis import Contact

mcp_client = MultiServerMCPClient({
    "apply_form_fill": {
        "transport": "stdio",
        "command": "python",
        "args": [mcp_script_path("apply_form_fill.py")]
    }
})


async def _get_prompt():
    prompt = await mcp_client.get_prompt("apply_form_fill", "prompt")
    return cacheable_system_message(prompt[0].content)


async def make_apply_form_fill_agent():
    prompt = await _get_prompt()
    return create_agent(
        model=get_model(),
        system_prompt=prompt,
        response_format=FormFillPlan,
        name="Application-Form-Fill"
    )


async def plan_form_fill(contact: Contact, fields: list[ExtractedField]) -> FormFillPlan:
    """Empty fields list -> empty plan without spending an LLM call — a
    posting whose form had nothing left after the deterministic
    sensitive-field filter (see services/browser.is_sensitive_field)
    needs no judgment call at all."""
    if not fields:
        return FormFillPlan(decisions=[])

    agent = await make_apply_form_fill_agent()
    instruction = (
        "Decide fill-or-skip for each field below, given this candidate's contact info.\n\n"
        f"Contact:\n{contact.model_dump_json(indent=2)}\n\n"
        f"Fields:\n{json.dumps([f.model_dump() for f in fields], indent=2)}"
    )
    response = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
    return response["structured_response"]
