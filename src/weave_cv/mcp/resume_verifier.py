from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("resume_verifier", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the resume verifier agent"""
    return load_prompt("resume_verifier.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
