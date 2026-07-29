from pydantic import BaseModel, Field

class JobDescriptionAnalysis(BaseModel):
    # --- Validity / failure signal ---
    is_job_posting: bool = Field(
        description="False if the scraped page is not a usable job posting "
        "(expired, login wall, search page, error). When False, leave all "
        "other fields empty and do not fabricate content."
    )

    company_name: str | None = Field(
        default=None, description="Exact name of the firm or company"
    )

    # --- Role metadata (only if explicitly stated) ---
    title: str | None = Field(
        default=None, description="Exact job title as written, or null."
    )
    seniority: str | None = Field(
        default=None,
        description="Seniority only if the posting states it (e.g. 'Senior', "
        "'Entry-level'). Do not infer from other cues.",
    )
    location: str | None = Field(default=None, description="Location if stated.")
    work_model: str | None = Field(
        default=None, description="Remote / hybrid / onsite, only if stated."
    )

    # --- Experience (only if the posting gives a number) ---
    min_years_experience: float | None = Field(
        default=None,
        description="Minimum years of experience ONLY if explicitly stated. "
        "Never infer from seniority or role. Null if unstated.",
    )
    max_years_experience: float | None = Field(
        default=None,
        description="Upper bound only if a range is stated. Usually null.",
    )

    # --- Requirements, split by the posting's own labels ---
    required_skills: list[str] = Field(
        default_factory=list,
        description="Skills marked required/must-have, verbatim. If the posting "
        "doesn't label them, place hard requirements here (lower confidence).",
    )
    preferred_skills: list[str] = Field(
        default_factory=list,
        description="Skills marked preferred/nice-to-have/bonus, verbatim.",
    )
    qualifications: list[str] = Field(
        default_factory=list,
        description="Education, certifications, and experience-type "
        "requirements as stated.",
    )
    responsibilities: list[str] = Field(
        default_factory=list, description="Key responsibilities as stated."
    )

    # --- Verbatim ATS ammunition (distinct consumer) ---
    ats_keywords: list[str] = Field(
        default_factory=list,
        description="Exact skill/tool/technology strings to mirror for ATS "
        "matching, verbatim from the posting ('Kubernetes', 'CI/CD', "
        "'React.js'). Not normalized or expanded.",
    )
