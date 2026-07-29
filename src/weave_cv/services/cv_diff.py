"""Structural diffing between an original and tailored CVProfile, keyed on
the stable IDs both share.

This is the deterministic half of verification: everything computed here
is a plain set/field comparison, no LLM involved, and it's 100% reliable
for what it checks — unlike an LLM judgment call. It can fully answer "did
tailoring introduce anything not traceable to the original" (new IDs, new
skill/cert/publication strings, changed factual fields). It deliberately
can't answer "did rephrasing a bullet change its underlying meaning" —
that's a semantic judgment left to agents/resume_verifier_agent.py, which
consumes `CVProfileDiff.reworded_bullets` as its only input.
"""

from dataclasses import dataclass, field

from weave_cv.schemas.cv_analysis import Contact, CVProfile


@dataclass
class BulletChange:
    id: str
    original_text: str
    tailored_text: str


@dataclass
class SectionDiff:
    label: str
    kept_ids: list[str] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)
    added_ids: list[str] = field(default_factory=list)  # hallucination signal
    changed_facts: dict[str, list[str]] = field(default_factory=dict)  # id -> field names, hallucination signal
    reworded_bullets: list[BulletChange] = field(default_factory=list)  # needs LLM judgment
    dropped_bullets: dict[str, str] = field(default_factory=dict)  # id -> text
    new_bullets: dict[str, str] = field(default_factory=dict)  # id -> text, hallucination signal

    def render(self) -> list[str]:
        lines = [
            f"\n{self.label}: {len(self.kept_ids)} kept, "
            f"{len(self.dropped_ids)} dropped, {len(self.added_ids)} added"
        ]
        for eid in sorted(self.dropped_ids):
            lines.append(f"  - dropped {eid}")
        for eid in sorted(self.added_ids):
            lines.append(f"  ! NEW {eid} not in original (possible hallucination)")
        for eid in sorted(self.kept_ids):
            if eid in self.changed_facts:
                lines.append(f"  ! {eid}: factual field(s) changed (should never happen): {self.changed_facts[eid]}")
            else:
                lines.append(f"  {eid}: kept")
        for bid, text in sorted(self.dropped_bullets.items()):
            lines.append(f"    - dropped bullet {bid}: {text[:90]}")
        for bid, text in sorted(self.new_bullets.items()):
            lines.append(f"    ! NEW bullet {bid} not in original (possible hallucination): {text[:90]}")
        for bc in sorted(self.reworded_bullets, key=lambda b: b.id):
            lines.append(f"    ~ reworded {bc.id}")
            lines.append(f"        before: {bc.original_text[:100]}")
            lines.append(f"        after:  {bc.tailored_text[:100]}")
        return lines


@dataclass
class FlatListDiff:
    label: str
    kept: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)  # hallucination signal

    def render(self) -> list[str]:
        lines = [f"\n{self.label}: {len(self.kept)} kept, {len(self.dropped)} dropped, {len(self.added)} added"]
        for item in sorted(self.dropped):
            lines.append(f"  - dropped: {item[:90]}")
        for item in sorted(self.added):
            lines.append(f"  ! NEW not in original (possible hallucination): {item[:90]}")
        return lines


@dataclass
class CVProfileDiff:
    contact_changed: bool
    contact_before: Contact
    contact_after: Contact
    experience: SectionDiff
    projects: SectionDiff
    skills: FlatListDiff
    certifications: FlatListDiff
    publications: FlatListDiff
    education_before_count: int
    education_after_count: int

    @property
    def hallucination_signals(self) -> list[str]:
        """Anything in `tailored` that isn't traceable to `original`. If
        this is non-empty, verification should fail without needing an
        LLM call at all — this check is deterministic and exhaustive for
        what it covers."""
        signals = []
        if self.contact_changed:
            signals.append("contact changed (should never happen)")
        for section in (self.experience, self.projects):
            for eid in section.added_ids:
                signals.append(f"{section.label}: new entry {eid} not in original")
            for eid, facts in section.changed_facts.items():
                signals.append(f"{section.label}: {eid} factual field(s) changed: {facts}")
            for bid in section.new_bullets:
                signals.append(f"{section.label}: new bullet {bid} not in original")
        for flat in (self.skills, self.certifications, self.publications):
            for item in flat.added:
                signals.append(f"{flat.label}: new item not in original: {item}")
        return signals

    @property
    def reworded_bullets(self) -> list[BulletChange]:
        """Bullets whose text changed but whose ID is preserved — the part
        that needs an LLM's judgment (did rephrasing preserve the fact?),
        not a deterministic check."""
        return self.experience.reworded_bullets + self.projects.reworded_bullets

    def render(self) -> str:
        lines = ["=" * 60, "CVProfile DELTA (original -> tailored)", "=" * 60]

        if self.contact_changed:
            lines.append("! contact changed (should never happen):")
            lines.append(f"    before: {self.contact_before}")
            lines.append(f"    after:  {self.contact_after}")
        else:
            lines.append("contact: unchanged")

        lines += self.experience.render()
        lines += self.projects.render()
        lines += self.skills.render()
        lines += self.certifications.render()
        lines += self.publications.render()

        if self.education_before_count != self.education_after_count:
            lines.append(
                f"\nEducation: entry count changed "
                f"({self.education_before_count} -> {self.education_after_count})"
            )
        else:
            lines.append("\nEducation: entry count unchanged")

        lines.append("=" * 60)
        return "\n".join(lines)


