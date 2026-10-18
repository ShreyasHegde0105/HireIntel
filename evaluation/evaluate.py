"""Requirement-state evaluation: how often HireIntel's states agree with human reviewers.

    python -m evaluation.evaluate template            # blank sheet for a rater
    python -m evaluation.evaluate predict             # run the app's assessment (calls Gemini)
    python -m evaluation.evaluate score               # rater agreement + system vs human labels
    python -m evaluation.evaluate score --gold evaluation/data/designer_intent.csv   # smoke test only

See evaluation/README.md for the process.
"""

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluation.metrics import STATES, Labels, compare, disagreements, krippendorff_alpha_nominal, majority_gold

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LABELS_DIR = ROOT / "labels"
PREDICTIONS_DIR = ROOT / "predictions"
COLUMNS = ["job_id", "resume_id", "requirement_id", "importance", "requirement", "state", "note"]


def load_jobs(data_dir: Path = DATA) -> list:
    return json.loads((data_dir / "jobs.json").read_text(encoding="utf-8"))["jobs"]


def cases(data_dir: Path = DATA):
    """Yields (job, resume_id, resume_text, requirements with IDs R1..Rn)."""
    from app.services.requirements import validate_requirements

    for job in load_jobs(data_dir):
        requirements = validate_requirements(job["requirements"])
        for resume_id in job["resumes"]:
            text = (data_dir / "resumes" / f"{resume_id}.txt").read_text(encoding="utf-8")
            yield job, resume_id, text, requirements


def read_labels(path: Path) -> Labels:
    labels = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            state = (row.get("state") or "").strip().lower()
            if not state:
                continue  # unlabelled row
            if state not in STATES:
                raise SystemExit(f"{path.name} line {line_no}: state must be one of {', '.join(STATES)}, got {state!r}")
            labels[(row["job_id"].strip(), row["resume_id"].strip(), row["requirement_id"].strip())] = state
    return labels


def write_template(out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for job, resume_id, _, requirements in cases():
            for r in requirements:
                writer.writerow([job["id"], resume_id, r["id"], r["importance"], r["text"], "", ""])
    print(f"Wrote {out}. Copy it to evaluation/labels/<your-initials>.csv and fill in the state column (see RUBRIC.md).")


async def _predict(out: Path) -> None:
    from app.services.ai_client import AIUnavailableError
    from app.services.parser import clean_text
    from app.services.requirements import assess_resume

    items, errors, models = [], [], set()
    for job, resume_id, text, requirements in cases():
        print(f"{job['id']}/{resume_id} ...", end=" ", flush=True)
        try:
            assessment = await assess_resume(clean_text(text), requirements)
        except AIUnavailableError as e:
            print("error")
            errors.append({"job_id": job["id"], "resume_id": resume_id, "error": str(e)})
            continue
        print(assessment["band"]["code"])
        models.add(assessment["model"])
        for r in assessment["requirements"]:
            items.append(
                {
                    "job_id": job["id"],
                    "resume_id": resume_id,
                    "requirement_id": r["id"],
                    "state": r["state"],
                    "quotes": r["quotes"],
                    "note": r["note"],
                    "band": assessment["band"]["code"],
                    "manipulation_detected": assessment["manipulation_detected"],
                }
            )
    run = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": sorted(models),
        "items": items,
        "errors": errors,
    }
    out.write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(items)} items, {len(errors)} errors).")


def read_predictions(path: Path) -> tuple:
    run = json.loads(path.read_text(encoding="utf-8"))
    labels = {(i["job_id"], i["resume_id"], i["requirement_id"]): i["state"] for i in run["items"]}
    return labels, run


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _print_comparison(title: str, result: dict) -> None:
    print(f"\n## {title}\n")
    print(f"Items compared: {result['items']}  (no prediction: {result['missing_predictions']})")
    print(f"Accuracy: {_fmt(result['accuracy'])}   Cohen's kappa: {_fmt(result['kappa'])}")
    print(f"Missed evidence (human: supported, app: no_evidence): {_fmt(result['missed_evidence_rate'])}")
    print(f"False support (human: no_evidence, app: supported):  {_fmt(result['false_support_rate'])}")
    print("\nConfusion (rows = human, columns = app):")
    width = max(len(s) for s in STATES) + 2
    print(" " * width + "".join(s.rjust(width) for s in STATES))
    for gs in STATES:
        print(gs.ljust(width) + "".join(str(result["confusion"][gs][ps]).rjust(width) for ps in STATES))
    print("\nPer state:")
    for s, m in result["per_state"].items():
        print(f"  {s:<14} precision {_fmt(m['precision'])}  recall {_fmt(m['recall'])}  (human count {m['gold_count']})")


