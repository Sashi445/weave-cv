from pydantic import BaseModel, Field


class Link(BaseModel):
    label: str = Field(description="e.g. 'GitHub', 'LinkedIn', 'Portfolio'.")
    url: str


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[Link] = Field(default_factory=list)


class SkillGroup(BaseModel):
    category: str | None = Field(
        default=None,
        description="Skill category if the CV groups them (e.g. 'Languages'), "
        "else null.",
    )
    items: list[str] = Field(
        default_factory=list, description="Skills verbatim, not normalized."
    )


class Bullet(BaseModel):
    id: str = Field(
        description="Stable ID in the form <parent_id>-b<N>, assigned in "
        "document order (e.g. 'exp1-b2'). Must be deterministic across re-runs."
    )
    text: str = Field(description="Bullet text exactly as written.")


class Experience(BaseModel):
    id: str = Field(
        description="Stable ID 'exp<N>' in document order (exp1, exp2, ...)."
    )
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start_date: str | None = Field(
        default=None,
        description="Raw string as written ('Jun 2023', 'Present'). Do not "
        "normalize or reformat.",
    )
    end_date: str | None = Field(
        default=None, description="Raw string as written. Do not normalize."
    )
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    id: str = Field(description="Stable ID 'proj<N>' in document order.")
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(
        default_factory=list, description="Verbatim, not expanded."
    )
    links: list[Link] = Field(
        default_factory=list,
        description="URLs associated with this project (e.g. a GitHub repo "
        "or live demo), each with a display label — same shape as "
        "Contact.links. Extracted from any \\href{url}{label} (or bare "
        "URL) tied to this project in the source resume. Never invent one; "
        "never drop one that exists.",
    )
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    location: str | None = None
    start_date: str | None = Field(default=None, description="Raw string.")
    end_date: str | None = Field(default=None, description="Raw string.")
    details: list[str] = Field(
        default_factory=list,
        description="GPA, honors, relevant coursework, etc. — only if stated.",
    )


class AdditionalSection(BaseModel):
    section_title: str = Field(
        description="The CV's own heading for a section that doesn't map to the "
        "standard fields (e.g. 'Awards', 'Leadership', 'Languages')."
    )
    content: list[str] = Field(
        default_factory=list, description="Items under that section, verbatim."
    )


class CVProfile(BaseModel):
    contact: Contact
    summary: str | None = Field(
        default=None, description="Professional summary/objective if present."
    )
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    additional: list[AdditionalSection] = Field(
        default_factory=list,
        description="Any section that doesn't fit the fields above. Never drop "
        "a section — capture it here to preserve completeness.",
    )