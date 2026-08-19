"""Standalone apply agent — fills what it confidently can on a job's
real application form, using a real (headful) browser, and then STOPS:
it never clicks Submit/Apply, never checks a consent/EEO/demographic
box, never answers a work-authorization/visa/citizenship/salary
question, and never solves a CAPTCHA. Those are all either legally
significant (a false statement on a real application, submitted under
the candidate's name) or need the candidate's own judgment — deliberately
left for a human to review and finish by hand. See
services/browser.is_sensitive_field for the deterministic (not
LLM-judged) list of what never gets touched.

Deliberately has nothing to do with orchestrator_agent.py's tailor
pipeline or job_discovery_agent.py's search pipeline — this only ever
consumes what they already produced (a job_url with a tailored
resume/cover letter already generated for it, from applied_jobs).
"""

import asyncio
from dataclasses import dataclass, field

from playwright.async_api import async_playwright

from weave_cv.agents.apply_form_fill_agent import plan_form_fill
from weave_cv.schemas.application_form import ExtractedField
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.services.browser import (
    PageField,
    extract_page_fields,
    fill_text_field,
    is_sensitive_field,
    navigate_to_application_form,
    upload_file,
)


@dataclass
class ApplyResult:
    job_url: str
    form_found: bool
    filled: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _match_file_field(pf: PageField) -> str | None:
    haystack = f"{pf.name} {pf.id} {pf.label}".lower()
    if "cover" in haystack:
        return "cover_letter"
    if "resume" in haystack or "cv" in haystack:
        return "resume"
    return None


async def apply_to_job(
    job_url: str,
    resume_path: str,
    cover_letter_path: str | None,
    cv_profile: CVProfile,
    headless: bool = False,
    wait_for_review: bool = True,
) -> ApplyResult:
    """Opens a browser window (visible by default — headless=False is
    the real, intended usage; headless=True exists for tests/CI, so they
    don't pop an actual window), fills what it can, then blocks (on this
    process's stdin) until the user confirms they're done reviewing/
    submitting before closing it — the browser and the Playwright driver
    both live for exactly the duration of this call, on purpose: there
    is no "leave it running and hand it off" mode, so there's no way for
    a filled-but-unreviewed form to end up submitted by anything other
    than the user's own click. wait_for_review=False skips that block
    (only ever for tests — real callers always want the review pause).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        found = await navigate_to_application_form(page, job_url)
        if not found:
            await browser.close()
            return ApplyResult(job_url=job_url, form_found=False)

        result = ApplyResult(job_url=job_url, form_found=True)
        page_fields = await extract_page_fields(page)

        fillable: list[PageField] = []
        for pf in page_fields:
            if not pf.is_locatable:
                # No id or name — no reliable way to re-find this exact
                # element if the DOM shifts after this point (confirmed
                # live: uploading a resume can trigger an ATS's own
                # "autofill from resume" JS that does exactly that).
                # Never guess by position — skip outright.
                result.skipped.append((pf.label, "no stable id/name to safely target — left for manual entry"))
                continue
            if pf.field_type == "file":
                kind = _match_file_field(pf)
                if kind is None:
                    result.skipped.append((pf.label, "unrecognized file field — left for manual upload"))
                    continue
                path = {"resume": resume_path, "cover_letter": cover_letter_path}.get(kind)
                if path:
                    await upload_file(page, pf, path)
                    result.filled.append(pf.label)
                else:
                    result.skipped.append((
                        pf.label,
                        f"recognized as a {kind.replace('_', ' ')} upload, but none was generated for this job",
                    ))
                continue
            if is_sensitive_field(pf):
                result.skipped.append((pf.label, "excluded — sensitive/legal/compliance field, never auto-filled"))
                continue
            fillable.append(pf)

        extracted = [
            ExtractedField(index=i, label=pf.label, field_type=pf.field_type, options=pf.options)
            for i, pf in enumerate(fillable)
        ]
        plan = await plan_form_fill(cv_profile.contact, extracted)
        decisions_by_index = {d.index: d for d in plan.decisions}

        for i, pf in enumerate(fillable):
            decision = decisions_by_index.get(i)
            if decision and decision.action == "fill" and decision.value:
                await fill_text_field(page, pf, decision.value)
                result.filled.append(pf.label)
            else:
                reason = decision.skip_reason if decision and decision.skip_reason else "not confidently mappable"
                result.skipped.append((pf.label, reason))

        if wait_for_review:
            await asyncio.to_thread(
                input,
                "\nReview the filled form in the browser window — check every field, "
                "answer what was skipped, solve any CAPTCHA, and submit it yourself "
                "if it looks right. Press Enter here once you're done (submitted or "
                "not) to close the browser...",
            )
        await browser.close()
        return result
