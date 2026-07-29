import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from weave_cv.services.tex_service import TexService
from weave_cv.services.impl.tex_service_impl import TexServiceImpl
from mcp.server.fastmcp import FastMCP
from typing import Dict

tex_service = TexServiceImpl()

mcp_server = FastMCP("tex_tools", log_level="ERROR")

@mcp_server.tool()
def parse_tex_as_dict(tex_file_path: str) -> Dict:
    """Parse a .tex file at tex_file_path into a section-structured dict,
    suitable for an LLM to extract a CVProfile from."""
    return tex_service.parse_tex_as_tree(tex_file_path=tex_file_path)

@mcp_server.tool()
def parse_tex_as_text(tex_file_path: str) -> str:
    """Parse a .tex file at tex_file_path into its document body as plain
    text (preamble and comments stripped, no section structuring),
    suitable for an LLM to extract a CVProfile from."""
    return tex_service.parse_tex_as_text(tex_file_path=tex_file_path)

@mcp_server.tool()
def validate_generated_tex(tex_str: str) -> bool:
    """Check whether a TeX string compiles without errors."""
    return tex_service.is_valid_tex(tex_str=tex_str)

@mcp_server.tool()
def tex_to_pdf(tex: str, output_path: str) -> str:
    """Compile a TeX string to a PDF and write it to output_path. Returns
    output_path on success; raises if the TeX fails to compile."""
    if tex_service.tex_to_pdf(tex=tex, output_path=output_path) is None:
        raise ValueError("Failed to compile tex to PDF: the tex is invalid.")
    return output_path

@mcp_server.tool()
def tex_to_docx(tex: str, output_path: str) -> str:
    """Convert a TeX string to a DOCX file and write it to output_path.
    Returns output_path on success; raises if the conversion fails."""
    if tex_service.tex_to_docx(tex=tex, output_path=output_path) is None:
        raise ValueError("Failed to convert tex to DOCX.")
    return output_path


if __name__ == '__main__':
    mcp_server.run(
        transport="stdio"
    )