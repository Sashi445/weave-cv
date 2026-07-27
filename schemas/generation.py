from pydantic import BaseModel, Field


class GeneratedResumeBody(BaseModel):
    tex_body: str = Field(
        description="The LaTeX content between \\begin{document} and "
        "\\end{document} only — no preamble, no "
        "\\begin{document}/\\end{document} tags themselves."
    )
