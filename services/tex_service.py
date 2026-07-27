from typing import Protocol, Any, Dict, List, Optional


class TexService(Protocol):
    def parse_tex_as_tree(self, tex_file_path: str) -> Dict:
        """"""
        ...

    def parse_tex_as_text(self, tex_file_path: str) -> str:
        """Return the file's document body (preamble and comments stripped)
        as plain text, with no section structuring."""
        ...

    def is_valid_tex(self, tex_str: str) -> bool:
        """"""
        ...

    def tex_to_docx(self, tex: str, output_path: str) -> bytes | None:
        """Convert a TeX string to a DOCX file, write it to output_path, and
        return the bytes of the DOCX file."""
        ...

    def tex_to_pdf(self, tex: str, output_path: str) -> bytes | None:
        """Convert a TeX string to a PDF file, write it to output_path, and
        return the bytes of the PDF file."""
        ...
 