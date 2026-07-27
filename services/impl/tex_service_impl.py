import platform
import re
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Union

import pypandoc
from TexSoup import TexSoup

from services.tex_service import TexService

SectionContent = Union[str, List[Dict[str, str]]]

TECTONIC_VERSION = "0.16.9"

# (platform.system(), platform.machine()) -> (release target triple, archive ext)
_TECTONIC_TARGETS = {
    ("Darwin", "arm64"): ("aarch64-apple-darwin", "tar.gz"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin", "tar.gz"),
    ("Linux", "x86_64"): ("x86_64-unknown-linux-gnu", "tar.gz"),
    ("Linux", "aarch64"): ("aarch64-unknown-linux-musl", "tar.gz"),
    ("Windows", "AMD64"): ("x86_64-pc-windows-msvc", "zip"),
    ("Windows", "x86_64"): ("x86_64-pc-windows-msvc", "zip"),
}


def _tectonic_cache_dir() -> Path:
    return Path.home() / ".cache" / "weave-cv" / "tectonic" / TECTONIC_VERSION


def _download_tectonic(cache_dir: Path) -> Path:
    key = (platform.system(), platform.machine())
    if key not in _TECTONIC_TARGETS:
        raise RuntimeError(f"No tectonic build available for platform {key}")
    target, ext = _TECTONIC_TARGETS[key]

    asset = f"tectonic-{TECTONIC_VERSION}-{target}.{ext}"
    url = (
        "https://github.com/tectonic-typesetting/tectonic/releases/download/"
        f"tectonic%40{TECTONIC_VERSION}/{asset}"
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / asset
    urllib.request.urlretrieve(url, archive_path)

    if ext == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(cache_dir)
    else:
        with tarfile.open(archive_path) as tf:
            tf.extractall(cache_dir)
    archive_path.unlink()

    binary_path = cache_dir / ("tectonic.exe" if platform.system() == "Windows" else "tectonic")
    if not binary_path.exists():
        raise RuntimeError(f"Expected {binary_path} after extracting tectonic")

    binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return binary_path


def _tectonic_binary() -> Path:
    """Returns a local tectonic binary, downloading it into a per-version
    cache dir on first use. Avoids depending on a system-wide TeX install,
    since this tool's users won't all have one."""
    cache_dir = _tectonic_cache_dir()
    binary_path = cache_dir / ("tectonic.exe" if platform.system() == "Windows" else "tectonic")
    if binary_path.exists():
        return binary_path
    return _download_tectonic(cache_dir)


class TexServiceImpl(TexService):
    def __init__(self) -> None:
        super().__init__()

    def parse_tex_as_tree(self, tex_file_path: str) -> Dict[str, SectionContent]:
        with open(tex_file_path, "r", encoding="utf-8") as f:
            tex_str = f.read()

        try:
            soup = TexSoup(self._extract_document_body(tex_str))
        except Exception:
            return {"content": self._strip_comments(tex_str)}

        container = soup.find("document") or soup
        sections = self._split_by_section(container)

        if len(sections) < 2:
            return {"content": self._strip_comments(str(container))}

        return {title: self._build_section(nodes) for title, nodes in sections.items()}

    def parse_tex_as_text(self, tex_file_path: str) -> str:
        """Cheaper alternative to parse_tex_as_tree: strips the preamble and
        comments and hands back the document body as plain text, with no
        TexSoup parsing and no section structuring. Lets the LLM doing the
        extraction figure out structure itself instead of relying on a
        generic parser to get every template's macros right."""
        with open(tex_file_path, "r", encoding="utf-8") as f:
            tex_str = f.read()

        return self._strip_comments(self._extract_document_body(tex_str))

    @staticmethod
    def _extract_document_body(tex_str: str) -> str:
        """Preamble macros (\\titleformat, \\newcommand, margins, etc.) are
        template plumbing, never resume content, and their custom argument
        signatures can trip up TexSoup 0.3.3's generic parser. Parsing only
        the \\begin{document}...\\end{document} body sidesteps that and keeps
        the parsed tree free of preamble noise."""
        start = tex_str.find(r"\begin{document}")
        if start == -1:
            return tex_str
        end = tex_str.find(r"\end{document}")
        if end == -1:
            return tex_str[start:]
        return tex_str[start : end + len(r"\end{document}")]

    def _split_by_section(self, container) -> Dict[str, list]:
        """Groups a document's top-level nodes under their nearest preceding
        \\section{}/\\section*{} header. TexSoup 0.3.3 exposes no sibling
        links, so sections are inferred by walking the flat contents list."""
        sections: Dict[str, list] = {}
        current_title = None
        current_nodes: list = []

        for node in container.contents:
            if getattr(node, "name", None) in ("section", "section*"):
                if current_title is not None:
                    sections[current_title] = current_nodes
                current_title = str(node.args[0].string).strip()
                current_nodes = []
            elif current_title is not None:
                current_nodes.append(node)

        if current_title is not None:
            sections[current_title] = current_nodes

        return sections

    def _build_section(self, nodes: list) -> SectionContent:
        """A section whose top-level nodes all share one tag (e.g. a run of
        \\cventry{}) is almost certainly a list of entries produced by the
        same macro, so it's split into one chunk per entry, tagged with that
        macro name as a hint for the LLM. Anything else (mixed/plain-text
        entries, whose boundaries a generic parser can't tell apart across
        arbitrary templates) is left as a single raw block."""
        content_nodes = [n for n in nodes if str(n).strip()]
        tags = {getattr(n, "name", None) for n in content_nodes}

        if len(content_nodes) > 1 and len(tags) == 1:
            return [
                {"tag": n.name, "content": self._strip_comments(str(n).strip())}
                for n in content_nodes
            ]

        raw = "".join(str(n) for n in nodes).strip()
        return self._strip_comments(raw)

    @staticmethod
    def _strip_comments(text: str) -> str:
        lines = (re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())
        return "\n".join(lines).strip()
    
    def is_valid_tex(self, tex_str: str) -> bool:
        success, _ = self._compile_pdf(tex_str)
        return success

    def tex_to_pdf(self, tex: str, output_path: str) -> bytes | None:
        success, pdf_bytes = self._compile_pdf(tex)
        if not success or pdf_bytes is None:
            return None

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_bytes)
        return pdf_bytes

    def tex_to_docx(self, tex: str, output_path: str) -> bytes | None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._convert_to_docx(tex, out_path)
        except OSError:
            pypandoc.download_pandoc()
            self._convert_to_docx(tex, out_path)
        except RuntimeError:
            return None

        return out_path.read_bytes()

    @staticmethod
    def _convert_to_docx(tex: str, out_path: Path) -> None:
        pypandoc.convert_text(tex, to="docx", format="latex", outputfile=str(out_path))

    @staticmethod
    def _compile_pdf(tex_str: str) -> tuple[bool, bytes | None]:
        """Compiles tex_str with tectonic in a scratch dir and returns
        (success, pdf_bytes). Shared by is_valid_tex and tex_to_pdf since
        both need the same compile step, just with different outcomes."""
        binary = _tectonic_binary()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tex_path = tmp_path / "input.tex"
            tex_path.write_text(tex_str, encoding="utf-8")

            try:
                result = subprocess.run(
                    [str(binary), "-o", str(tmp_path), str(tex_path)],
                    capture_output=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                return False, None

            if result.returncode != 0:
                return False, None

            return True, (tmp_path / "input.pdf").read_bytes()

# def update_latex_tree(original_latex: str, target_section: str, new_content: str) -> str:
#     """Injects a modified string back into its original structural node."""
#     soup = TexSoup(original_latex)
#     container = soup.find('document') or soup
#     contents = list(container.contents)
#     section_indices = [i for i, n in enumerate(contents) if getattr(n, 'name', None) == 'section']

#     for pos, start in enumerate(section_indices):
#         section = contents[start]
#         if str(section.args[0].string).strip() != target_section:
#             continue

#         # Body nodes run from just after this section header up to the next one
#         end = section_indices[pos + 1] if pos + 1 < len(section_indices) else len(contents)
#         body_nodes = contents[start + 1:end]

#         # Parse the new tailored fragment into fresh, parentless nodes
#         new_nodes = [n.copy() for n in TexSoup(new_content).contents]

#         # replace_with is identity-based (unlike insert(), whose index space
#         # includes whitespace tokens TexSoup hides from .contents), so we use
#         # it to swap the section header for [header copy, *new content] and
#         # then drop the stale body nodes individually.
#         section_copy = section.copy()
#         section.replace_with(section_copy, *new_nodes)
#         for node in body_nodes:
#             node.delete()
#         break

#     # Casting TexSoup object to str cleanly renders it back as raw LaTeX
#     return str(soup)