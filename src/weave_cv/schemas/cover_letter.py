from pydantic import BaseModel, Field


class CoverLetter(BaseModel):
    content: str = Field(
        description="The full cover letter, plain prose — no LaTeX, no "
        "markdown, ready to save as-is into a .txt file."
    )
