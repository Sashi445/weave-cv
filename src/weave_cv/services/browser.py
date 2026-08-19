"""Playwright mechanics for the apply agent: locating an application
form from a job posting URL, extracting its fillable fields, and a
deterministic (not LLM-judged) filter for fields that must never be
auto-filled.

Verified live against real postings on all three platforms
weave-cv discovers from that have a public application form (Ashby,
Greenhouse, Lever — Workday's flow typically requires account creation
and isn't attempted by this module):
- Greenhouse embeds the form directly on the job posting page.
- Lever and Ashby serve it at a separate URL ("<job_url>/apply" and
  "<job_url>/application" respectively, reached via an "Apply" link on
  the posting page) — hence navigate_to_application_form's multi-step
  fallback below, rather than assuming one fixed shape.
- All three include real EEO/demographic fields (Ashby:
  "..._systemfield_eeoc_gender/race/veteran_status"; Lever:
  "eeo[gender]", "eeo[race]", plus a disability self-identification
  signature field), a reCAPTCHA/hCAPTCHA, and Ashby additionally has a
  pronoun-selection field — is_sensitive_field's pattern list is built
  directly from these, not guessed.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from playwright.async_api import Locator, Page

_HTTP_NAV_TIMEOUT_MS = 25_000
_POST_NAV_SETTLE_MS = 1_500


def _attr_selector(attr: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}="{escaped}"]'


@dataclass
class PageField:
    """Deliberately does NOT store the Locator captured at extraction
    time — confirmed live that filling the resume upload can trigger an
    ATS's own "autofill from resume" JS, which mutates the DOM (adds/
    reorders fields) between extraction and fill time. A Locator from
    `.all()` is position-based under the hood, so a stored one can end
    up silently pointing at the wrong element after such a mutation
    (caught this via a real misfire: a text value landing on a file
    input several positions away). `locate(page)` re-resolves by the
    field's own id/name at the moment it's actually used instead, which
    survives DOM reordering.

    is_locatable is False when a field has neither id nor name — no
    stable way exists to re-find it if the DOM has shifted since
    extraction, and it demonstrably does shift (the same resume-upload
    trigger above). Filling by raw position anyway was tried and it
    silently targeted the wrong element in testing, so callers must
    treat is_locatable=False as "cannot be safely filled, skip it" —
    never call locate() when it's False.
    """

    tag: str
    field_type: str  # "text" | "email" | "tel" | "textarea" | "select" | "file"
    name: str
    id: str
    label: str
    options: list[str] = field(default_factory=list)

    @property
    def is_locatable(self) -> bool:
        return bool(self.id or self.name)

    def locate(self, page: Page) -> Locator:
        if self.id:
            return page.locator(_attr_selector("id", self.id)).first
        if self.name:
            return page.locator(_attr_selector("name", self.name)).first
        raise ValueError(f"Field {self.label!r} has no id or name — check is_locatable before calling locate().")


# Deliberately deterministic, not left to the LLM's judgment — a false
# "yes" on work authorization, or a guessed EEO/demographic response,
# submitted under the candidate's name is a real problem an LLM
# "probably wouldn't do that" isn't an acceptable guard against. Built
# directly from real field names/labels found on Ashby, Greenhouse, and
# Lever's actual forms (see module docstring) — including two real
# misses caught only by testing live against those forms, not by
# reasoning about what patterns "should" cover: Greenhouse's "Are you
# legally authorized to work in the US?" (the word order defeated an
# earlier "work\s*authoriz" pattern — "authoriz" alone is what actually
# matters here) and Lever's "Are you a U.S. Citizen or lawful permanent
# resident?" and background-check consent question (neither mentions
# "visa," "legal status," or "consent" at all).
_SENSITIVE_RE = re.compile(
    r"eeo|equal\s*employment|gender|\bsex\b|\brace\b|ethnicit|veteran|disab|"
    r"pronoun|sexual\s*orientation|signature|captcha|consent|certify|"
    r"acknowledge|attest|visa|sponsor|authoriz|legal\s*status|"
    r"citizen|permanent\s*resident|green\s*card|background\s*check|"
    r"salary|compensation|expected\s*pay",
    re.IGNORECASE,
)


def is_sensitive_field(pf: PageField) -> bool:
    haystack = f"{pf.name} {pf.id} {pf.label}"
    return bool(_SENSITIVE_RE.search(haystack))


_LABEL_JS = """
(el) => {
    let node = el;
    for (let hops = 0; hops < 5 && node; hops++) {
        node = node.parentElement;
        if (!node) break;
        const clone = node.cloneNode(true);
        clone.querySelectorAll("input, select, textarea, script, style").forEach(n => n.remove());
        const text = clone.textContent.replace(/\\s+/g, " ").trim();
        if (text && text.length > 0 && text.length < 200) return text;
    }
    return null;
}
"""


async def _extract_label(page: Page, el: Locator, eid: str, name: str) -> str:
    """Tries, in order: <label for=id> (Greenhouse's convention) ->
    aria-label -> placeholder -> nearest ancestor's visible text with
    all nested form controls stripped out (Lever/Ashby's convention,
    neither of which use <label for> at all — confirmed live, not
    assumed) -> humanized name/id as an absolute last resort."""
    if eid:
        label_el = page.locator(f'label[for="{eid}"]')
        if await label_el.count() > 0:
            text = (await label_el.first.text_content() or "").strip()
            if text:
                return text
    aria = await el.get_attribute("aria-label")
    if aria and aria.strip():
        return aria.strip()
    placeholder = await el.get_attribute("placeholder")
    if placeholder and placeholder.strip():
        return placeholder.strip()
    dom_text = await el.evaluate(_LABEL_JS)
    if dom_text:
        return dom_text
    raw = name or eid or ""
    return re.sub(r"[_\-\[\]]+", " ", raw).strip() or "Unlabeled field"


async def extract_page_fields(page: Page) -> list[PageField]:
    """Every input/textarea/select on the current page, classified and
    labeled. Deliberately excludes, at this stage already (before
    is_sensitive_field even runs):
    - type=hidden (session/tracking plumbing, never user-facing)
    - radio/checkbox (in v1, always left for the user regardless of
      what they're for — reliably filling a multi-choice group correctly
      needs more care than a text/select field does, and in practice
      these are disproportionately EEO/consent fields anyway)
    - any input type this doesn't recognize (e.g. a search box that's
      part of a phone country-code picker widget, not a real field)
    """
    fields: list[PageField] = []
    elements = await page.locator("input, textarea, select").all()
    for el in elements:
        tag = (await el.evaluate("e => e.tagName")).lower()
        raw_type = (await el.get_attribute("type")) or ("text" if tag == "input" else tag)
        raw_type = raw_type.lower()

        if raw_type in ("hidden", "radio", "checkbox", "submit", "button"):
            continue

        name = (await el.get_attribute("name")) or ""
        eid = (await el.get_attribute("id")) or ""

        if raw_type == "file":
            field_type = "file"
        elif tag == "textarea":
            field_type = "textarea"
        elif tag == "select":
            field_type = "select"
        elif raw_type in ("email", "tel"):
            field_type = raw_type
        elif raw_type in ("text", "url", "number"):
            field_type = "text"
        else:
            continue

        label = await _extract_label(page, el, eid, name)

        options: list[str] = []
        if field_type == "select":
            for opt in await el.locator("option").all():
                text = (await opt.text_content() or "").strip()
                if text:
                    options.append(text)

        fields.append(PageField(tag=tag, field_type=field_type, name=name, id=eid, label=label, options=options))
    return fields


async def _has_fillable_fields(page: Page) -> bool:
    return await page.locator('input[type="text"], input[type="email"], input[type="file"]').count() > 0


async def navigate_to_application_form(page: Page, job_url: str) -> bool:
    """True once page is sitting on a page with fillable fields, False
    if none could be located — the caller's job to treat as "unsupported
    page, nothing to fill" rather than a crash. Handles all 3 shapes
    confirmed live: form embedded directly on the posting (Greenhouse),
    reached via an explicit "Apply" link's href (Lever, Ashby), or
    revealed by clicking a JS-driven "Apply" button with no href."""
    await page.goto(job_url, wait_until="domcontentloaded", timeout=_HTTP_NAV_TIMEOUT_MS)
    await page.wait_for_timeout(_POST_NAV_SETTLE_MS)

    if await _has_fillable_fields(page):
        return True

    apply_link = page.locator('a:has-text("Apply")').first
    if await apply_link.count() > 0:
        href = await apply_link.get_attribute("href")
        if href:
            # Ashby's "Apply" link href is relative ("/notion/.../application")
            # — confirmed live it crashes page.goto() with "invalid URL"
            # unless resolved against the current page's origin first.
            await page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=_HTTP_NAV_TIMEOUT_MS)
            await page.wait_for_timeout(_POST_NAV_SETTLE_MS)
            if await _has_fillable_fields(page):
                return True

    apply_button = page.locator('button:has-text("Apply")').first
    if await apply_button.count() > 0:
        await apply_button.click()
        await page.wait_for_timeout(_POST_NAV_SETTLE_MS)
        if await _has_fillable_fields(page):
            return True

    return False


async def fill_text_field(page: Page, pf: PageField, value: str) -> None:
    locator = pf.locate(page)
    if pf.field_type == "select":
        try:
            await locator.select_option(label=value)
            return
        except Exception:
            for opt in pf.options:
                if value.lower() in opt.lower() or opt.lower() in value.lower():
                    await locator.select_option(label=opt)
                    return
            return  # no reasonable option match — leave it unfilled rather than pick arbitrarily
    await locator.fill(value)


async def upload_file(page: Page, pf: PageField, file_path: str) -> None:
    await pf.locate(page).set_input_files(file_path)
