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
    │   ├─ scrape (deterministic) -> JD-Analyzer   extract    │
    │   │    job requirements — cache-first, 48h TTL          │
    │   └─ CV-Analyzer   parse .tex into a structured profile │
    │        cache-first, keyed on the file's own content hash│
    │        (concurrent, both keyed to the same stable IDs)  │
    │                                                         │
    │ tailor     reorder / reselect / reword, same IDs kept   │
    │ verify     structural diff (no LLM) + narrow LLM check  │
    │            on just the bullets that got reworded        │
    │            fails -> back to tailor (bounded retries)    │
    │ generate   same LaTeX macros as your template -> PDF    │
    │            page under-filled -> back to tailor (bounded)│
    │            also writes a cover letter + job posting     │
    │            record alongside it                          │
    └─────────────────────────────────────────────────────────┘
        │
        ▼
 tailored .tex + .pdf + cover_letter.txt + job_posting.json,
 verified against the original, in their own "<company> - <timestamp>"
 output folder
```

- **gather_inputs** — the job posting and your resume are read
  concurrently. The posting is fetched by a plain deterministic scrape
  (no LLM decides *to* fetch it — there was never a real decision
  there), then handed to the JD-Analyzer agent to distill into
  structured requirements (required vs. preferred skills,
  qualifications, ATS keywords). The resume's `.tex` is parsed by the
  CV-Analyzer into a structured profile — every experience, project,
  bullet, and skill — with stable IDs assigned in document order
  (`exp1`, `exp1-b2`, `proj1`, ...). Both analyses are cache-first (see
  [Caching](#caching)), so a rerun against the same resume or the same
  still-fresh posting skips the LLM call entirely.
- **tailor** — reorders and reselects from the structured profile to
  foreground what's relevant to the job, and rewords bullets to mirror
  the posting's terminology. Outputs the same schema, reusing the same
  IDs: a kept bullet keeps its ID, a dropped one is simply absent,
  nothing gets an ID that wasn't already there. Bullets are condensed
  before they're cut — a bullet only disappears entirely as a last
  resort, once rewording it tighter still doesn't make it fit.
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
  same macros as the original, then compiled straight to PDF. This
  stage handles page-fit on its own: a compile error or overflow past
  one page gets a formatting-only retry here (no need to go back and
  re-tailor content for a spacing problem); a page that comes out
  under-filled routes back to **tailor** instead, since trimming
  content back down needs the job's full context, which only tailor
  has. Both retry loops are bounded. Once generation succeeds, it also
  writes `cover_letter.txt` (built around "why this company" / "why
  you're a fit," not boilerplate salutations) and `job_posting.json`
  (the posting's URL and extracted requirements) into the same output
  folder — both best-effort, neither can fail the pipeline.

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
- **Prompt caching on Anthropic.** When the configured provider is
  Anthropic, every agent's system prompt is sent as a `cache_control`
  block instead of a plain string, so a resume that goes through
  several tailor/verify/generate calls in one run only pays full input
  cost on the prompt once. A no-op on every other provider.
- **Agent/tool boundary via [MCP](https://modelcontextprotocol.io/).**
  Each agent's prompt and tools are served over their own MCP process
  rather than hardcoded inline strings.
- **Rendering** runs through [Tectonic](https://tectonic-typesetting.github.io/),
  a self-contained LaTeX engine with no dependency on a system TeX install.

## Job discovery & applications (experimental)

A separate extension on top of the tailoring pipeline above — genuinely
separate, sharing no code path with `tailor`/`batch`, only the same
local config and a small SQLite database both sides read from.

- **`discover`** searches Ashby, Greenhouse, Lever, and Workday for
  postings that match your resume, judging each one against your
  résumé's title/location/experience fit with an LLM call, and records
  what it finds.
- **`apply`** opens a real browser, navigates to a discovered job's
  actual application form, and fills in what it can confidently infer
  from your resume — then stops. It never clicks Submit, and it never
  touches anything legally or personally sensitive (EEO/demographic
  questions, work authorization, salary, CAPTCHAs) — those are always
  left for you to answer and submit yourself.

Chained with `batch --from-db`, the three commands form a loop:

```
$ weave-cv discover -k "backend engineer,platform engineer"
$ weave-cv batch --from-db
$ weave-cv apply --from-db
```

Each rerun only ever acts on what's new — already-scored postings,
already-tailored jobs, and already-attempted applications are tracked
and skipped automatically (see [Caching](#caching)).

## Docs / CLI reference

- [Installation](#installation)
- [`weave-cv config`](#weave-cv-config)
- [`weave-cv tailor`](#weave-cv-tailor)
- [`weave-cv batch`](#weave-cv-batch)
- [`weave-cv discover`](#weave-cv-discover)
- [`weave-cv apply`](#weave-cv-apply)
- [Caching](#caching)

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

#### Tavily API key (for `discover`)

`discover` needs its own key, separate from the LLM one, for the
[Tavily](https://tavily.com) search API it uses to find postings — free,
no card required:

```
$ weave-cv config set --tavily-api-key tvly-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml
```

Only `discover` touches it — every other command ignores it. Skip it and
weave-cv asks the first time `discover` actually needs it, same as the
LLM API key.

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
tavily_api_key: ****xxxx
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

#### From the database, instead of a file

Skip the CSV entirely and pull every posting [`discover`](#weave-cv-discover)
found relevant that hasn't already been tailored:

```
$ weave-cv batch --from-db
Found 4 relevant, unapplied job(s) in the database. Processing up to 3 at a time.
```

`--file` and `--from-db` are mutually exclusive — exactly one is
required. Nothing found ("run `discover` first") exits cleanly with code `0`, not an error.

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

### `weave-cv discover`

Searches Ashby, Greenhouse, Lever, and Workday for job postings, fetching
each one directly by URL rather than pulling a whole company's board.
Postings get filtered down — freshness, already-seen, keyword match, a
deterministic title-only seniority check — before whatever's left is
judged against your resume with a single LLM call per posting: title,
location, and years of experience only, deliberately no job description.
Requires a free [Tavily](https://tavily.com) API key (no card needed) —
weave-cv asks for one the first time it's needed, same as the LLM API key
(see [Tavily API key](#tavily-api-key-for-discover) above).

Standalone experiment, separate from `tailor`/`batch` — it only searches
and judges relevance, it never tailors or generates anything.

#### Basic run

```
$ weave-cv discover -k "backend engineer,platform engineer"
```

Long-flag equivalents: `--keywords`, `--master-resume`. Keywords are
comma-separated — each one is searched separately, once per platform, so
two keywords means eight Tavily searches, not one.

#### What a run looks like

```
Candidate role fit — roles: Backend Engineer, Platform Engineer, Software Engineer | experience: 2-3y | skills: Python, Go, Kubernetes, PostgreSQL

