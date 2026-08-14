from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("cover_letter", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the cover letter agent"""
    return load_prompt("cover_letter.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
