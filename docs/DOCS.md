# weave-cv docs

Every example below uses the same scenario throughout:

- master resume: `~/resumes/master-resume.tex`
- output folder: `~/tailored-resumes`
- job posting: `https://job-boards.greenhouse.io/acme/jobs/1234567` (company: Acme)

Swap those three for your own paths/URL — everything else stays the same.

## `weave-cv config`

### Set your master resume and output folder once

```
$ weave-cv config set --master-resume ~/resumes/master-resume.tex --output-dir ~/tailored-resumes
Saved to /Users/you/.weave-cv/config.toml
```

### Set your provider, model, and API key

```
$ weave-cv config set --provider openai --model gpt-5-mini --api-key sk-proj-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml
```

Same flag works for any supported provider — just swap `--provider`/`--model`:

```
$ weave-cv config set --provider anthropic --model claude-sonnet-5 --api-key sk-ant-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --provider google_genai --model gemini-2.0-flash --api-key AIzaSyxxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --provider groq --model llama-3.3-70b-versatile --api-key gsk_xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --provider xai --model grok-4 --api-key xai-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml

$ weave-cv config set --provider deepseek --model deepseek-chat --api-key sk-xxxxxxxxxxxx
Saved to /Users/you/.weave-cv/config.toml
```

### Update a single value later

Flags you omit are left unchanged — this only touches `--output-dir`:

```
$ weave-cv config set --output-dir ~/Desktop/resumes-2026
Saved to /Users/you/.weave-cv/config.toml
```

### Calling `config set` with nothing to save

```
$ weave-cv config set
No values given — nothing changed.
```

### View what's saved

```
$ weave-cv config show
master_resume: /Users/you/resumes/master-resume.tex
output_dir: /Users/you/tailored-resumes
api_key: ****xxxx
provider: openai
model: gpt-5-mini
```

Before anything is ever saved:

```
$ weave-cv config show
No config saved yet — see `weave-cv config set --help`.
```

### First run, no config, no `.env`

If you skip `config set --api-key` entirely, `weave-cv` asks once and remembers it:

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567 -m ~/resumes/master-resume.tex -o ~/tailored-resumes
No API key found for provider 'openai' — enter one:
Saved API key to your weave-cv config.
```

## `weave-cv tailor`

Tailors one master resume against one job posting.

### Everything from config (nothing to type but the job URL)

```
$ weave-cv tailor -j https://job-boards.greenhouse.io/acme/jobs/1234567
```

### Fully explicit, no config required

```
$ weave-cv tailor \
    -j https://job-boards.greenhouse.io/acme/jobs/1234567 \
    -m ~/resumes/master-resume.tex \
    -o ~/tailored-resumes
```

### Long-flag form

```
$ weave-cv tailor \
    --job-url https://job-boards.greenhouse.io/acme/jobs/1234567 \
    --master-resume ~/resumes/master-resume.tex \
    --output-dir ~/tailored-resumes
```

### What a run looks like

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

### When verification fails and retries

```
▶ Verifying tailored resume...
  4.1s … Verifying tailored resume — failed, retrying: exp1-b2: Reworded version adds a metric ("40% faster") not present in the original.
▶ Tailoring resume (retry)...
 31.0s ✓ Tailoring resume (attempt 2)
▶ Verifying tailored resume...
  2.2s ✓ Verifying tailored resume — passed
```

### When a stage fails outright

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

## `weave-cv batch`

Tailors the same master resume against many job postings, concurrently.

### Build the input file

```
$ cat jobs.csv
job_url
https://job-boards.greenhouse.io/acme/jobs/1234567
https://job-boards.greenhouse.io/acme/jobs/7654321
https://job-boards.greenhouse.io/globex/jobs/2468101
```

Any of these header names works (case/spacing-insensitive): `job_url`, `url`, `link`, `job_link`. Also accepts `.xlsx` with the same header convention:

```
$ weave-cv batch -f jobs.xlsx
```

### Run it, everything else from config

```
$ weave-cv batch -f jobs.csv
Found 3 job URL(s) in jobs.csv. Processing up to 3 at a time.
```

### Run it with an explicit concurrency cap

```
$ weave-cv batch -f jobs.csv --concurrency 2
Found 3 job URL(s) in jobs.csv. Processing up to 2 at a time.
```

### Fully explicit, no config required

```
$ weave-cv batch \
    -f jobs.csv \
    -m ~/resumes/master-resume.tex \
    -o ~/tailored-resumes \
    -c 2
```

### What a batch run looks like

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

### When one job in the batch fails

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

### A bad input file

```
$ weave-cv batch -f jobs.csv
Couldn't find a URL column in the header row — expected one of ['job_url', 'url', 'link', 'job_link'], found: ['company', 'notes']
```
