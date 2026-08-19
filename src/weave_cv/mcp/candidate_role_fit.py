from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("candidate_role_fit", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the candidate role-fit agent"""
    return load_prompt("candidate_role_fit.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
