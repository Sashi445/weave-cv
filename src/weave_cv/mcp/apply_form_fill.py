from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("apply_form_fill", log_level="ERROR")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the application-form-fill agent"""
    return load_prompt("apply_form_fill.txt")

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
