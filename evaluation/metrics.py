"""Agreement and accuracy metrics for requirement-state labels. Pure Python, no dependencies.

Labels are dicts keyed by item = (job_id, resume_id, requirement_id), valued by state.
"""

from collections import Counter
from typing import Dict, List, Optional, Tuple

STATES = ("supported", "needs_review", "no_evidence")

Item = Tuple[str, str, str]
Labels = Dict[Item, str]


def cohen_kappa(a: List[str], b: List[str]) -> Optional[float]:
    """Agreement between two label sequences beyond what chance would give. None if undefined."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[s] * cb[s] for s in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return (observed - expected) / (1 - expected)


def krippendorff_alpha_nominal(units: List[List[str]]) -> Optional[float]:
    """Krippendorff's alpha for nominal labels. Each unit is the list of labels it received;
    units with fewer than two labels are ignored, so raters may skip rows. None if undefined."""
    coincidences: Counter = Counter()
    for labels in units:
        m = len(labels)
        if m < 2:
            continue
        counts = Counter(labels)
        for c in counts:
            for k in counts:
                pairs = counts[c] * (counts[k] - (1 if c == k else 0))
                if pairs:
                    coincidences[(c, k)] += pairs / (m - 1)
    n = sum(coincidences.values())
    if n <= 1:
        return None
    totals: Counter = Counter()
    for (c, _), v in coincidences.items():
        totals[c] += v
    observed_disagreement = sum(v for (c, k), v in coincidences.items() if c != k) / n
    expected_disagreement = sum(totals[c] * totals[k] for c in totals for k in totals if c != k) / (n * (n - 1))
    if expected_disagreement == 0:
        return 1.0 if observed_disagreement == 0 else None
    return 1 - observed_disagreement / expected_disagreement


def majority_gold(raters: Dict[str, Labels], adjudicated: Optional[Labels] = None) -> Tuple[Labels, List[Item]]:
    """Gold label per item: the adjudicated label if present, else a strict majority of raters.
    Returns (gold, unresolved items) where unresolved items are ties waiting for adjudication."""
    adjudicated = adjudicated or {}
    items = set(adjudicated)
    for labels in raters.values():
        items |= set(labels)
    gold, unresolved = {}, []
    for item in sorted(items):
        if item in adjudicated:
            gold[item] = adjudicated[item]
            continue
        votes = Counter(labels[item] for labels in raters.values() if item in labels)
        (top, top_count), *rest = votes.most_common()
        if rest and rest[0][1] == top_count:
            unresolved.append(item)
        else:
            gold[item] = top
    return gold, unresolved


def disagreements(raters: Dict[str, Labels]) -> List[Tuple[Item, Dict[str, str]]]:
    items = sorted(set().union(*(set(labels) for labels in raters.values()))) if raters else []
    out = []
    for item in items:
        given = {name: labels[item] for name, labels in raters.items() if item in labels}
        if len(set(given.values())) > 1:
            out.append((item, given))
    return out


def compare(gold: Labels, predicted: Labels) -> dict:
    """System vs gold on the items both have."""
    items = sorted(set(gold) & set(predicted))
    g = [gold[i] for i in items]
    p = [predicted[i] for i in items]
    confusion = {gs: {ps: 0 for ps in STATES} for gs in STATES}
    for gs, ps in zip(g, p, strict=True):
        confusion[gs][ps] += 1
    per_state = {}
    for s in STATES:
        tp = confusion[s][s]
        predicted_s = sum(confusion[gs][s] for gs in STATES)
        gold_s = sum(confusion[s].values())
        per_state[s] = {
            "precision": tp / predicted_s if predicted_s else None,
            "recall": tp / gold_s if gold_s else None,
            "gold_count": gold_s,
        }
    supported_gold = sum(confusion["supported"].values())
    no_evidence_gold = sum(confusion["no_evidence"].values())
    return {
        "items": len(items),
        "missing_predictions": len(set(gold) - set(predicted)),
        "accuracy": sum(x == y for x, y in zip(g, p, strict=True)) / len(items) if items else None,
        "kappa": cohen_kappa(g, p),
        "confusion": confusion,
        "per_state": per_state,
        # The costly mistakes: hiding real evidence, and claiming evidence that is not there.
        "missed_evidence_rate": confusion["supported"]["no_evidence"] / supported_gold if supported_gold else None,
        "false_support_rate": confusion["no_evidence"]["supported"] / no_evidence_gold if no_evidence_gold else None,
    }
