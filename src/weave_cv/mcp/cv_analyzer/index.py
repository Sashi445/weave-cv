from mcp.server.fastmcp import FastMCP

from weave_cv.prompts import load_prompt

mcp_server = FastMCP("cv_analyzer", log_level="ERROR")

@mcp_server.prompt()
def system_prompt() -> str:
    """Return the system prompt for the CV-Analyzer agent."""
    return load_prompt("cv_analyzer.txt")

# @mcp_server.resource("")
# def get_cv_file(file_path: str) -> str:
#     """Return the resume in string format by reading the .tex file from the disk"""
#     with open(file_path, "r", encoding="utf-8") as f:
#         return f.read()

if __name__ == "__main__":
    mcp_server.run(transport="stdio")