from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("resume_generation")

@mcp_server.prompt()
def prompt() -> str:
    """Returns system prompt for the resume generation agent"""
    with open("prompts/resume_generation.txt", "r") as f:
        return f.read()

if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )
