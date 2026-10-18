# HireIntel 🎯
### AI-assisted resume review: similarity scoring plus evidence-based strengths and gaps

HireIntel helps a recruiter look through a batch of resumes for one job. You paste a job description (or a short job title), upload resumes, and for each resume HireIntel shows:

- a **similarity score** (0–100) between the job description and the resume, computed from text embeddings;
- an **AI-written analysis**: a short summary, requirements the resume shows evidence for, requirements with no evidence found, and points to verify with the candidate;
- the **extracted text**, so you can check what the system actually read.

### Requirement mode (evidence per requirement)

Click **Extract requirements to check** after pasting a job description:

1. The AI proposes a checklist of requirements, each marked **mandatory** or **preferred**. Conditions a resume can't show (citizenship, documents, shift availability, relocation) are listed separately as *not checked from resumes*.
2. You edit the list: reword items, change importance, delete them or add your own.
3. Each resume is assessed against every confirmed requirement in one AI call. Each requirement gets one of three states:
   - **Evidence found**: the AI quoted the resume, and the quote was **found in the extracted text** by HireIntel's own check.
   - **Needs review**: the evidence is ambiguous, the AI's quote could not be found in the text, or part of the resume was cut.
   - **No evidence found**: nothing in a complete, readable resume mentions it. This is not proof that the candidate lacks it.
4. Candidates are grouped into bands by their mandatory requirements: **B1** all supported, **B2** some need review, **B3** no evidence for one, **B4** no evidence for two or more. Within a band, more supported preferred requirements come first. **No band rejects anyone.**

A verified quote proves the words exist in the resume. It doesn't prove the AI interpreted them correctly, so the quotes are shown for you to judge.

5. **Review evidence** opens a candidate's requirements beside the extracted text, with every verified quote highlighted. Click a quote to jump to it in the text, or a highlight to find its requirement. **Open original file** shows the file you uploaded, straight from your browser.
6. You can change any requirement's state. A reason is required (and a note, for "Other"). The band is recalculated with the same rules, the card shows the change (e.g. `B3 → B2`), and **Group by reviewed bands** reorders the list.
7. **Export review (CSV)** saves every requirement with the AI's state, your final state, the reason and the verified quotes. Review changes stay in the browser tab only, so export them before closing or running again. The page warns you if you haven't.

> **This is a portfolio demo, not a hiring tool.** Results are suggestions for a human reviewer. The similarity score is not a probability of fit, and the AI analysis can be wrong. HireIntel never rejects anyone automatically.

---

## 📋 Problem

Recruiters reviewing many resumes run into a few recurring problems that HireIntel tries to make visible:

1. **Keyword matching misses synonyms.** "Backend Software Engineer" and "Python Developer" can describe the same person. Embeddings capture some of that similarity.
2. **A single score explains nothing.** HireIntel pairs the score with requirement-level evidence and gaps.
3. **Scanned resumes have no text.** PDFs without a text layer and image resumes go through AI text recognition (OCR), and the result is labelled as OCR output.
4. **LLMs get dates wrong.** The current year is passed to the model so it can calculate graduation and experience dates correctly.

## 🧭 Design principles

- **Failures are never disguised as results.** If scoring or analysis fails, the resume is marked `partial` with a visible warning. It never shows "0%" or a made-up analysis.
- **"No evidence found" is not "lacks the skill".** Gaps are worded as missing evidence in the resume text.
- **Resume text is treated as data.** The text is fenced off in the prompt, and the model is told to ignore and report any instructions hidden in a resume. The sample `kavya_python_intern.txt` contains such an instruction so you can see this in action.
- **Honest limits.** Long resumes that had to be cut, and OCR output that hit its length limit, are flagged.
- **Hidden text is set aside, not trusted.** Text a reader can't see (Word's hidden text, white text with nothing coloured behind it, microscopic fonts, text off the page) is left out of the analysis and listed on the candidate's card, because hidden keywords and instructions are a known way to game screening tools. White text on a coloured sidebar, banner or text box counts as visible.

---

## 🛠️ Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML, CSS and JavaScript, served by the backend from the same origin |
| Backend | FastAPI, Uvicorn, Python 3.12 |
| AI | Google Gemini API via the `google-genai` SDK: `gemini-3.5-flash-lite` for analysis and OCR (falling back to `gemini-3.8-flash`), `gemini-embedding-2` (768 dimensions) for similarity |
| Documents | `pypdfium2` and `pdfplumber` for PDFs, a defused `lxml` walk of the DOCX XML (body, tables, text boxes, content controls, headers and footers) |
| Quality | pytest, ruff, GitHub Actions |

Model IDs are configuration, not code (`app/config.py`), so a retired model can be replaced without a code change.

## 📐 Architecture

