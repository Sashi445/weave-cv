from datetime import datetime

from pydantic import BaseModel, Field


class DiscoveredJob(BaseModel):
    platform: str = Field(description="'ashby', 'greenhouse', or 'lever'.")
    company: str = Field(description="The company's own board/API slug on this platform.")
    company_name: str | None = None
    job_id: str = Field(description="The platform's own job ID — stable, used as the seen-cache key.")
    title: str
    url: str
    location: str | None = None
    posted_at: datetime
    description: str = Field(description="Plain-text job description, for relevance scoring.")


class RelevanceVerdict(BaseModel):
    relevant: bool
    reason: str = Field(
        description="One line: the specific, concrete reason this posting is (or "
        "isn't) a good match for the candidate."
    )
