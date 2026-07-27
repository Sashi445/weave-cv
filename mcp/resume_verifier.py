from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("resume_verifier")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the resume verifier agent"""
    with open("prompts/resume_verifier.txt", "r") as f:
        return f.read()

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
