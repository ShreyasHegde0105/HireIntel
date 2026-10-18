# Requirement-state evaluation

Measures how often HireIntel's requirement states (`supported`, `needs_review`, `no_evidence`)
agree with human reviewers. All data here is synthetic.

## What is here

| Path | What it is |
|---|---|
| `data/jobs.json` | 3 jobs with confirmed requirements (5 each), and which resumes go with which job |
| `data/resumes/` | 12 synthetic resumes, written to hit known hard cases (see below) |
| `data/designer_intent.csv` | The state each case was **built** to have. One person's view, written with the cases: a smoke test, not ground truth |
| `RUBRIC.md` | Labelling rules for raters |
| `labels/` | Rater sheets go here (`<initials>.csv`), plus `adjudicated.csv` after disagreements are settled |
| `predictions/` | Saved app runs. Each records the model that answered |

60 items in total (12 resumes × 5 requirements). Hard cases covered: synonyms (Postgres,
"split tests", "HTTP JSON endpoints"), related-but-not-equivalent tools (MySQL, Looker,
Cypress, React Native), skills-list-only evidence, durations that fall short or depend on an
internship, an arguable "related field" degree, a pipe-separated table layout, and a prompt
injection.

## Process

```bash
python -m evaluation.evaluate template        # writes evaluation/labelling_sheet.csv
# each rater: copy it to evaluation/labels/<initials>.csv, label alone using RUBRIC.md
python -m evaluation.evaluate predict         # runs the app's assessment; needs GEMINI_API_KEY (12 calls)
python -m evaluation.evaluate score           # rater agreement, disagreements, app vs reviewers
```

`score` reports Krippendorff's alpha between raters and lists rows they disagree on. Settle those
together and write them to `labels/adjudicated.csv`. The gold label is the adjudicated one, or else
a strict majority. It then compares the app with that gold label:
accuracy, Cohen's kappa, a confusion matrix, per-state precision and recall, and the two costly
mistakes:

- **missed evidence**: reviewers say `supported`, the app says `no_evidence` (a candidate is hidden);
- **false support**: reviewers say `no_evidence`, the app says `supported` (evidence is invented).

Use at least two raters; with one, agreement between reviewers cannot be measured. Model output
varies between runs, so compare runs on the same model before drawing conclusions.

## Baseline (2026-10-18, gemini-3.5-flash-lite, against designer intent only)

`predictions/20261018T061203Z.json`: accuracy 0.90, kappa 0.83, missed evidence 0.00, false support
0.00. The injection in r04 was flagged. Six mismatches:

- **Skills lists and personal projects (4 items, r03).** The app gives `needs_review` where the rubric
  says a skills-list entry supports a requirement about using a tool. Raters should settle this
  rule first; either the rubric or the prompt changes.
- **Durations (2 items).** r02 has 2 of 3 required Python years: the app says `needs_review`, the
  rubric says `no_evidence` (a cautious difference). r03 has no dated roles: the app says
  `no_evidence`, the rubric says `needs_review`.
- **Mobile counted as frontend (r12 R3).** The app counted React Native mobile years toward
  "frontend development" and said `supported`. That is a real error to watch for.

These numbers only show the harness works and point to the questions to ask reviewers. They are
not a measure of agreement with humans until rater sheets exist.
