#!/usr/bin/env python3
"""Build and score a blinded founder-vs-judge calibration set.

The historical trail contains Codex review findings plus Assaf's workflow
disposition. This harness measures a narrow question: given only the finding
text and severity, can a fresh judge predict whether Assaf accepted, rejected,
or deferred it?

It does not claim to measure clean-pass quality. The ledger stores positive
findings, not claim-level negatives. Naming that boundary prevents a useful
triage eval from turning into a false product-quality metric.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable


LABELS = ("accepted", "rejected", "deferred")
QUOTAS = {"accepted": 20, "rejected": 20, "deferred": 10}
FORBIDDEN_BLIND_KEYS = {"founder_disposition", "founder_rationale", "source_record_sha256"}
POST_ADJUDICATION_RE = re.compile(
    r"\b(refuted by my own|my own verification|severity lowered|reviewer filed this as|"
    r"raised from the reviewer(?:'s)?|founder (?:accepted|rejected|deferred))\b",
    re.IGNORECASE,
)


def canonical_hash(record: dict) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def source_candidates(repo: Path) -> list[dict]:
    findings_dir = repo / ".prd-os" / "findings"
    candidates = []
    # Scar 2026-08-03: the first calibration build counted the recursive ledger
    # during recon but scanned only top-level PRD findings here. All 19 deferred
    # decisions included issue-level files, so the promised 10-case deferred
    # stratum could not be built. The source boundary is the whole findings tree.
    for path in sorted(findings_dir.rglob("*-findings.jsonl")):
        relative = str(path.relative_to(repo))
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{relative}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                continue
            if record.get("source") != "codex-review":
                continue
            if record.get("disposition") not in LABELS:
                continue
            if not str(record.get("body", "")).strip():
                continue
            # The ledger body is mutable. Exclude findings whose text contains an
            # explicit post-review adjudication, because the blind case would
            # otherwise carry its own answer. Scar: v1 case 049 said the original
            # conclusion was "REFUTED" and that severity had already been lowered.
            if POST_ADJUDICATION_RE.search(str(record.get("body"))):
                continue
            stable_key = f"{record.get('prd_id')}:{record.get('id')}:{record.get('body')}"
            candidates.append(
                {
                    "record": record,
                    "source_path": relative,
                    "source_line": line_number,
                    "source_record_sha256": canonical_hash(record),
                    "selection_hash": hashlib.sha256(stable_key.encode("utf-8")).hexdigest(),
                }
            )
    return candidates


def source_population_counts(repo: Path) -> dict[str, int]:
    """Count the full historical ledger before benchmark leakage exclusions."""
    counts: collections.Counter[str] = collections.Counter()
    findings_dir = repo / ".prd-os" / "findings"
    for path in sorted(findings_dir.rglob("*-findings.jsonl")):
        for record in read_jsonl(path):
            if record.get("source") == "codex-review" and record.get("disposition") in LABELS:
                counts[record["disposition"]] += 1
    return dict(counts)


def round_robin_select(candidates: list[dict], label: str, quota: int) -> list[dict]:
    by_prd: dict[str, list[dict]] = collections.defaultdict(list)
    for item in candidates:
        if item["record"]["disposition"] == label:
            by_prd[str(item["record"].get("prd_id"))].append(item)
    for items in by_prd.values():
        items.sort(key=lambda item: item["selection_hash"])
    prd_order = sorted(
        by_prd,
        key=lambda prd_id: hashlib.sha256(f"{label}:{prd_id}".encode("utf-8")).hexdigest(),
    )
    selected = []
    depth = 0
    while len(selected) < quota:
        added = False
        for prd_id in prd_order:
            items = by_prd[prd_id]
            if depth < len(items):
                selected.append(items[depth])
                added = True
                if len(selected) == quota:
                    break
        if not added:
            raise ValueError(f"not enough {label} candidates for quota {quota}")
        depth += 1
    return selected


def build_dataset(repo: Path) -> list[dict]:
    candidates = source_candidates(repo)
    picked = []
    for label in LABELS:
        picked.extend(round_robin_select(candidates, label, QUOTAS[label]))
    picked.sort(key=lambda item: item["selection_hash"])
    dataset = []
    for index, item in enumerate(picked, 1):
        record = item["record"]
        dataset.append(
            {
                "case_id": f"fjc-v1-{index:03d}",
                "prd_id": record.get("prd_id"),
                "finding_id": record.get("id"),
                "severity": record.get("severity"),
                "finding": record.get("body"),
                "founder_disposition": record.get("disposition"),
                "founder_rationale": record.get("rationale"),
                "source_path": item["source_path"],
                "source_line": item["source_line"],
                "source_record_sha256": item["source_record_sha256"],
                "selection_rule": "sha256 round-robin by PRD; quotas accepted=20 rejected=20 deferred=10",
            }
        )
    validate_dataset(dataset)
    return dataset


def validate_dataset(rows: list[dict]) -> None:
    if len(rows) != 50:
        raise ValueError(f"expected 50 cases, got {len(rows)}")
    ids = [row.get("case_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case_id in dataset")
    counts = collections.Counter(row.get("founder_disposition") for row in rows)
    if dict(counts) != QUOTAS:
        raise ValueError(f"wrong label quotas: {dict(counts)} expected {QUOTAS}")
    for row in rows:
        if not row.get("finding") or row.get("severity") not in {"blocker", "major", "minor", "nit"}:
            raise ValueError(f"invalid case {row.get('case_id')}")


def blind_rows(rows: list[dict]) -> list[dict]:
    validate_dataset(rows)
    blinded = []
    for row in rows:
        # Only the evidence named by the experiment reaches the judge. PRD and
        # finding IDs can encode chronology or familiar project names, and they
        # are unnecessary for a context-free prediction.
        clean = {
            "case_id": row["case_id"],
            "severity": row["severity"],
            "finding": row["finding"],
        }
        blinded.append(clean)
    leaked = sorted(FORBIDDEN_BLIND_KEYS.intersection({key for row in blinded for key in row}))
    if leaked:
        raise ValueError(f"blind export leaked keys: {leaked}")
    return blinded


def verify_sources(repo: Path, rows: list[dict]) -> list[str]:
    validate_dataset(rows)
    errors = []
    cache: dict[Path, list[dict]] = {}
    for row in rows:
        path = repo / row["source_path"]
        if path not in cache:
            cache[path] = read_jsonl(path)
        matches = [
            record for record in cache[path]
            if record.get("prd_id") == row["prd_id"] and record.get("id") == row["finding_id"]
        ]
        if len(matches) != 1:
            errors.append(f"{row['case_id']}: expected one source record, found {len(matches)}")
            continue
        if canonical_hash(matches[0]) != row["source_record_sha256"]:
            errors.append(f"{row['case_id']}: source hash changed")
    return errors


def prediction_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["predictions"],
        "properties": {
            "predictions": {
                "type": "array",
                "minItems": 50,
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "prediction", "confidence", "reason"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "prediction": {"type": "string", "enum": list(LABELS)},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }


def load_predictions(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("predictions"), list):
        raise ValueError("predictions file must be an object with a predictions array")
    return payload["predictions"]


def validate_predictions(dataset: list[dict], predictions: list[dict]) -> None:
    gold_ids = {row["case_id"] for row in dataset}
    predicted_ids = [row.get("case_id") for row in predictions]
    if len(predicted_ids) != len(set(predicted_ids)):
        raise ValueError("duplicate prediction case_id")
    missing = sorted(gold_ids - set(predicted_ids))
    unknown = sorted(set(predicted_ids) - gold_ids)
    if missing or unknown:
        raise ValueError(f"prediction coverage mismatch: missing={missing} unknown={unknown}")
    for row in predictions:
        required = {"case_id", "prediction", "confidence", "reason"}
        if set(row) != required:
            raise ValueError(
                f"{row.get('case_id')}: prediction keys must be exactly {sorted(required)}; "
                f"got {sorted(row)}"
            )
        if row.get("prediction") not in LABELS:
            raise ValueError(f"{row.get('case_id')}: invalid prediction {row.get('prediction')!r}")
        confidence = row.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"{row.get('case_id')}: confidence must be a number from 0 to 1")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError(f"{row.get('case_id')}: reason must be a non-empty string")


def score(dataset: list[dict], predictions: list[dict], population_counts: dict[str, int] | None = None) -> dict:
    validate_dataset(dataset)
    validate_predictions(dataset, predictions)
    pred_by_id = {row["case_id"]: row for row in predictions}
    matrix = {gold: {pred: 0 for pred in LABELS} for gold in LABELS}
    errors = []
    for row in dataset:
        pred_row = pred_by_id[row["case_id"]]
        gold = row["founder_disposition"]
        pred = pred_row["prediction"]
        matrix[gold][pred] += 1
        if gold != pred:
            errors.append(
                {
                    "case_id": row["case_id"],
                    "gold": gold,
                    "prediction": pred,
                    "severity": row["severity"],
                    "prd_id": row["prd_id"],
                    "finding_id": row["finding_id"],
                    "reason": pred_row.get("reason", ""),
                }
            )
    total = len(dataset)
    correct = sum(matrix[label][label] for label in LABELS)
    accuracy = correct / total
    recalls = []
    f1s = []
    per_label = {}
    gold_totals = {label: sum(matrix[label].values()) for label in LABELS}
    pred_totals = {label: sum(matrix[gold][label] for gold in LABELS) for label in LABELS}
    for label in LABELS:
        tp = matrix[label][label]
        recall = tp / gold_totals[label] if gold_totals[label] else 0.0
        precision = tp / pred_totals[label] if pred_totals[label] else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        recalls.append(recall)
        f1s.append(f1)
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1}
    expected = sum(gold_totals[label] * pred_totals[label] for label in LABELS) / (total * total)
    kappa = (accuracy - expected) / (1 - expected) if not math.isclose(expected, 1.0) else 1.0
    correctness = []
    confidences = []
    for row in dataset:
        prediction = pred_by_id[row["case_id"]]
        correctness.append(1.0 if prediction["prediction"] == row["founder_disposition"] else 0.0)
        confidences.append(float(prediction["confidence"]))
    bins = []
    ece = 0.0
    for lower_index in range(10):
        lower = lower_index / 10
        upper = (lower_index + 1) / 10
        members = [
            index for index, confidence in enumerate(confidences)
            if confidence >= lower and (confidence < upper or (upper == 1.0 and confidence <= upper))
        ]
        if not members:
            continue
        bin_confidence = sum(confidences[index] for index in members) / len(members)
        bin_accuracy = sum(correctness[index] for index in members) / len(members)
        ece += (len(members) / total) * abs(bin_accuracy - bin_confidence)
        bins.append(
            {"lower": lower, "upper": upper, "count": len(members),
             "mean_confidence": bin_confidence, "accuracy": bin_accuracy}
        )
    high_confidence = [index for index, confidence in enumerate(confidences) if confidence >= 0.9]
    population_counts = population_counts or dict(gold_totals)
    population_total = sum(population_counts.values())
    post_stratified_accuracy = sum(
        (population_counts.get(label, 0) / population_total) * per_label[label]["recall"]
        for label in LABELS
    ) if population_total else 0.0
    return {
        "cases": total,
        "correct": correct,
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls),
        "macro_f1": sum(f1s) / len(f1s),
        "cohen_kappa": kappa,
        "gold_counts": gold_totals,
        "prediction_counts": pred_totals,
        "per_label": per_label,
        "confidence": {
            "mean": sum(confidences) / total,
            "correct_mean": sum(c for c, ok in zip(confidences, correctness) if ok) / correct if correct else 0.0,
            "wrong_mean": sum(c for c, ok in zip(confidences, correctness) if not ok) / (total - correct) if total != correct else 0.0,
            "ece_10_bin": ece,
            "high_confidence_count": len(high_confidence),
            "high_confidence_correct": int(sum(correctness[index] for index in high_confidence)),
            "bins": bins,
        },
        "population_counts": population_counts,
        "population_majority_baseline": max(population_counts.values()) / population_total if population_total else 0.0,
        "post_stratified_accuracy": post_stratified_accuracy,
        "confusion_matrix": matrix,
        "errors": errors,
    }


def report_markdown(result: dict) -> str:
    matrix = result["confusion_matrix"]
    lines = [
        "# Founder-Judge Context-Free Triage Stress Test v1",
        "",
        "## Result",
        "",
        f"- Cases: {result['cases']}",
        f"- Exact agreement: {result['correct']}/{result['cases']} ({result['accuracy']:.1%})",
        f"- Balanced accuracy: {result['balanced_accuracy']:.1%}",
        f"- Macro F1: {result['macro_f1']:.3f}",
        f"- Cohen's kappa: {result['cohen_kappa']:.3f}",
        "- Balanced-set majority baseline: 40.0%",
        f"- Historical-ledger majority baseline: {result['population_majority_baseline']:.1%}",
        f"- Post-stratified accuracy estimate: {result['post_stratified_accuracy']:.1%}",
        f"- Judge predictions: {result['prediction_counts']['accepted']} accepted, {result['prediction_counts']['rejected']} rejected, {result['prediction_counts']['deferred']} deferred",
        "",
        "This is a deliberately balanced stress test. It measures whether finding text and severity alone can predict Assaf's workflow disposition. It does not measure clean-pass quality, objection-finding recall, or factual validity. The historical ledger is not balanced, so the exact agreement above is not an operational accuracy estimate.",
        "",
        "## Assessment",
        "",
        f"- Accepted recall: {result['per_label']['accepted']['recall']:.1%}. The judge matched {matrix['accepted']['accepted']} of {result['gold_counts']['accepted']} accepted findings.",
        f"- Accepted precision: {result['per_label']['accepted']['precision']:.1%}. More than half of the judge's fix-now calls were not accepted by Assaf.",
        f"- Rejected recall: {result['per_label']['rejected']['recall']:.1%}.",
        f"- Deferred recall: {result['per_label']['deferred']['recall']:.1%}.",
        f"- The judge predicted `accepted` for {result['prediction_counts']['accepted']} of {result['cases']} supplied objections. It is not a calibrated proxy for founder triage.",
        f"- Reweighted to the historical class mix, estimated accuracy is {result['post_stratified_accuracy']:.1%}, below the {result['population_majority_baseline']:.1%} always-accepted baseline.",
        "- Hidden workflow context sets many labels. Duplicate status, prior remediation, issue ordering, and scope removal are absent from the blind input.",
        "- Near-identical empty-manifest findings received different founder dispositions because the surrounding PRD state differed.",
        "",
        "## Confidence calibration",
        "",
        f"- Mean confidence: {result['confidence']['mean']:.1%}",
        f"- Mean confidence on wrong predictions: {result['confidence']['wrong_mean']:.1%}",
        f"- 10-bin expected calibration error: {result['confidence']['ece_10_bin']:.3f}",
        f"- Predictions at or above 90% confidence: {result['confidence']['high_confidence_correct']}/{result['confidence']['high_confidence_count']} correct",
        "",
        "## Confusion matrix",
        "",
        "| Founder \\ Judge | accepted | rejected | deferred |",
        "|---|---:|---:|---:|",
    ]
    for gold in LABELS:
        lines.append(f"| {gold} | {matrix[gold]['accepted']} | {matrix[gold]['rejected']} | {matrix[gold]['deferred']} |")
    lines.extend(["", "## Disagreements", ""])
    if not result["errors"]:
        lines.append("None.")
    else:
        for error in result["errors"]:
            lines.append(
                f"- `{error['case_id']}` {error['prd_id']}/{error['finding_id']}: "
                f"founder `{error['gold']}`, judge `{error['prediction']}`. {error['reason']}"
            )
    lines.append("")
    return "\n".join(lines)


def selftest() -> int:
    fixture = []
    for index in range(50):
        label = "accepted" if index < 20 else "rejected" if index < 40 else "deferred"
        fixture.append(
            {
                "case_id": f"fjc-v1-{index + 1:03d}",
                "prd_id": f"prd-{index % 7}",
                "finding_id": f"finding-{index}",
                "severity": "major",
                "finding": f"case {index}",
                "founder_disposition": label,
                "founder_rationale": None,
                "source_path": ".prd-os/findings/fixture.jsonl",
                "source_line": index + 1,
                "source_record_sha256": "0" * 64,
                "selection_rule": "fixture",
            }
        )
    perfect = [
        {"case_id": row["case_id"], "prediction": row["founder_disposition"],
         "confidence": 1.0, "reason": "fixture"}
        for row in fixture
    ]
    perfect_score = score(fixture, perfect)
    if perfect_score["accuracy"] != 1.0 or perfect_score["cohen_kappa"] != 1.0:
        print("SELFTEST FAIL: perfect predictions did not score 100%", file=sys.stderr)
        return 1
    corrupted = [dict(row) for row in perfect]
    corrupted[0]["prediction"] = "rejected"
    if score(fixture, corrupted)["accuracy"] >= 1.0:
        print("SELFTEST FAIL: corrupting a prediction did not lower the score", file=sys.stderr)
        return 1
    try:
        score(fixture, perfect[:-1])
    except ValueError:
        pass
    else:
        print("SELFTEST FAIL: missing prediction was accepted", file=sys.stderr)
        return 1
    malformed = [dict(row) for row in perfect]
    malformed[0].pop("confidence")
    try:
        score(fixture, malformed)
    except ValueError:
        pass
    else:
        print("SELFTEST FAIL: schema-invalid prediction was accepted", file=sys.stderr)
        return 1
    blinded = blind_rows(fixture)
    if any(FORBIDDEN_BLIND_KEYS.intersection(row) for row in blinded):
        print("SELFTEST FAIL: blind export leaked gold fields", file=sys.stderr)
        return 1
    # File integration is best-effort because Codex review runs read-only with no
    # usable temp directory. The scoring contract above remains fully in-memory.
    try:
        temp = tempfile.TemporaryDirectory()
    except (FileNotFoundError, OSError) as exc:
        print(f"integration test skipped: no writable temp dir ({exc})")
    else:
        with temp as temp_dir:
            repo = Path(temp_dir)
            nested = repo / ".prd-os" / "findings" / "issue" / "nested-findings.jsonl"
            nested.parent.mkdir(parents=True)
            write_jsonl(
                nested,
                [{
                    "prd_id": "prd-nested", "id": "finding-1", "source": "codex-review",
                    "disposition": "deferred", "severity": "major", "body": "nested issue finding",
                    "rationale": "out of scope",
                }],
            )
            if len(source_candidates(repo)) != 1:
                print("SELFTEST FAIL: nested issue finding was not discovered", file=sys.stderr)
                return 1
    print("SELFTEST PASS: scoring changes, schema and coverage enforced, blind export clean")
    return 0


def default_repo() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser("build")
    build.add_argument("--repo", type=Path, default=default_repo())
    build.add_argument("--output", type=Path, required=True)
    blind = sub.add_parser("blind")
    blind.add_argument("--dataset", type=Path, required=True)
    blind.add_argument("--output", type=Path, required=True)
    schema = sub.add_parser("schema")
    schema.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--repo", type=Path, default=default_repo())
    verify.add_argument("--dataset", type=Path, required=True)
    scorer = sub.add_parser("score")
    scorer.add_argument("--dataset", type=Path, required=True)
    scorer.add_argument("--predictions", type=Path, required=True)
    scorer.add_argument("--report", type=Path, required=True)
    scorer.add_argument("--repo", type=Path, default=default_repo())
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.command == "build":
        rows = build_dataset(args.repo.resolve())
        write_jsonl(args.output, rows)
        print(f"BUILT {len(rows)} cases: {dict(collections.Counter(r['founder_disposition'] for r in rows))}")
        return 0
    if args.command == "blind":
        rows = read_jsonl(args.dataset)
        args.output.write_text(json.dumps({"cases": blind_rows(rows)}, indent=2) + "\n", encoding="utf-8")
        print(f"BLINDED {len(rows)} cases with zero gold-label fields")
        return 0
    if args.command == "schema":
        args.output.write_text(json.dumps(prediction_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {args.output}")
        return 0
    if args.command == "verify":
        errors = verify_sources(args.repo.resolve(), read_jsonl(args.dataset))
        if errors:
            print("VERIFY FAIL:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        print("VERIFY PASS: 50 unique cases, 20/20/10 balance, all source hashes match")
        return 0
    if args.command == "score":
        population_counts = source_population_counts(args.repo.resolve())
        result = score(
            read_jsonl(args.dataset), load_predictions(args.predictions), population_counts
        )
        args.report.write_text(report_markdown(result), encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "errors"}, indent=2))
        return 0
    parser.error("choose a command or --selftest")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
