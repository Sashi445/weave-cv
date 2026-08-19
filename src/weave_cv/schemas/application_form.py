from typing import Literal

from pydantic import BaseModel, Field


class ExtractedField(BaseModel):
    """One fillable form field, already stripped of anything
    services/browser.py's hard exclusion filter caught (EEO/demographic,
    CAPTCHA, hidden, signature/consent fields never reach this shape) —
    the LLM only ever sees fields that already passed that deterministic
    gate, so `index` here is an index into the post-filter list, not the
    raw page.
    """

    index: int
    label: str
    field_type: Literal["text", "email", "tel", "textarea", "select"]
    options: list[str] = Field(default_factory=list, description="Choices, for select fields only.")


class FieldDecision(BaseModel):
    index: int = Field(description="Matches an ExtractedField.index from the request.")
    action: Literal["fill", "skip"]
    value: str | None = Field(
        default=None, description="Required when action is 'fill', omitted when 'skip'."
    )
    skip_reason: str | None = Field(
        default=None, description="Required when action is 'skip', omitted when 'fill'."
    )


class FormFillPlan(BaseModel):
    decisions: list[FieldDecision]
