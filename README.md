<div align="center"><pre>
  ██╗    ██╗███████╗ █████╗ ██╗   ██╗███████╗     ██████╗██╗   ██╗
  ██║    ██║██╔════╝██╔══██╗██║   ██║██╔════╝    ██╔════╝██║   ██║
  ██║ █╗ ██║█████╗  ███████║██║   ██║█████╗      ██║     ██║   ██║
  ██║███╗██║██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝      ██║     ╚██╗ ██╔╝
  ╚███╔███╔╝███████╗██║  ██║ ╚████╔╝ ███████╗    ╚██████╗ ╚████╔╝ 
   ╚══╝╚══╝ ╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝     ╚═════╝  ╚═══╝  
  An agent that tailors your resume to a job posting — without
  inventing anything new
</pre></div>

weave-cv is an agent, not a template filler. Point it at a job posting
and your actual master resume, and it works the job the way you would:
read both, figure out what to lead with, reword it to speak the role's
language, then double-check itself before handing back a resume — and
a compiled PDF — built entirely from what was already there.

Given a job posting and a master resume, the agent:

- **reads both** — scrapes and distills the posting into concrete
  requirements, and parses your resume into a structured profile of
  every experience, project, bullet, and skill
- **decides what to lead with** — reorders and reselects from your
  real experience to foreground what's relevant to this role
- **rewords to match the role** — mirrors the posting's language in
  your bullets, without adding a skill, metric, or scope you didn't
  have
- **checks its own work** — diffs its output against your original
  and re-does anything that drifted, before it ever reaches you
- **hands back a resume** — same LaTeX template, same macros, just
  retargeted, compiled straight to PDF

The rule everything else is built around: **the output must never
contain anything the input didn't.** No invented experience, no
inflated scope, no fabricated metrics. Most of the design exists to
make that a property the system checks, not just a rule the prompt asks for.

<p align="center">
  <a href="#docs--cli-reference">Docs / CLI reference</a>
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

## Docs / CLI reference

