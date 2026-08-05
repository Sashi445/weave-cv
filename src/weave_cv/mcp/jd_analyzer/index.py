from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("jd_analyzer", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Return the system prompt for the JD-Analyzer agent."""
    return load_prompt("jd_analyzer.txt")

if __name__ == "__main__":
    mcp_server.run(transport="stdio")