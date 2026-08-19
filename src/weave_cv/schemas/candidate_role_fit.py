from pydantic import BaseModel, Field


class CandidateRoleFit(BaseModel):
    """A condensed, purpose-built summary of a CVProfile for judging job
    relevance — not a résumé rewrite, and not used anywhere content
    fidelity matters (tailoring/generation still use the real, full
    CVProfile). Computed once per resume, cached, and reused across
    every posting a `discover` run checks, instead of re-sending the
    entire CVProfile (every bullet, every project, every education
    entry) on every single relevance call.
    """

    target_roles: list[str] = Field(
        description="Job titles/role categories this candidate could "
        "reasonably target, based on their real experience. Cast a wide "
        "net — include adjacent/related titles their experience "
        "supports, not just their literal most recent title. The goal "
        "is maximizing the odds of surfacing real opportunities, not "
        "guaranteeing a single 'correct' role."
    )
    min_years_experience: float = Field(
        description="Estimated total years of relevant professional "
        "experience, computed from the CVProfile's actual employment "
        "dates — low end of a reasonable range."
    )
    max_years_experience: float = Field(
        description="Same, high end of a reasonable range."
    )
    core_skills: list[str] = Field(
        description="The candidate's strongest, most defining skills/"
        "technologies — enough to judge stack overlap against a "
        "posting, not an exhaustive restatement of every skill listed."
    )
    location: str | None = Field(
        default=None,
        description="The candidate's own location, copied verbatim from "
        "CVProfile.contact.location — set directly from that field after "
        "this object is built, not something the LLM should infer or "
        "guess at.",
    )
    summary: str = Field(
        description="1-2 plain sentences on their domain/focus/"
        "strengths — context a bare role list and skill list can't "
        "capture on their own."
    )
