import json

import pytest

from evaluation import evaluate
from evaluation.metrics import cohen_kappa, compare, disagreements, krippendorff_alpha_nominal, majority_gold

S, N, X = "supported", "needs_review", "no_evidence"


def test_cohen_kappa_known_value():
    assert cohen_kappa([S, S, N, N], [S, N, N, N]) == pytest.approx(0.5)
    assert cohen_kappa([S, N], [S, N]) == 1.0


def test_krippendorff_alpha_known_value():
    # Two raters, four units: coincidences SS=2, SN=NS=1, NN=4 -> alpha = 1 - 0.25 / (30/56)
    assert krippendorff_alpha_nominal([[S, S], [S, N], [N, N], [N, N]]) == pytest.approx(1 - 0.25 / (30 / 56))


def test_krippendorff_alpha_ignores_units_with_one_label():
    assert krippendorff_alpha_nominal([[S, S], [N, N], [X]]) == 1.0
    assert krippendorff_alpha_nominal([[S]]) is None


def test_majority_gold_prefers_adjudication_and_reports_ties():
    a, b, c = ("J", "r", "R1"), ("J", "r", "R2"), ("J", "r", "R3")
    raters = {"x": {a: S, b: S, c: N}, "y": {a: S, b: N, c: N}}
    gold, unresolved = majority_gold(raters)
    assert gold == {a: S, c: N} and unresolved == [b]
    gold, unresolved = majority_gold(raters, {b: N})
    assert gold[b] == N and unresolved == []
    assert disagreements(raters) == [(b, {"x": S, "y": N})]


def test_compare_counts_costly_mistakes():
    items = [("J", "r", f"R{i}") for i in range(4)]
    gold = dict(zip(items, [S, S, X, X], strict=True))
    predicted = dict(zip(items, [S, X, S, X], strict=True))
    result = compare(gold, predicted)
    assert result["accuracy"] == 0.5
    assert result["missed_evidence_rate"] == 0.5
    assert result["false_support_rate"] == 0.5
    assert result["confusion"][S][X] == 1


def test_dataset_is_complete_and_designer_labels_cover_every_item():
    rows = list(evaluate.cases())
    assert len(rows) == 12
    expected = {(job["id"], resume_id, r["id"]) for job, resume_id, _, reqs in rows for r in reqs}
    assert set(evaluate.read_labels(evaluate.DATA / "designer_intent.csv")) == expected


def test_score_runs_end_to_end(tmp_path, capsys):
    labels = evaluate.read_labels(evaluate.DATA / "designer_intent.csv")
    run = {"created": "t", "models": ["fake"], "errors": [], "items": [
        {"job_id": j, "resume_id": r, "requirement_id": q, "state": s} for (j, r, q), s in labels.items()
    ]}
    predictions = tmp_path / "run.json"
    predictions.write_text(json.dumps(run))
    rater_dir = tmp_path / "labels"
    rater_dir.mkdir()
    for name in ("ab", "cd"):
        (rater_dir / f"{name}.csv").write_bytes((evaluate.DATA / "designer_intent.csv").read_bytes())
    evaluate.score(predictions, labels_dir=rater_dir)
    out = capsys.readouterr().out
    assert "Krippendorff's alpha (raters): 1.00" in out
    assert "Accuracy: 1.00" in out


def test_invalid_state_is_rejected(tmp_path):
    sheet = tmp_path / "x.csv"
    sheet.write_text("job_id,resume_id,requirement_id,state\nJ1,r01,R1,maybe\n")
    with pytest.raises(SystemExit, match="state must be one of"):
        evaluate.read_labels(sheet)