```mermaid
flowchart TD
    A[Browser] -->|POST /api/match: JD + resumes| B[FastAPI]
    B --> L[Rate limits and daily budget]
    B --> C[File validation by content type]
    C --> D[Text extraction: pypdfium2, pdfplumber, DOCX XML walk]
    D -->|no text layer| E[Gemini OCR, flagged as OCR]
    B --> F[gemini-embedding-2: JD and resume vectors]
    F --> G[Cosine similarity 0-100]
    B --> H[Gemini analysis: structured JSON]
    G --> I[Per-resume result: success, partial or error]
    H --> I
    I -->|sorted, unscored after scored, errors last| A
```

Each resume is processed independently (4 at a time). One bad file can't break the batch. Scoring and analysis for a resume run concurrently.

### Data handling

- Files are processed in memory per request and are **not stored** by HireIntel. There is no database. The web server may briefly buffer uploads over 1 MB in a temporary file while receiving them.
- **All resume text is sent to Google's Gemini API.** On the free tier, Google may use submitted content to improve its products and humans may review it ([Gemini API terms](https://ai.google.dev/gemini-api/terms)). That is why the public demo asks for **sample or made-up resumes only**.
- Logs record counts, statuses and error types, never resume or job description text.

---

## 🔒 Public demo protections

| Protection | Default | Setting |
|---|---|---|
| Requests per client per minute | 3 | `RATE_LIMIT_PER_MINUTE` |
| Requests per client per day | 20 | `RATE_LIMIT_PER_DAY` |
| Resumes processed per day (all users) | 150 | `DAILY_RESUME_BUDGET` |
| Files per request | 10 | `MAX_FILES` |
| Size per file | 5 MB | `MAX_FILE_SIZE_MB` |
| Optional access code | off | `DEMO_ACCESS_CODE` |
| Cross-origin calls | blocked | `CORS_ORIGINS` |

Oversized requests are rejected before the body is read. File types are checked from the file's content, not just its extension. Legacy `.doc` files are rejected with a clear message. Limits are kept in memory and reset when the server restarts, which is fine for a single-instance demo.

---

## ⚙️ Run locally

**Prerequisites:** Python 3.12+ and a Gemini API key from [Google AI Studio](https://aistudio.google.com/).

```bash
git clone https://github.com/ShreyasHegde0105/HireIntel.git
cd HireIntel

python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env    # then put your GEMINI_API_KEY in .env

uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and click **Load sample job & resumes**, then **Analyze and Rank**. API docs are at http://127.0.0.1:8000/docs.

### Tests and lint

```bash
pytest -q
ruff check .
```

The tests use a fake Gemini client, so they need no API key and cost nothing. They cover the failure rules: a failed embedding never becomes a score and is never cached, failed analyses are never faked, temporary overloads are retried, bad files are rejected, and limits are enforced.

### Evaluate requirement states

`evaluation/` holds a synthetic set of 3 jobs and 12 resumes (60 requirement checks), a labelling rubric and a scoring script that compares the app's states with human labels. See [evaluation/README.md](evaluation/README.md).

---

## 🚀 Deploy (Render free tier)

The repository includes `render.yaml` and a `Dockerfile`. The container runs as a non-root user, honours `$PORT`, and has a health check at `/health`.

1. In Render, create a **Blueprint** from this repository (or a Docker web service).
2. Set `GEMINI_API_KEY` in the service's environment. Optionally set `DEMO_ACCESS_CODE`.
3. Deploy. The frontend and API are served from the same URL.

The free tier sleeps after 15 minutes without traffic. The first request after that can take about a minute while it wakes up; the frontend waits up to 3 minutes.

CI (`.github/workflows/ci.yml`) runs lint and tests on every push, then builds the Docker image and checks that `/health` responds.

---

## ⚠️ Known limitations

- The similarity score is uncalibrated cosine similarity. Scores for related resumes often cluster closely (for example 65–80), so compare candidates within one run rather than reading the number as an absolute grade.
- The analysis is a single LLM pass per resume and can miss or misread evidence. Quotes are checked and highlighted in the extracted text, not drawn on the original PDF.
- Review changes are not saved on the server. They live in the browser tab until you export them.
- "No evidence found" covers both "not mentioned" and "the resume shows something different" (e.g. a B.Sc. against a required B.Tech); the note explains which.
- DOCX footnotes, endnotes and comments are not read.
- Hidden-text detection is heuristic. White text over a colour that is set by a table style or theme can still be read as visible, and some designs with white text and no detectable background may be flagged; the card lists anything left out so you can check.
- Response time depends on Gemini. On the free tier the model is sometimes overloaded; affected resumes are then shown as `partial` with a warning.
- No accounts, history or persistence. Re-running costs another round of API calls.

## 🗺️ Next steps

- Save reviews on the server (Postgres) so they survive a reload and can be audited.
- Tighten the assessment prompt after reviewers settle the skills-list rule; it currently counts mobile years as web frontend experience.
- Get two reviewers to label the evaluation set in `evaluation/` so requirement states can be measured against humans, not just against the cases' design.
