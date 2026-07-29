from pydantic import BaseModel, Field


class BulletVerdict(BaseModel):
    bullet_id: str = Field(description="The bullet's stable ID, copied from the input.")
    fact_preserved: bool = Field(
        description="False if the reworded text changes scope, seniority, "
        "numbers, or any underlying fact versus the original — not just "
        "different wording of the same fact."
    )
    reason: str = Field(
        default="", description="Brief reason, required when fact_preserved is False."
    )


class SemanticVerification(BaseModel):
    bullet_verdicts: list[BulletVerdict] = Field(default_factory=list)
    overall_passed: bool = Field(
        description="True only if every entry in bullet_verdicts has fact_preserved=True."
    )