def _diff_bullets(orig_bullets, tail_bullets) -> tuple[dict[str, str], dict[str, str], list[BulletChange]]:
    orig_by_id = {b.id: b for b in orig_bullets}
    tail_by_id = {b.id: b for b in tail_bullets}

    dropped = {bid: orig_by_id[bid].text for bid in orig_by_id.keys() - tail_by_id.keys()}
    new = {bid: tail_by_id[bid].text for bid in tail_by_id.keys() - orig_by_id.keys()}
    reworded = [
        BulletChange(id=bid, original_text=orig_by_id[bid].text, tailored_text=tail_by_id[bid].text)
        for bid in orig_by_id.keys() & tail_by_id.keys()
        if orig_by_id[bid].text != tail_by_id[bid].text
    ]
    return dropped, new, reworded


def _diff_entries(original_list, tailored_list, label: str, fact_fields: list[str]) -> SectionDiff:
    orig_by_id = {e.id: e for e in original_list}
    tail_by_id = {e.id: e for e in tailored_list}

    dropped_ids = sorted(orig_by_id.keys() - tail_by_id.keys())
    added_ids = sorted(tail_by_id.keys() - orig_by_id.keys())
    kept_ids = sorted(orig_by_id.keys() & tail_by_id.keys())

    changed_facts: dict[str, list[str]] = {}
    dropped_bullets: dict[str, str] = {}
    new_bullets: dict[str, str] = {}
    reworded_bullets: list[BulletChange] = []

    for eid in kept_ids:
        o, t = orig_by_id[eid], tail_by_id[eid]
        changed = [f for f in fact_fields if getattr(o, f, None) != getattr(t, f, None)]
        if changed:
            changed_facts[eid] = changed
        d, n, r = _diff_bullets(o.bullets, t.bullets)
        dropped_bullets.update(d)
        new_bullets.update(n)
        reworded_bullets.extend(r)

    return SectionDiff(
        label=label,
        kept_ids=kept_ids,
        dropped_ids=dropped_ids,
        added_ids=added_ids,
        changed_facts=changed_facts,
        reworded_bullets=reworded_bullets,
        dropped_bullets=dropped_bullets,
        new_bullets=new_bullets,
    )


def _diff_flat_list(original_items, tailored_items, label: str) -> FlatListDiff:
    orig_set = set(original_items)
    tail_set = set(tailored_items)
    return FlatListDiff(
        label=label,
        kept=sorted(orig_set & tail_set),
        dropped=sorted(orig_set - tail_set),
        added=sorted(tail_set - orig_set),
    )


def diff_cv_profiles(original: CVProfile, tailored: CVProfile) -> CVProfileDiff:
    orig_skills = [item for group in original.skills for item in group.items]
    tail_skills = [item for group in tailored.skills for item in group.items]

    return CVProfileDiff(
        contact_changed=original.contact != tailored.contact,
        contact_before=original.contact,
        contact_after=tailored.contact,
        experience=_diff_entries(
            original.experience, tailored.experience, "Experience",
            fact_fields=["company", "title", "location", "start_date", "end_date"],
        ),
        projects=_diff_entries(
            original.projects, tailored.projects, "Projects",
            fact_fields=["name", "description", "technologies"],
        ),
        skills=_diff_flat_list(orig_skills, tail_skills, "Skills"),
        certifications=_diff_flat_list(original.certifications, tailored.certifications, "Certifications"),
        publications=_diff_flat_list(original.publications, tailored.publications, "Publications"),
        education_before_count=len(original.education),
        education_after_count=len(tailored.education),
    )
