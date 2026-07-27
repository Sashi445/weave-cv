from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("jd_analyzer")

@mcp_server.prompt()
def prompt() -> str:
    """Return the system prompt for the JD-Analyzer agent."""
    with open("prompts/jd_analyzer.txt", "r") as f:
        return f.read()

if __name__ == "__main__":
    mcp_server.run(transport="stdio")