def _latest_predictions() -> Path:
    runs = sorted(PREDICTIONS_DIR.glob("*.json"))
    if not runs:
        raise SystemExit("No predictions yet. Run: python -m evaluation.evaluate predict")
    return runs[-1]


def score(predictions: Path, gold_file: Path = None, labels_dir: Path = LABELS_DIR) -> None:
    predicted, run = read_predictions(predictions)
    print(f"# Requirement-state evaluation\n\nPredictions: {predictions.name}  models: {', '.join(run['models']) or 'n/a'}")
    if run["errors"]:
        print(f"Resumes the app failed on: {len(run['errors'])}")

    if gold_file:
        print(f"\nReference: {gold_file.name} (one labeller; not a measure of agreement with reviewers)")
        _print_comparison("App vs reference", compare(read_labels(gold_file), predicted))
        return

    adjudicated_path = labels_dir / "adjudicated.csv"
    raters = {p.stem: read_labels(p) for p in sorted(labels_dir.glob("*.csv")) if p != adjudicated_path}
    raters = {name: labels for name, labels in raters.items() if labels}
    if not raters:
        raise SystemExit(f"No rater sheets in {labels_dir}. Create one with: python -m evaluation.evaluate template")
    adjudicated = read_labels(adjudicated_path) if adjudicated_path.exists() else {}

    print(f"\nRaters: {', '.join(raters)}" + ("  + adjudication" if adjudicated else ""))
    if len(raters) >= 2:
        items = sorted(set().union(*(set(labels) for labels in raters.values())))
        units = [[labels[i] for labels in raters.values() if i in labels] for i in items]
        print(f"Krippendorff's alpha (raters): {_fmt(krippendorff_alpha_nominal(units))}")
        open_rows = [(item, given) for item, given in disagreements(raters) if item not in adjudicated]
        if open_rows:
            print(f"\nDisagreements to adjudicate ({len(open_rows)}):")
            for (job_id, resume_id, req_id), given in open_rows:
                print(f"  {job_id}/{resume_id}/{req_id}: " + ", ".join(f"{n}={s}" for n, s in given.items()))
    else:
        print("Only one rater: agreement between reviewers cannot be measured yet.")

    gold, unresolved = majority_gold(raters, adjudicated)
    if unresolved:
        print(f"\n{len(unresolved)} tied items are left out until adjudicated.")
    _print_comparison("App vs reviewers", compare(gold, predicted))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template", help="write a blank labelling sheet")
    t.add_argument("--out", type=Path, default=ROOT / "labelling_sheet.csv")
    p = sub.add_parser("predict", help="run the app's requirement assessment on every case (calls Gemini)")
    p.add_argument("--out", type=Path)
    s = sub.add_parser("score", help="compare app states with human labels")
    s.add_argument("--predictions", type=Path, help="defaults to the latest file in evaluation/predictions")
    s.add_argument("--gold", type=Path, help="score against one labels file instead of the rater sheets")
    s.add_argument("--labels", type=Path, default=LABELS_DIR)
    args = parser.parse_args(argv)

    if args.command == "template":
        write_template(args.out)
    elif args.command == "predict":
        from app.config import settings

        settings.validate()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        PREDICTIONS_DIR.mkdir(exist_ok=True)
        asyncio.run(_predict(args.out or PREDICTIONS_DIR / f"{stamp}.json"))
    else:
        score(args.predictions or _latest_predictions(), args.gold, args.labels)


if __name__ == "__main__":
    sys.exit(main())
