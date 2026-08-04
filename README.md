<div align="center"><pre>
  ██╗    ██╗███████╗ █████╗ ██╗   ██╗███████╗     ██████╗██╗   ██╗
  ██║    ██║██╔════╝██╔══██╗██║   ██║██╔════╝    ██╔════╝██║   ██║
  ██║ █╗ ██║█████╗  ███████║██║   ██║█████╗      ██║     ██║   ██║
  ██║███╗██║██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝      ██║     ╚██╗ ██╔╝
  ╚███╔███╔╝███████╗██║  ██║ ╚████╔╝ ███████╗    ╚██████╗ ╚████╔╝ 
   ╚══╝╚══╝ ╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝     ╚═════╝  ╚═══╝  
  Tailor a resume to a job posting — verified, not just generated
</pre></div>

Tailors a LaTeX resume to a job posting using a small pipeline of
cooperating AI agents — not by writing a new resume, but by reordering,
reselecting, and rewording your *actual* master resume to target a role,
then rendering it back into your own LaTeX template as a compiled PDF.

The rule everything else is built around: **the output must never
contain anything the input didn't.** No invented experience, no
inflated scope, no fabricated metrics. Most of the design exists to
make that a property the system checks, not just a rule the prompt asks for.

<p align="center">
  <a href="docs/DOCS.md">Docs / CLI reference</a>
</p>

## How it works

```
 You
   job posting URL  +  master resume .tex
        │
        ▼
    ┌─────────────────────────────────────────────────────────┐
    │ weave-cv                                                │
    │ ─────────────────────────────────────────────────────── │
    │ gather_inputs                                           │
    │   ├─ JD-Analyzer   scrape + extract job requirements    │
    │   └─ CV-Analyzer   parse .tex into a structured profile │
    │        (concurrent, both keyed to the same stable IDs)  │
    │                                                         │
    │ tailor     reorder / reselect / reword, same IDs kept   │
    │ verify     structural diff (no LLM) + narrow LLM check  │
    │            on just the bullets that got reworded        │
    │            fails -> back to tailor (bounded retries)    │
    │ generate   same LaTeX macros as your template -> PDF    │
    └─────────────────────────────────────────────────────────┘
        │
        ▼
 tailored .tex + .pdf, verified against the original
```

- **gather_inputs** — the job posting and your resume are read
  concurrently by two separate agents. The posting is scraped and
  distilled into structured requirements (required vs. preferred
  skills, qualifications, ATS keywords). The resume's `.tex` is parsed
  into a structured profile — every experience, project, bullet, and
  skill — with stable IDs assigned in document order (`exp1`,
  `exp1-b2`, `proj1`, ...).
- **tailor** — reorders and reselects from the structured profile to
  foreground what's relevant to the job, and rewords bullets to mirror
  the posting's terminology. Outputs the same schema, reusing the same
  IDs: a kept bullet keeps its ID, a dropped one is simply absent,
  nothing gets an ID that wasn't already there.
- **verify** — checked in two passes. First a deterministic structural
  diff (no model) walks both profiles by ID and flags anything that
  shouldn't be possible: a new ID, a changed factual field, a skill
  that appeared from nowhere. Only if that passes does a narrow model
  call run — over just the bullets whose *wording* changed — to judge
  whether the reword preserved the fact or quietly inflated it. A
  failure feeds back into another tailoring attempt, up to a bounded
  number of retries.
- **generate** — the master template's preamble (packages, macros,
  margins) is reused byte-for-byte, untouched. Only the content between
  `\begin{document}` and `\end{document}` is regenerated, using the
  same macros as the original, then compiled straight to PDF.

## Technical notes

- **Orchestration** is a [LangGraph](https://github.com/langchain-ai/langgraph)
  state graph, not an agent that decides what to run next — every
  routing decision (what's next, whether to retry) is fixed control
  flow over plain state, because none of it is actually a judgment
  call. The real decisions (how to tailor, whether a reword is
  faithful) belong to the sub-agents that make them.
- **Every agent boundary is a Pydantic schema**, not free text — job
  analysis, resume profile, verification verdict, generated document
  body. This is what makes the stable-ID diff possible: two JSON
  objects diff exactly, two paragraphs of prose don't.
- **Deterministic where possible, agentic only where necessary.**
  Concurrent fetching, structural diffing, output-folder handling,
  LaTeX-escaping the model's own output — all done in code, not
  delegated to an LLM call. Models are reserved for tailoring quality,
  fact-preservation judgment, and regenerating LaTeX in an existing
  macro style.
- **Provider-agnostic.** Runs on OpenAI, Anthropic, Google Gemini,
  Groq, xAI, or DeepSeek — one model for every agent, set via
  `weave-cv config set --provider ... --model ...`.
- **Agent/tool boundary via [MCP](https://modelcontextprotocol.io/).**
  Each agent's prompt and tools are served over their own MCP process
  rather than hardcoded inline strings.
- **Rendering** runs through [Tectonic](https://tectonic-typesetting.github.io/),
  a self-contained LaTeX engine with no dependency on a system TeX install.