- [Installation](#installation)
- [`weave-cv config`](#weave-cv-config)
- [`weave-cv tailor`](#weave-cv-tailor)
- [`weave-cv batch`](#weave-cv-batch)

### Installation

`weave-cv` requires **Python 3.12 or newer**. Most systems still ship an
older default Python, so the recommended path is to install 3.12+ with
[pyenv](https://github.com/pyenv/pyenv) first, then create an isolated
environment for `weave-cv` on top of it.

#### 1. Install Python 3.12+ via pyenv

Already have Python 3.12+ (`python3 --version`)? Skip to step 2.

Otherwise, pick your OS for step-by-step pyenv install directions:

- [pyenv on macOS](docs/pyenv-macos.md)
- [pyenv on Linux](docs/pyenv-linux.md)
- [pyenv on Windows](docs/pyenv-windows.md)

Once pyenv is installed, grab a 3.12+ Python from your project folder
(`pyenv local` scopes it to this folder only, leaving your system
Python untouched):

```
$ pyenv install 3.12.8
$ pyenv local 3.12.8
$ python3 --version
Python 3.12.8
```

#### 2. Create an environment and install weave-cv

##### Option A — local (per-project) environment, recommended

Keeps `weave-cv` and its dependencies scoped to one project folder using
Python's built-in `venv`.

**macOS / Linux:**

```
$ python3 -m venv .venv
$ source .venv/bin/activate
(.venv) $ pip install --upgrade pip
(.venv) $ pip install weave-cv
```

**Windows (PowerShell):**

```
> python -m venv .venv
> .venv\Scripts\Activate.ps1
(.venv) > pip install --upgrade pip
(.venv) > pip install weave-cv
```

Each new terminal session needs the environment reactivated with the
`activate` command above before running `weave-cv`. Confirm it worked:

```
(.venv) $ weave-cv --help
```

##### Option B — global install

Makes the `weave-cv` command available from any terminal, in any
directory, without activating anything. Use [pipx](https://pipx.pypa.io/)
so it installs into its own isolated environment instead of polluting
your system Python:

```
$ pipx install weave-cv
```

Don't have pipx? Install it first (`python3 -m pip install --user pipx`,
then `pipx ensurepath`), or fall back to a plain user-level pip install:

```
$ pip install --user weave-cv
```

Confirm it worked:

```
$ weave-cv --help
```

### `weave-cv config`

Set this up before you start using weave-cv — it saves you from typing
the same flags on every `tailor`/`batch` run. Everything lands in
`~/.weave-cv/config.toml`, and any of it can still be overridden
per-command with flags.

#### Master resume & output folder

`--master-resume` is the `.tex` file everything gets tailored from.
`--output-dir` is where the tailored `.tex`/`.pdf` get written. Set them
one at a time:

```
$ weave-cv config set --master-resume ~/resumes/master-resume.tex
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --output-dir ~/tailored-resumes
Saved to /Users/you/.weave-cv/config.toml
```

#### Provider, model & API key

Every agent in the pipeline calls the same LLM, so you need all three:
`--provider` is the vendor (`openai`, `anthropic`, `google_genai`,
`groq`, `xai`, `deepseek`), `--model` is which model from it, `--api-key`
is the credential. Set them one at a time:

```
$ weave-cv config set --provider openai
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --model gpt-5-mini
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --api-key sk-proj-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml
```

Suggested: `openai` with `gpt-5-mini` — cheap, fast, and good enough for
this pipeline. Skip `--api-key` and weave-cv just asks for one the first
time it actually needs it.

#### Update a value later

Only the flag you pass changes — everything else stays as-is:

```
$ weave-cv config set --output-dir ~/Desktop/resumes-2026
Saved to /Users/you/.weave-cv/config.toml
```

#### `config set` with nothing to save

```
$ weave-cv config set
No values given — nothing changed.
```

#### View what's saved

```
$ weave-cv config show
master_resume: /Users/you/resumes/master-resume.tex
output_dir: /Users/you/tailored-resumes
api_key: ****xxxx
provider: openai
model: gpt-5-mini
```

Nothing saved yet:

```
$ weave-cv config show
No config saved yet — see `weave-cv config set --help`.
```

#### Skipped config entirely?

Fine — weave-cv asks for an API key on first run and remembers it:

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567 -m ~/resumes/master-resume.tex -o ~/tailored-resumes
No API key found for provider 'openai' — enter one:
Saved API key to your weave-cv config.
```

### `weave-cv tailor`

Runs the agent on one job posting: reads it, reads your master resume,
tailors, verifies, and writes back a `.tex` and a compiled `.pdf`.

#### With config set

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567
```

#### Without config

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567 -m ~/resumes/master-resume.tex -o ~/tailored-resumes
```

Long-flag equivalents: `--job-url`, `--master-resume`, `--output-dir`.

#### What a run looks like

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567
▶ Scraping job posting & analyzing resume...
 61.4s ✓ Scraping job posting & analyzing resume
▶ Tailoring resume...
 34.2s ✓ Tailoring resume (attempt 1)
▶ Verifying tailored resume...
  2.8s ✓ Verifying tailored resume — passed
▶ Generating PDF...
 48.9s ✓ Generating PDF
Total: 147.3s

Tex saved to: /Users/you/tailored-resumes/master-resume_Acme_20260804_120145_331902.tex
PDF saved to: /Users/you/tailored-resumes/master-resume_Acme_20260804_120145_331902.pdf
```

#### When verification fails and retries

```
▶ Verifying tailored resume...
  4.1s … Verifying tailored resume — failed, retrying: exp1-b2: Reworded version adds a metric ("40% faster") not present in the original.
▶ Tailoring resume (retry)...
 31.0s ✓ Tailoring resume (attempt 2)
▶ Verifying tailored resume...
  2.2s ✓ Verifying tailored resume — passed
```

#### When a stage fails outright

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567
▶ Scraping job posting & analyzing resume...
 12.1s ✗ Scraping job posting & analyzing resume failed

Failed at stage 'gather_inputs': [gather_inputs] JD analysis failed: page returned little to no content.
```

Exits with code `1` — safe to check in scripts:

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567 || echo "tailoring failed"
```

### `weave-cv batch`

Runs the agent over every job posting in a CSV or XLSX file, several at
a time up to a concurrency cap, and prints a summary table at the end.
Same pipeline as `tailor`, just batched.

#### Input file

```
$ cat jobs.csv
job_url
https://job-boards.greenhouse.io/acme/jobs/1234567
https://job-boards.greenhouse.io/acme/jobs/7654321
https://job-boards.greenhouse.io/globex/jobs/2468101
```

Header can be `job_url`, `url`, `link`, or `job_link`
(case/spacing-insensitive). `.xlsx` works the same way.

#### With config set

```
$ weave-cv batch -f jobs.csv
Found 3 job URL(s) in jobs.csv. Processing up to 3 at a time.
```

#### Without config

```
$ weave-cv batch -f jobs.csv -m ~/resumes/master-resume.tex -o ~/tailored-resumes -c 2
```

Long-flag equivalents: `--file`, `--master-resume`, `--output-dir`,
`--concurrency`. Concurrency defaults to 3.

#### What a batch run looks like

```
$ weave-cv batch -f jobs.csv -c 2
Found 3 job URL(s) in jobs.csv. Processing up to 2 at a time.

⠋ https://job-boards.greenhouse.io/acme/jobs/1234567 — Tailoring resume        0:00:41
⠙ https://job-boards.greenhouse.io/acme/jobs/7654321 — Scraping job posting…   0:00:41
✓ Globex — done                                                                0:02:12

                       Batch tailoring summary
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job URL                 ┃ Status ┃ Output / Error                  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ .../acme/jobs/1234567   │ done   │ .../master-resume_Acme_...pdf   │
│ .../acme/jobs/7654321   │ done   │ .../master-resume_Acme_...pdf   │
│ .../globex/jobs/2468101 │ done   │ .../master-resume_Globex_...pdf │
└─────────────────────────┴────────┴─────────────────────────────────┘

3/3 succeeded.
```

#### When one job in the batch fails

```
                                Batch tailoring summary
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job URL               ┃ Status            ┃ Output / Error                          ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ .../acme/jobs/1234567 │ done              │ .../master-resume_Acme_...pdf           │
│ .../acme/jobs/7654321 │ failed (generate) │ Generated tex failed to compile to PDF. │
└───────────────────────┴───────────────────┴─────────────────────────────────────────┘

1/2 succeeded.
```

Exits with code `1` if anything in the batch failed — same scripting pattern as `tailor`:

```
$ weave-cv batch -f jobs.csv || echo "one or more jobs failed"
```

#### A bad input file

```
$ weave-cv batch -f jobs.csv
Couldn't find a URL column in the header row — expected one of ['job_url', 'url', 'link', 'job_link'], found: ['company', 'notes']
```
