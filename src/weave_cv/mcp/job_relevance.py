from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("job_relevance", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the job relevance agent"""
    return load_prompt("job_relevance.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