Tavily search keyword='backend engineer' platform=greenhouse domains=['*.greenhouse.io', 'job-boards.greenhouse.io'] -> 18 result(s)
Tavily search keyword='backend engineer' platform=lever domains=['jobs.lever.co'] -> 14 result(s)
Tavily search keyword='backend engineer' platform=ashby domains=['jobs.ashbyhq.com'] -> 9 result(s)
Tavily search keyword='backend engineer' platform=workday domains=['*.myworkdayjobs.com'] -> 20 result(s)

Unique postings found: 57

  greenhouse -> Backend Engineer @ Acme
  lever -> Platform Engineer @ Globex
  ashby -> Senior Backend Engineer @ Initech
  ...

Funnel: 57 posting(s) fetched -> 41 fresh -> 33 not already scored -> 21 matched keywords -> 15 filtered on title alone -> 6 judging now

Judging Backend Engineer @ Acme (greenhouse) — https://job-boards.greenhouse.io/acme/jobs/1234567
  RELEVANT — title: "Backend Engineer" lines up directly with target_roles; location: Remote; years: no seniority signal in the title

Judging Staff Platform Engineer @ Umbrella (lever) — https://jobs.lever.co/umbrella/98765
  not relevant — years: "Staff" implies ~6+ years, well above the candidate's 3y max

                              1 relevant posting(s) found
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Title                 ┃ Company┃ Platform ┃ Posted  ┃ Why                                  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Backend Engineer      │ Acme  │ greenhouse│ 3.2h ago│ title lines up directly with target…│
└───────────────────────┴───────┴──────────┴─────────┴──────────────────────────────────────┘

