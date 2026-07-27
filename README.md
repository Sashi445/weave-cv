# weave-cv

**weave-cv** tailors a LaTeX resume to a specific job posting using a small
pipeline of cooperating AI agents — not by writing a new resume from
scratch, but by reordering, reselecting, and carefully rewording your
*actual* master resume's content to target a role, then rendering the
result back into your own LaTeX template as a compiled PDF.

The design constraint driving everything below is simple to state and
hard to guarantee: **the output must never contain anything the input
didn't.** No invented experience, no inflated scope, no fabricated
metrics. Most of the architecture exists to make that a property the
system can check, not just a rule the prompts ask for.

## How it works

The pipeline runs in four stages:

1. **Analyze** — the job posting and the master resume are read
   concurrently by two separate agents. The job posting is scraped and
   distilled into structured requirements (required vs. preferred skills,
   qualifications, ATS keywords). The master resume's `.tex` file is
   parsed into a structured profile — every experience, project,
   bullet, and skill — with **stable IDs** assigned in document order
   (`exp1`, `exp1-b2`, `proj1`, ...).

2. **Tailor** — a third agent reorders and reselects from the structured
   resume profile to foreground what's relevant to the job, and rewords
   bullets to mirror the posting's terminology. It outputs the same
   schema back, reusing the same IDs: a kept bullet (rephrased or not)
   keeps its ID, a dropped one is simply absent, and nothing gets a new
   ID that wasn't already there.

3. **Verify** — the tailored profile is checked against the original in
   two passes. First, a deterministic structural diff (no model
   involved) walks both profiles by ID and flags anything that
   shouldn't be possible under the tailoring rules: a new ID that wasn't
   in the original, a changed factual field, a skill or credential that
   appeared from nowhere. Only if that passes does a second, narrow
   model call run — and only over the specific bullets whose *wording*
   changed — to judge whether the rewording preserved the underlying
   fact or quietly inflated it. A failure here feeds back into another
   tailoring attempt, up to a bounded number of retries.

4. **Generate** — the verified profile is rendered back into a real
   document. The master template's preamble (packages, custom macro
   definitions, margins) is reused byte-for-byte, untouched. Only the
   content between `\begin{document}` and `\end{document}` is
   regenerated, using the same macros as the original, filled with the
   tailored content. The result is compiled straight to PDF.

## Technical architecture

**Orchestration.** The four stages are wired together as a
[LangGraph](https://github.com/langchain-ai/langgraph) state graph, not
an agent that decides what to do next. Every routing decision in the
pipeline — what runs next, whether to retry — is fixed control flow
driven by plain state, because none of that is actually a judgment
call; the only real decisions (how to tailor, whether a rewording is
faithful) already belong to the sub-agents that make them. The two
independent analysis agents in stage one run concurrently via
`asyncio.gather`, for the same reason: batching them isn't a decision
worth spending a model call on.

**Model tiering.** Each agent runs on a model sized to what it's
actually being asked to do. Extracting a flat, mostly-list-of-strings
job description doesn't need the same model as reconstructing a deeply
nested resume schema or judging semantic drift in a rewritten bullet —
so cheaper and pricier tiers are assigned per agent rather than
uniformly.

**Structured I/O everywhere.** Every agent boundary is a Pydantic
schema, not free text — the job analysis, the resume profile, the
verification verdict, the generated document body. This is what makes
the stable-ID system possible in the first place: a diff between two
JSON objects is exact, a diff between two paragraphs of prose isn't.

**Deterministic where possible, agentic only where necessary.** A
recurring principle throughout: anything that can be decided in code —
concurrent fetching, structural diffing, output-folder handling,
LaTeX-escaping the model's own generated text — is done in code, not
delegated to an LLM call. Models are reserved for the things that
actually require judgment: tailoring quality, semantic fact-preservation,
and regenerating LaTeX content in an existing macro style.

**Agent/tool boundary via MCP.** Each agent's prompt and tools are
served over the [Model Context
Protocol](https://modelcontextprotocol.io/), keeping prompts,
tool definitions, and agent logic in separate, independently
addressable processes rather than hardcoded inline strings.

**Observability.** Every agent and the orchestrating graph are named
explicitly, so a LangSmith trace of a full run reads as a labeled
pipeline — job analysis, resume analysis, tailoring, verification,
generation — rather than an undifferentiated stack of identical LLM
calls.

**Rendering.** LaTeX-to-PDF compilation runs through
[Tectonic](https://tectonic-typesetting.github.io/), a self-contained
engine with no dependency on a system TeX install.
