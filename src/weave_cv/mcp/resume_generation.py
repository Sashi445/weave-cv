from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("resume_generation", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the resume generation agent"""
    return load_prompt("resume_generation.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