Backend Engineer @ Acme — https://job-boards.greenhouse.io/acme/jobs/1234567
```

#### Options

- `--max-age-hours` (default `48`) — only postings newer than this.
- `--ignore-seen` — re-judge postings a previous `discover` run already
  scored, instead of skipping them automatically. The fresh verdict
  replaces the old one — useful if the pool of genuinely new postings
  looks thin and you want another shot at ones seen before (e.g. after
  loosening keywords).

#### Where results go

Every posting checked — relevant or not — is recorded in a local SQLite
database (`~/.weave-cv/weave_cv.db`), so a rerun never re-scores the same
posting twice. `weave-cv batch --from-db` (see [above](#from-the-database-instead-of-a-file))
reads straight from this table.

### `weave-cv apply`

Opens a real, visible browser window, navigates to a job's actual
application form (not just the posting page — Greenhouse's embedded
form, or the separate `/apply`-style URL Lever and Ashby use), and fills
in what it can confidently map from your resume's contact info: name,
email, phone, links, and the tailored resume/cover-letter file uploads.

It **never clicks Submit or Apply**, and it never lets a model anywhere
near anything sensitive — work authorization, visa/sponsorship,
citizenship, salary, EEO/demographic questions (gender, race, veteran,
disability), consent/background-check questions, signatures, and
CAPTCHAs are all excluded by deterministic regex-based code before the
form-fill agent ever sees the field list (see `services/browser.py`).
Fields with no stable `id`/`name` to safely target are skipped
automatically too, rather than risk filling the wrong thing. The browser
is left open afterwards so you can review everything, answer whatever
was skipped, and submit it yourself.

Supports Ashby, Greenhouse, and Lever. Workday isn't supported — its
flow generally requires creating a candidate account first, which is out
of scope here.

Requires the job to already have a tailored resume — run `tailor` or
`batch` on it first; `apply` only ever consumes what they already
produced.

#### One specific job

```
$ weave-cv apply -j https://job-boards.greenhouse.io/acme/jobs/1234567
```

#### Every tailored job not yet attempted

```
$ weave-cv apply --from-db
Found 2 job(s) to apply to, one at a time.
```

Long-flag equivalents: `--job-url`, `--from-db` (exactly one is
required), `--master-resume`.

#### What a run looks like

```
Opening application form: https://job-boards.greenhouse.io/acme/jobs/1234567
Filled 4 field(s): Full name, Email, Phone, LinkedIn
Left 2 field(s) for you:
  - Why do you want to work here?: not confidently mappable
  - Are you authorized to work in this country?: excluded — work authorization question

Review the filled form in the browser window — check every field, answer what was skipped, solve any CAPTCHA, and submit it yourself if it looks right. Press Enter here once you're done (submitted or not) to close the browser...
```

Attempts are recorded in the same local database `discover` uses, so a
rerun with `--from-db` never revisits a job it's already tried.

### Caching

Two things are cached locally so reruns don't re-pay for an LLM call (or
a scrape) that would produce the same answer, plus one plain history log
that isn't a cache at all:

| What | Where | Keyed on | Expires |
|---|---|---|---|
| Master resume analysis (CVProfile) | `~/.weave-cv/cache/cv_analysis/` | resume file's own content hash | Never — a byte-for-byte resume change is what invalidates it. |
| Candidate role-fit summary (used by `discover` only) | `~/.weave-cv/cache/candidate_role_fit/` | same content hash | Never, same as above — it's a derived summary of the same file. |
| Job posting analysis (JD) | cache directory, keyed per URL | job posting URL | 48 hours — a posting's content can change, or it can close, without its URL changing. |

Every cache is versioned internally (`CACHE_SCHEMA_VERSION`): if a schema
field is added or changed, entries cached under the old shape are treated
as a miss and silently re-fetched rather than served stale forever.

`discover`'s scoring history (which postings were seen and how they were
judged), and `tailor`/`batch`/`apply`'s outcome history, live separately
in a small SQLite database at `~/.weave-cv/weave_cv.db` — that's a record
of what happened, not a cache, and isn't touched by anything below.

#### Check what's cached

```
$ weave-cv cache show
Cached (CV): master-resume.tex
  name: Jane Doe
  cached at: 2026-08-15 09:12:03

Pass --job-url to check a specific job posting's cache status.

                All cached CV analyses (1)
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Hash        ┃ Name    ┃ Cached At          ┃ Size   ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ a1b2c3d4e5f6│ Jane Doe│ 2026-08-15 09:12:03│ 4,213 B│
└─────────────┴─────────┴────────────────────┴────────┘

No cached JD analyses.
```

#### Clear it

```
$ weave-cv cache clear
Cleared 1 cached CV analysis file(s), 1 cached candidate role-fit summary(ies), 3 cached JD analysis file(s), and 12 discovered-job record(s).
```

This clears the CV analysis cache, the candidate role-fit cache, the JD
analysis cache, **and** the `discovered_jobs` "seen" history — so the
next `discover` run re-scores and re-shows postings it already judged,
same as passing `--ignore-seen` but for everything at once. It does not
touch the `applied_jobs`/`applications` tables — that history of what
you actually tailored and applied to is never cleared automatically.
