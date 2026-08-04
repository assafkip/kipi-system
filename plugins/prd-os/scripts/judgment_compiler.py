#!/usr/bin/env python3
"""Judgment Compiler: append-only decision receipts for PRD finding triage.

PRD: q-system/output/prd-judgment-compiler-2026-08-04.md (ASK-363).
Paired tests: plugins/prd-os/tests/test_judgment_compiler.py.

Why this exists (verified v1 benchmark, founder-judge-calibration-v1): finding
text + severity alone predict the founder's triage disposition at 40% exact
agreement, kappa 0.032, worse than the 76.6% accept-all baseline. A disposition
is not a property of an objection; it is a property of an objection inside
workflow state. The findings ledger mutates records in place, so decision-time
state is destroyed the moment state moves on. This module freezes it.

Design constraints (each anchored to a scar):
  - Ledger lives under the shared worktree root via prd_runner._ledger_root,
    never cfg.repo_root (sp-bc42f1d3: 26 private worktree ledgers hid 71 open
    findings from the gate that existed to see them).
  - Receipts are append-only and hash-chained. Corrections append a superseding
    receipt; nothing rewrites history (v1 scar: case 049's mutable body carried
    its own adjudication into a "blind" benchmark).
  - Missing evidence stays "unknown", never false (v1 scar: absent workflow
    context silently became a property of the finding text).
  - The self-test is fully in-memory (rca-founder-judge-calibration RCA: the
    first benchmark's selftest died in Codex's read-only sandbox on a
    tempfile call).
  - This module contains NO code path that installs policy: promotion of a
    policy candidate goes through the human-reviewed prd-os flow. A grep test
    in the paired test file holds that line.

Subcommands:
  assemble           build a deterministic decision-context packet
  capture            validate + append one triage episode receipt
  verify             re-walk the chain; also --packet/--receipt-id binding
  evaluate           score prospective judge-vs-human cases (read-only)
  sample-check       deterministic 5% sampling verdict for a basis hash
  policy-candidates  detect repeated override patterns, append proposals
  --selftest         in-memory contract proof (read-only safe)

Exit codes: 0 success, 2 validation error (matches findings_writer contract).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config import Config, ConfigError, load as load_config  # noqa: E402

RECEIPT_SCHEMA_VERSION = 1
PACKET_SCHEMA_VERSION = 1
LEDGER_NAME = "judgments.jsonl"
CANDIDATES_NAME = "judgment-policy-candidates.jsonl"

SAMPLE_SALT = "kipi-judgment-sample-v1"
SAMPLE_MODULUS = 10000
SAMPLE_THRESHOLD = 500  # 5%
SAMPLE_RULE = f"int(sha256('{SAMPLE_SALT}:' + basis_sha256), 16) % {SAMPLE_MODULUS} < {SAMPLE_THRESHOLD}"

LEGACY_DISPOSITIONS = ("pending", "accepted", "rejected", "deferred")
TECHNICAL_VALIDITY = ("valid", "invalid", "uncertain")
WORKFLOW_DISPOSITIONS = (
    "fix-now", "already-remediated", "duplicate", "scope-removed",
    "out-of-scope", "defer", "invalid", "needs-human",
)
REASON_CODES = (
    "valid-fix-now", "already-remediated", "duplicate", "owned-by-other-prd",
    "scope-removed", "out-of-scope", "superseded", "defer-dependency",
    "defer-ordering", "invalid-finding", "insufficient-context", "needs-human",
)
JUDGE_OUTPUT_FIELDS = (
    "technical_validity", "technical_reason", "workflow_disposition",
    "workflow_reason_code", "evidence_refs", "missing_context", "confidence",
)
# Reason codes / workflow dispositions that must not pass without a stable
# reference (PRD Change 4). Value = tuple of required ref prefixes; every
# listed prefix must be present at least once.
EVIDENCE_REQUIREMENTS = {
    "duplicate": (("finding:", "issue:", "spillover:"),),
    "already-remediated": (("receipt:", "commit:", "test:"),),
    "owned-by-other-prd": (("prd:",), ("issue:",)),
    "scope-removed": (("scope:",),),
    "out-of-scope": (("scope:",),),
    "superseded": (("judgment:",),),
}
EVIDENCE_REF_RE = re.compile(
    r"^(finding|issue|prd|receipt|judgment|commit|test|scope|spillover):\S+$"
)
JUDGE_TO_LEGACY = {
    "fix-now": "accepted",
    "already-remediated": "rejected",
    "duplicate": "rejected",
    "scope-removed": "rejected",
    "out-of-scope": "rejected",
    "invalid": "rejected",
    "defer": "deferred",
    "needs-human": None,  # excluded from automation metrics
}

RECEIPT_FIELDS = frozenset((
    "schema_version", "receipt_id", "sequence", "captured_at", "finding",
    "review", "repo_state", "prd_state", "issue_state", "scope", "duplicates",
    "remediation", "related_prds", "prior_receipts", "missing_context",
    "judge", "human", "sampling", "supersedes", "prev_receipt_sha256",
))
TIP_NAME = "judgments-tip.json"
TIP_FIELDS = frozenset(("count", "last_receipt_sha256", "last_receipt_id",
                        "updated_at"))
PACKET_FIELDS = frozenset((
    "packet_schema_version", "assembled_at", "packet_sha256", "finding",
    "review", "repo_state", "prd_state", "issue_state", "scope", "duplicates",
    "remediation", "related_prds", "prior_receipts", "missing_context",
))
CANDIDATE_FIELDS = frozenset((
    "candidate_id", "status", "created_at", "pattern",
    "supporting_receipt_ids", "case_count", "counterexamples",
    "counterexample_search", "proposed_rule", "proposed_tests",
    "false_positive_risk", "integration_point",
))


class ValidationError(ValueError):
    """A contract violation. Caller converts to exit 2."""


# ---------------------------------------------------------------------------
# Canonical hashing (pinned by the paired tests from the other side)
# ---------------------------------------------------------------------------


def canonical_hash(record: dict) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def packet_hash(packet: dict) -> str:
    body = {k: v for k, v in packet.items()
            if k not in ("packet_sha256", "assembled_at")}
    return canonical_hash(body)


def receipt_content_id(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "receipt_id"}
    return "jr-" + canonical_hash(body)[:16]


def sample_decision(basis_sha256: str) -> bool:
    digest = hashlib.sha256(f"{SAMPLE_SALT}:{basis_sha256}".encode()).hexdigest()
    return int(digest, 16) % SAMPLE_MODULUS < SAMPLE_THRESHOLD


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Ledger paths (shared across worktrees; see module docstring)
# ---------------------------------------------------------------------------


def _ledger_dir(cfg: Config) -> Path:
    from prd_runner import _ledger_root  # sibling; one definition of the root

    return _ledger_root(cfg.repo_root) / ".prd-os"


def ledger_path(cfg: Config) -> Path:
    return _ledger_dir(cfg) / LEDGER_NAME


def candidates_path(cfg: Config) -> Path:
    return _ledger_dir(cfg) / CANDIDATES_NAME


def tip_path(cfg: Config) -> Path:
    return _ledger_dir(cfg) / TIP_NAME


def read_tip(path: Path) -> dict | None:
    """The tip anchor: how long the chain is and what its last line hashes to.

    WHY THIS EXISTS (self-attack 2026-08-04, before this file ever shipped):
    a prev-hash chain proves each retained line follows the one before it. It
    cannot prove the chain is COMPLETE, because any prefix of a valid chain is
    itself a valid chain. Truncating the tail (or deleting the whole ledger)
    passed `verify` cleanly. Reproduced: 2 receipts -> VERIFY PASS; `head -1`
    the file -> still VERIFY PASS. The anchor closes deletion, the one
    tamper class the chain structurally cannot see.

    HONEST BOUNDARY: the anchor is written by the same process that writes the
    ledger, so an attacker who can edit one can edit the other. This is
    tamper-EVIDENT (accidental truncation, a crashed write, a partial sync,
    a naive edit), not tamper-PROOF. For an independent check use
    `verify --cross-check`, which reads the findings ledgers instead.
    """
    if not path.is_file():
        return None
    try:
        tip = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValidationError(f"{path}: unreadable tip anchor: {exc}") from exc
    if not isinstance(tip, dict):
        raise ValidationError(f"{path}: tip anchor must be an object")
    _require_keys(tip, TIP_FIELDS, str(path))
    if not isinstance(tip["count"], int) or isinstance(tip["count"], bool) \
            or tip["count"] < 0:
        raise ValidationError(f"{path}: tip count must be a non-negative int")
    return tip


def write_tip(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(records),
        "last_receipt_sha256": canonical_hash(records[-1]) if records else None,
        "last_receipt_id": records[-1]["receipt_id"] if records else None,
        "updated_at": _now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def read_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise ValidationError(f"{path}:{line_number}: expected an object")
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Field validators (small and boring on purpose)
# ---------------------------------------------------------------------------


def _require_keys(obj: dict, allowed: frozenset, where: str) -> None:
    extra = sorted(set(obj) - allowed)
    missing = sorted(allowed - set(obj))
    if extra:
        raise ValidationError(f"{where}: unknown fields {extra}")
    if missing:
        raise ValidationError(f"{where}: missing fields {missing}")


def _require_str_or_unknown(value, where: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValidationError(
            f"{where}: must be a non-empty string (use 'unknown' for missing "
            f"evidence, never false/null); got {value!r}")


def _validate_confidence(value, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where}: confidence must be a number, got {value!r}")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValidationError(
            f"{where}: confidence must be finite and within [0, 1], got {value!r}")


def _validate_evidence_refs(refs, where: str) -> None:
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise ValidationError(f"{where}: evidence_refs must be a list of strings")
    for ref in refs:
        if not EVIDENCE_REF_RE.match(ref):
            raise ValidationError(
                f"{where}: evidence ref {ref!r} does not match the stable "
                "reference grammar prefix:value")


def evidence_gate_errors(reason_code: str | None, disposition: str | None,
                         refs: list[str]) -> list[str]:
    """Which required reference prefixes are missing for this decision."""
    requirements: list[tuple[str, ...]] = []
    for key in (reason_code, disposition):
        for group in EVIDENCE_REQUIREMENTS.get(key or "", ()):  # type: ignore[arg-type]
            if group not in requirements:
                requirements.append(group)
    errors = []
    for group in requirements:
        if not any(ref.startswith(prefix) for prefix in group for ref in refs):
            errors.append(
                f"disposition/reason {reason_code or disposition!r} requires an "
                f"evidence ref with prefix in {sorted(group)}")
    return errors


def validate_judge_output(output: dict, where: str) -> None:
    if not isinstance(output, dict):
        raise ValidationError(f"{where}: judge output must be an object")
    extra = sorted(set(output) - set(JUDGE_OUTPUT_FIELDS))
    if extra:
        raise ValidationError(f"{where}: unexpected judge output fields {extra}")
    missing = sorted(set(JUDGE_OUTPUT_FIELDS) - set(output))
    if missing:
        raise ValidationError(f"{where}: missing judge output fields {missing}")
    if output["technical_validity"] not in TECHNICAL_VALIDITY:
        raise ValidationError(
            f"{where}: technical_validity must be one of {TECHNICAL_VALIDITY}")
    if output["workflow_disposition"] not in WORKFLOW_DISPOSITIONS:
        raise ValidationError(
            f"{where}: workflow_disposition must be one of {WORKFLOW_DISPOSITIONS}")
    if output["workflow_reason_code"] not in REASON_CODES:
        raise ValidationError(
            f"{where}: workflow_reason_code must be one of the canonical "
            f"reason codes; got {output['workflow_reason_code']!r}")
    if not isinstance(output["technical_reason"], str):
        raise ValidationError(f"{where}: technical_reason must be a string")
    _validate_evidence_refs(output["evidence_refs"], where)
    if not isinstance(output["missing_context"], list) or not all(
            isinstance(m, str) for m in output["missing_context"]):
        raise ValidationError(f"{where}: missing_context must be a list of strings")
    _validate_confidence(output["confidence"], where)


def validate_packet(packet: dict, where: str = "packet") -> None:
    if not isinstance(packet, dict):
        raise ValidationError(f"{where}: must be an object")
    _require_keys(packet, PACKET_FIELDS, where)
    if packet["packet_schema_version"] != PACKET_SCHEMA_VERSION:
        raise ValidationError(f"{where}: unsupported packet_schema_version")
    if packet_hash(packet) != packet["packet_sha256"]:
        raise ValidationError(f"{where}: packet_sha256 does not match content")
    _validate_state_groups(packet, where)


def _validate_state_groups(container: dict, where: str) -> None:
    """Shared shape checks for the context groups in packets and receipts."""
    finding = container["finding"]
    _require_keys(finding, frozenset(
        ("prd_id", "finding_id", "severity", "body", "body_sha256")),
        f"{where}.finding")
    if _sha256_text(finding["body"]) != finding["body_sha256"]:
        raise ValidationError(f"{where}.finding: body_sha256 mismatch")
    repo_state = container["repo_state"]
    _require_keys(repo_state, frozenset(("branch", "commit_sha", "dirty")),
                  f"{where}.repo_state")
    for key in ("branch", "commit_sha"):
        _require_str_or_unknown(repo_state[key], f"{where}.repo_state.{key}")
    if repo_state["dirty"] not in ("true", "false", "unknown"):
        raise ValidationError(
            f"{where}.repo_state.dirty: must be 'true'/'false'/'unknown' "
            f"(strings — missing evidence stays unknown, never a fabricated "
            f"boolean); got {repo_state['dirty']!r}")
    _require_keys(container["prd_state"], frozenset(
        ("path", "sha256", "status", "revision")), f"{where}.prd_state")
    _require_keys(container["issue_state"], frozenset(
        ("issue_id", "manifest_sha256", "issue_order")), f"{where}.issue_state")
    if not isinstance(container["issue_state"]["issue_order"], list):
        raise ValidationError(f"{where}.issue_state.issue_order: must be a list")
    _require_keys(container["scope"], frozenset(("source", "sha256")),
                  f"{where}.scope")
    for name in ("duplicates", "remediation", "related_prds", "prior_receipts",
                 "missing_context"):
        if not isinstance(container[name], list):
            raise ValidationError(f"{where}.{name}: must be a list")


def validate_receipt(record: dict, where: str) -> None:
    _require_keys(record, RECEIPT_FIELDS, where)
    if record["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise ValidationError(f"{where}: unsupported schema_version")
    sequence = record["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValidationError(f"{where}: sequence must be a positive integer")
    if receipt_content_id(record) != record["receipt_id"]:
        raise ValidationError(
            f"{where}: receipt_id does not match record content (mutated "
            "receipt or forged id)")
    _validate_state_groups(record, where)
    _validate_review(record["review"], where)
    _validate_sampling(record["sampling"], where)
    _validate_judge_block(record["judge"], where)
    _validate_human_block(record["human"], where)
    supersedes = record["supersedes"]
    if supersedes is not None and not isinstance(supersedes, str):
        raise ValidationError(f"{where}: supersedes must be a receipt id or null")
    prev = record["prev_receipt_sha256"]
    if prev is not None and (not isinstance(prev, str) or len(prev) != 64):
        raise ValidationError(f"{where}: prev_receipt_sha256 must be sha256 or null")


def _validate_review(review: dict, where: str) -> None:
    _require_keys(review, frozenset(("source", "review_run_id")), f"{where}.review")


def _validate_sampling(sampling: dict, where: str) -> None:
    _require_keys(sampling, frozenset(
        ("basis_sha256", "rule", "salt", "sampled")), f"{where}.sampling")
    if not isinstance(sampling["sampled"], bool):
        raise ValidationError(f"{where}.sampling.sampled: must be a boolean")
    if sampling["rule"] != SAMPLE_RULE or sampling["salt"] != SAMPLE_SALT:
        raise ValidationError(f"{where}.sampling: rule/salt drifted from contract")
    if sample_decision(sampling["basis_sha256"]) != sampling["sampled"]:
        raise ValidationError(
            f"{where}.sampling: recorded verdict does not reproduce from the rule")


def _validate_judge_block(judge, where: str) -> None:
    if judge is None:
        return
    _require_keys(judge, frozenset(
        ("model", "prompt_sha256", "review_run_id", "input_sha256",
         "output_sha256", "output", "converted_to_needs_human",
         "converted_from")), f"{where}.judge")
    validate_judge_output(judge["output"], f"{where}.judge.output")
    if not isinstance(judge["converted_to_needs_human"], bool):
        raise ValidationError(f"{where}.judge.converted_to_needs_human: bool required")


def _validate_human_block(human, where: str) -> None:
    if human is None:
        return
    _require_keys(human, frozenset(
        ("actor", "decided_at", "disposition", "reason_code", "evidence_refs",
         "rationale")), f"{where}.human")
    if human["disposition"] not in LEGACY_DISPOSITIONS:
        raise ValidationError(f"{where}.human.disposition: unknown disposition")
    code = human["reason_code"]
    if code is not None and code not in REASON_CODES:
        raise ValidationError(
            f"{where}.human.reason_code: must be one of the canonical reason "
            f"codes or null; got {code!r}")
    _validate_evidence_refs(human["evidence_refs"], f"{where}.human")
    gate = evidence_gate_errors(code, None, human["evidence_refs"])
    if gate:
        raise ValidationError(f"{where}.human: " + "; ".join(gate))


def validate_candidate(record: dict, where: str) -> None:
    _require_keys(record, CANDIDATE_FIELDS, where)
    if record["status"] != "proposed":
        raise ValidationError(
            f"{where}: candidate status must stay 'proposed' in this ledger; "
            "promotion happens in the human-reviewed prd-os flow")
    if not isinstance(record["counterexample_search"], str) or \
            not record["counterexample_search"].strip():
        raise ValidationError(
            f"{where}: counterexample_search is required — a candidate without "
            "a recorded counterexample search is an unsupported pattern claim")
    if not isinstance(record["counterexamples"], list):
        raise ValidationError(f"{where}: counterexamples must be a list")
    if not isinstance(record["supporting_receipt_ids"], list) or \
            not record["supporting_receipt_ids"]:
        raise ValidationError(f"{where}: supporting_receipt_ids required")


# ---------------------------------------------------------------------------
# Context assembly (deterministic; unknown stays unknown)
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo_root),
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _assemble_repo_state(repo_root: Path, missing: list[str]) -> dict:
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git(repo_root, "rev-parse", "HEAD")
    porcelain = _git(repo_root, "status", "--porcelain")
    state = {
        "branch": branch or "unknown",
        "commit_sha": commit or "unknown",
        "dirty": "unknown" if porcelain is None else
                 ("true" if porcelain else "false"),
    }
    for key in ("branch", "commit_sha", "dirty"):
        if state[key] == "unknown":
            missing.append(f"repo_state.{key}")
    return state


def _prd_spec_path(cfg: Config, prd_id: str) -> Path:
    return cfg.prds_dir / f"{prd_id}.md"


def _assemble_prd_state(cfg: Config, prd_id: str, missing: list[str]) -> dict:
    path = _prd_spec_path(cfg, prd_id)
    rel = os.path.relpath(path, cfg.repo_root)
    if not path.is_file():
        missing.extend(["prd_state.sha256", "prd_state.status",
                        "prd_state.revision"])
        return {"path": rel, "sha256": "unknown", "status": "unknown",
                "revision": "unknown"}
    text = path.read_text(encoding="utf-8")
    status_match = re.search(r"(?m)^status:\s*(\S+)", text)
    revision = _git(cfg.repo_root, "log", "-1", "--format=%H", "--", rel)
    if not revision:
        missing.append("prd_state.revision")
    if not status_match:
        missing.append("prd_state.status")
    return {
        "path": rel,
        "sha256": _sha256_text(text),
        "status": status_match.group(1) if status_match else "unknown",
        "revision": revision or "unknown",
    }


def _assemble_issue_state(cfg: Config, prd_id: str, missing: list[str]) -> dict:
    path = _prd_spec_path(cfg, prd_id)
    issue_id = None
    state_path = cfg.active_issue_state_path
    if state_path.is_file():
        try:
            issue_id = json.loads(state_path.read_text()).get("issue_id")
        except (json.JSONDecodeError, OSError):
            issue_id = None
    if not path.is_file():
        missing.append("issue_state.manifest")
        return {"issue_id": issue_id, "manifest_sha256": "unknown",
                "issue_order": []}
    try:
        import prd_split  # sibling: the one parser of the Issues manifest

        text = path.read_text(encoding="utf-8")
        body_start = text.find("---", 3)
        raw = prd_split._extract_issues_block(text[body_start:])
        entries = json.loads(raw)
        order = [entry.get("id") for entry in entries
                 if isinstance(entry, dict) and entry.get("id")]
        return {"issue_id": issue_id, "manifest_sha256": _sha256_text(raw),
                "issue_order": order}
    except (ValueError, OSError, ImportError):
        missing.append("issue_state.manifest")
        return {"issue_id": issue_id, "manifest_sha256": "unknown",
                "issue_order": []}


def _assemble_scope(cfg: Config, prd_id: str, missing: list[str]) -> dict:
    path = _prd_spec_path(cfg, prd_id)
    rel = os.path.relpath(path, cfg.repo_root)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^##\s+.*?Scope.*?$(.*?)(?=^##\s|\Z)", text)
        if match:
            return {"source": f"{rel}#Scope",
                    "sha256": _sha256_text(match.group(1).strip())}
    missing.append("scope")
    return {"source": "unknown", "sha256": "unknown"}


def _assemble_duplicates(cfg: Config, prd_id: str, finding_id: str,
                         finding_body: str, missing: list[str]) -> list[dict]:
    duplicates: list[dict] = []
    try:
        import findings_xref

        for match in findings_xref.cross_reference(prd_id, cfg=cfg,
                                                   repo_root=cfg.repo_root):
            if match.get("current_finding_id") != finding_id:
                continue
            duplicates.append({
                "prd_id": match["prior_prd_id"],
                "finding_id": match["prior_finding_id"],
                "similarity": match["similarity"],
                "source": str(os.path.relpath(
                    cfg.findings_dir / f"{match['prior_prd_id']}-findings.jsonl",
                    cfg.repo_root)),
            })
        threshold = getattr(findings_xref, "DEFAULT_THRESHOLD", 0.5)
        own_path = cfg.findings_dir / f"{prd_id}-findings.jsonl"
        for record in _read_findings(own_path):
            if record.get("id") == finding_id:
                continue
            similarity = findings_xref.jaccard(finding_body,
                                               str(record.get("body", "")))
            if similarity >= threshold:
                duplicates.append({
                    "prd_id": prd_id,
                    "finding_id": record["id"],
                    "similarity": similarity,
                    "source": str(os.path.relpath(own_path, cfg.repo_root)),
                })
    except Exception:  # advisory engine failure -> honest unknown, not []
        missing.append("duplicates")
    return duplicates


def _read_findings(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _assemble_remediation(cfg: Config, prd_id: str, finding_id: str,
                          missing: list[str]) -> list[dict]:
    path = cfg.receipts_path
    if not path.is_file():
        return []
    rel = os.path.relpath(path, cfg.repo_root)
    rows = []
    try:
        for line_number, raw in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            record = json.loads(raw)
            if record.get("prd_id") == prd_id and \
                    record.get("finding_id") == finding_id:
                rows.append({
                    "issue_id": record.get("issue_id"),
                    "finding_id": record.get("finding_id"),
                    "closed_at": record.get("closed_at"),
                    "commit_sha": record.get("commit_sha"),
                    "source": f"{rel}:{line_number}",
                })
    except (json.JSONDecodeError, OSError):
        missing.append("remediation")
    return rows


def assemble_packet(cfg: Config, prd_id: str, finding_id: str) -> dict:
    findings_file = cfg.findings_dir / f"{prd_id}-findings.jsonl"
    finding = next((r for r in _read_findings(findings_file)
                    if r.get("id") == finding_id), None)
    if finding is None:
        raise ValidationError(
            f"finding not found: {prd_id}/{finding_id} in {findings_file}")
    body = str(finding.get("body", ""))
    missing: list[str] = []
    duplicates = _assemble_duplicates(cfg, prd_id, finding_id, body, missing)
    prior = [r["receipt_id"] for r in read_ledger(ledger_path(cfg))
             if r.get("finding", {}).get("prd_id") == prd_id
             and r.get("finding", {}).get("finding_id") == finding_id]
    packet = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "finding": {
            "prd_id": prd_id,
            "finding_id": finding_id,
            "severity": finding.get("severity"),
            "body": body,
            "body_sha256": _sha256_text(body),
        },
        "review": {"source": finding.get("source"), "review_run_id": None},
        "repo_state": _assemble_repo_state(cfg.repo_root, missing),
        "prd_state": _assemble_prd_state(cfg, prd_id, missing),
        "issue_state": _assemble_issue_state(cfg, prd_id, missing),
        "scope": _assemble_scope(cfg, prd_id, missing),
        "duplicates": duplicates,
        "remediation": _assemble_remediation(cfg, prd_id, finding_id, missing),
        "related_prds": sorted({d["prd_id"] for d in duplicates
                                if d["prd_id"] != prd_id}),
        "prior_receipts": prior,
        "missing_context": sorted(set(missing)),
    }
    packet["assembled_at"] = _now_iso()
    packet["packet_sha256"] = packet_hash(packet)
    return packet


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def _check_packet_freshness(cfg: Config, packet: dict) -> None:
    """A receipt freezes decision-time state, so the packet must BE
    decision-time state: if the PRD or finding moved since assembly, refuse
    and demand a re-assemble instead of freezing a lie."""
    prd_state = packet["prd_state"]
    if prd_state["sha256"] != "unknown":
        path = cfg.repo_root / prd_state["path"]
        current = _sha256_text(path.read_text(encoding="utf-8")) \
            if path.is_file() else "unknown"
        if current != prd_state["sha256"]:
            raise ValidationError(
                "stale context packet: the PRD changed after assembly "
                f"({prd_state['path']}). Re-run assemble.")
    finding = packet["finding"]
    findings_file = cfg.findings_dir / f"{finding['prd_id']}-findings.jsonl"
    current_finding = next(
        (r for r in _read_findings(findings_file)
         if r.get("id") == finding["finding_id"]), None)
    if current_finding is None or \
            _sha256_text(str(current_finding.get("body", ""))) != finding["body_sha256"]:
        raise ValidationError(
            "stale context packet: the finding body changed after assembly. "
            "Re-run assemble.")


def _load_judge_run(path: Path, packet: dict) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValidationError(f"judge run {path}: unreadable: {exc}") from exc
    allowed = frozenset(("model", "prompt_sha256", "review_run_id",
                         "input_sha256", "output"))
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValidationError(f"judge run: unknown fields {extra}")
    for key in ("model", "prompt_sha256", "input_sha256", "output"):
        if key not in raw:
            raise ValidationError(f"judge run: missing field {key}")
    if raw["input_sha256"] != packet["packet_sha256"]:
        raise ValidationError(
            "judge run input_sha256 does not match the context packet hash — "
            "the judge saw different context than this capture (stale hash)")
    validate_judge_output(raw["output"], "judge run")
    return raw


def _judge_block_from_run(run: dict) -> dict:
    output = dict(run["output"])
    output_sha256 = canonical_hash(output)
    converted_from = None
    gate = evidence_gate_errors(output["workflow_reason_code"],
                                output["workflow_disposition"],
                                output["evidence_refs"])
    if gate:
        # PRD Change 4: an unsupported JUDGE recommendation degrades to
        # needs-human (advisory contract). A human decision hard-fails instead.
        converted_from = output["workflow_disposition"]
        output["workflow_disposition"] = "needs-human"
        output["missing_context"] = sorted(set(output["missing_context"]) |
                                           {"required_evidence"})
    return {
        "model": run["model"],
        "prompt_sha256": run["prompt_sha256"],
        "review_run_id": run.get("review_run_id"),
        "input_sha256": run["input_sha256"],
        "output_sha256": output_sha256,
        "output": output,
        "converted_to_needs_human": converted_from is not None,
        "converted_from": converted_from,
    }


def build_receipt(cfg: Config, packet: dict, *, disposition: str,
                  actor: str, reason_code: str | None,
                  evidence_refs: list[str], rationale: str | None,
                  judge_run: dict | None, supersedes: str | None,
                  existing: list[dict]) -> dict:
    """Validate the whole episode and produce the receipt record (pure)."""
    validate_packet(packet)
    if disposition not in LEGACY_DISPOSITIONS:
        raise ValidationError(f"disposition must be one of {LEGACY_DISPOSITIONS}")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise ValidationError(
            f"reason-code must be one of the canonical codes; got {reason_code!r}")
    _validate_evidence_refs(evidence_refs, "human decision")
    gate = evidence_gate_errors(reason_code, None, evidence_refs)
    if gate:
        raise ValidationError("human decision: " + "; ".join(gate))

    known_ids = {r["receipt_id"] for r in existing}
    if supersedes is not None and supersedes not in known_ids:
        raise ValidationError(f"supersedes target not found: {supersedes}")
    if supersedes is None:
        finding = packet["finding"]
        already_superseded = {r["supersedes"] for r in existing
                             if r.get("supersedes")}
        priors = [r for r in existing
                  if r["finding"]["prd_id"] == finding["prd_id"]
                  and r["finding"]["finding_id"] == finding["finding_id"]
                  and r["receipt_id"] not in already_superseded]
        if priors:
            supersedes = priors[-1]["receipt_id"]

    missing_context = list(packet["missing_context"])
    if reason_code is None:
        missing_context.append("human.reason_code")

    record = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sequence": len(existing) + 1,
        "captured_at": _now_iso(),
        "finding": packet["finding"],
        "review": packet["review"],
        "repo_state": packet["repo_state"],
        "prd_state": packet["prd_state"],
        "issue_state": packet["issue_state"],
        "scope": packet["scope"],
        "duplicates": packet["duplicates"],
        "remediation": packet["remediation"],
        "related_prds": packet["related_prds"],
        "prior_receipts": packet["prior_receipts"],
        "missing_context": sorted(set(missing_context)),
        "judge": _judge_block_from_run(judge_run) if judge_run else None,
        "human": {
            "actor": actor,
            "decided_at": _now_iso(),
            "disposition": disposition,
            "reason_code": reason_code,
            "evidence_refs": evidence_refs,
            "rationale": rationale,
        },
        "sampling": {
            "basis_sha256": packet["packet_sha256"],
            "rule": SAMPLE_RULE,
            "salt": SAMPLE_SALT,
            "sampled": sample_decision(packet["packet_sha256"]),
        },
        "supersedes": supersedes,
        "prev_receipt_sha256": canonical_hash(existing[-1]) if existing else None,
    }
    record["receipt_id"] = receipt_content_id(record)
    if record["receipt_id"] in known_ids:
        raise ValidationError(
            f"duplicate receipt id {record['receipt_id']}: refusing to append")
    validate_receipt(record, record["receipt_id"])
    return record


def append_receipt(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def capture_episode(cfg: Config, packet: dict, **kwargs) -> dict:
    """The single write path into the judgments ledger."""
    _check_packet_freshness(cfg, packet)
    path = ledger_path(cfg)
    existing = read_ledger(path)
    record = build_receipt(cfg, packet, existing=existing, **kwargs)
    append_receipt(path, record)
    # Anchor AFTER the append. If the process dies between the two the anchor
    # under-counts, and an under-counting anchor is deliberately NOT an error
    # (see _tip_errors) so a crashed write never manufactures a truncation
    # alarm. Anchoring first would do the opposite: claim a receipt that was
    # never written, and fail every later verify.
    write_tip(tip_path(cfg), existing + [record])
    return record


def capture_from_triage(cfg: Config, prd_id: str, finding: dict, *,
                        actor: str, reason_code: str | None,
                        evidence_refs: list[str], rationale: str | None,
                        judge_run_path: str | None) -> dict:
    """Called by findings_writer.cmd_set_disposition after the disposition
    write. Assembles context inline; the caller pre-validated the evidence
    gate via validate_triage_decision (fail-fast, before any mutation)."""
    packet = assemble_packet(cfg, prd_id, finding["id"])
    judge_run = None
    if judge_run_path:
        judge_run = _load_judge_run(Path(judge_run_path), packet)
    return capture_episode(
        cfg, packet, disposition=finding["disposition"], actor=actor,
        reason_code=reason_code, evidence_refs=evidence_refs,
        rationale=rationale, judge_run=judge_run, supersedes=None)


def validate_triage_decision(reason_code: str | None,
                             evidence_refs: list[str]) -> list[str]:
    """Fail-fast half for findings_writer: returns error strings, no I/O."""
    errors = []
    if reason_code is not None and reason_code not in REASON_CODES:
        errors.append(
            f"reason-code must be one of {REASON_CODES}; got {reason_code!r}")
        return errors
    try:
        _validate_evidence_refs(evidence_refs, "human decision")
    except ValidationError as exc:
        errors.append(str(exc))
        return errors
    errors.extend(evidence_gate_errors(reason_code, None, evidence_refs))
    return errors


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify_ledger(records: list[dict], tip: dict | None = None) -> list[str]:
    errors = []
    seen_ids: set[str] = set()
    prev_hash: str | None = None
    for index, record in enumerate(records, 1):
        where = f"receipt line {index}"
        if record.get("sequence") != index:
            errors.append(
                f"{where}: sequence {record.get('sequence')!r} does not match "
                f"its position {index} — a receipt was deleted or reordered")
        # Duplicate detection runs on the STORED id, before content validation:
        # a forged copy of an earlier receipt fails self-hash too, but the
        # duplicate must be named as such (N-7) — one error per defect class.
        rid = record.get("receipt_id")
        if isinstance(rid, str):
            if rid in seen_ids:
                errors.append(f"{where}: duplicate receipt id {rid}")
            seen_ids.add(rid)
        try:
            validate_receipt(record, where)
        except ValidationError as exc:
            errors.append(str(exc))
            prev_hash = canonical_hash(record)
            continue
        if record["prev_receipt_sha256"] != prev_hash:
            errors.append(
                f"{where}: broken chain — prev_receipt_sha256 does not match "
                "the previous receipt")
        if record["supersedes"] is not None and \
                record["supersedes"] not in seen_ids - {rid}:
            errors.append(
                f"{where}: supersedes {record['supersedes']} which does not "
                "appear earlier in the ledger")
        prev_hash = canonical_hash(record)
    errors.extend(_tip_errors(records, tip, prev_hash))
    return errors


def _tip_errors(records: list[dict], tip: dict | None,
                last_hash: str | None) -> list[str]:
    """Deletion detection. A prefix of a valid chain is a valid chain, so the
    chain walk above cannot see a truncated tail; the anchor can."""
    if tip is None:
        # No anchor (legacy or fresh ledger). Do not hard-fail — that would
        # break every repo whose ledger predates the anchor — but never claim
        # completeness we cannot check.
        return []
    if len(records) < tip["count"]:
        return [f"ledger is TRUNCATED: {len(records)} receipt(s) present, tip "
                f"anchor recorded {tip['count']}"]
    if len(records) == tip["count"] and tip["last_receipt_sha256"] is not None \
            and last_hash != tip["last_receipt_sha256"]:
        return ["ledger tail does not match the tip anchor: the last receipt "
                "was replaced"]
    return []


def verify_candidates(records: list[dict]) -> list[str]:
    errors = []
    for index, record in enumerate(records, 1):
        try:
            validate_candidate(record, f"candidate line {index}")
        except ValidationError as exc:
            errors.append(str(exc))
    return errors


def cross_check_findings(cfg: Config, records: list[dict],
                         since: str | None = None) -> list[str]:
    """Completeness check against an INDEPENDENT source: every dispositioned
    finding should have a receipt.

    The tip anchor and the ledger share a writer, so both move together if that
    writer is wrong or malicious. The findings ledgers do not: they are written
    by findings_writer's own path. A dispositioned finding with no receipt is
    either a truncation the anchor missed or a capture that silently failed.

    `since` filters by finding resolved_at, because findings dispositioned
    before this feature existed have no receipt by construction and would
    otherwise report as thousands of false gaps.
    """
    covered = {(r["finding"]["prd_id"], r["finding"]["finding_id"])
               for r in records}
    errors = []
    for path in sorted(cfg.findings_dir.rglob("*-findings.jsonl")):
        for record in _read_findings(path):
            disposition = record.get("disposition")
            if disposition in (None, "pending"):
                continue
            resolved_at = str(record.get("resolved_at") or "")
            if since and resolved_at < since:
                continue
            key = (record.get("prd_id"), record.get("id"))
            if key not in covered:
                errors.append(
                    f"{key[0]}/{key[1]}: dispositioned {disposition!r} at "
                    f"{resolved_at or 'unknown time'} but no judgment receipt "
                    "exists")
    return errors


def verify_packet_binding(packet: dict, receipt: dict) -> list[str]:
    errors = []
    recomputed = packet_hash(packet)
    if recomputed != receipt["sampling"]["basis_sha256"]:
        errors.append(
            "packet does not re-hash to the receipt's sampling basis "
            f"({recomputed} != {receipt['sampling']['basis_sha256']})")
    judge = receipt.get("judge")
    if judge and judge["input_sha256"] != recomputed:
        errors.append("packet does not re-hash to the judge input_sha256")
    return errors


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


def _active_receipts(records: list[dict]) -> tuple[list[dict], int]:
    superseded = {r["supersedes"] for r in records if r.get("supersedes")}
    active = [r for r in records if r["receipt_id"] not in superseded]
    return active, len(records) - len(active)


def _score_cases(cases: list[tuple[str, str, float]]) -> dict:
    """cases: (gold_legacy, predicted_legacy, confidence)."""
    labels = ("accepted", "rejected", "deferred")
    matrix = {g: {p: 0 for p in labels} for g in labels}
    for gold, predicted, _confidence in cases:
        matrix[gold][predicted] += 1
    total = len(cases)
    correct = sum(matrix[l][l] for l in labels)
    gold_totals = {l: sum(matrix[l].values()) for l in labels}
    pred_totals = {l: sum(matrix[g][l] for g in labels) for l in labels}
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        recall = tp / gold_totals[label] if gold_totals[label] else 0.0
        precision = tp / pred_totals[label] if pred_totals[label] else 0.0
        f1 = (2 * precision * recall / (precision + recall)) \
            if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1}
    expected = sum(gold_totals[l] * pred_totals[l] for l in labels) / (total * total) \
        if total else 0.0
    accuracy = correct / total if total else 0.0
    kappa = (accuracy - expected) / (1 - expected) \
        if total and not math.isclose(expected, 1.0) else (1.0 if total else 0.0)
    ece = _expected_calibration_error(cases)
    return {
        "cases": total,
        "exact_agreement": accuracy,
        "balanced_accuracy": sum(per_class[l]["recall"] for l in labels) / len(labels),
        "macro_f1": sum(per_class[l]["f1"] for l in labels) / len(labels),
        "cohen_kappa": kappa,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "ece_10_bin": ece,
    }


def _expected_calibration_error(cases: list[tuple[str, str, float]]) -> float:
    total = len(cases)
    if not total:
        return 0.0
    ece = 0.0
    for bin_index in range(10):
        lower, upper = bin_index / 10, (bin_index + 1) / 10
        members = [(gold, predicted, confidence)
                   for gold, predicted, confidence in cases
                   if confidence >= lower and
                   (confidence < upper or (upper == 1.0 and confidence <= upper))]
        if not members:
            continue
        mean_confidence = sum(c for _, _, c in members) / len(members)
        accuracy = sum(1 for g, p, _ in members if g == p) / len(members)
        ece += (len(members) / total) * abs(accuracy - mean_confidence)
    return ece


def evaluate(records: list[dict]) -> dict:
    active, superseded_excluded = _active_receipts(records)
    judged = [r for r in active if r.get("judge") and r.get("human")
              and r["human"]["disposition"] != "pending"]
    cases = []
    needs_human = 0
    converted = 0
    for record in judged:
        output = record["judge"]["output"]
        if record["judge"]["converted_to_needs_human"]:
            converted += 1
        mapped = JUDGE_TO_LEGACY[output["workflow_disposition"]]
        if mapped is None:
            needs_human += 1
            continue
        cases.append((record["human"]["disposition"], mapped,
                      float(output["confidence"])))
    result = _score_cases(cases)
    sampled = sum(1 for r in judged if r["sampling"]["sampled"])
    by_code: dict[str, dict] = {}
    for record in judged:
        code = record["human"]["reason_code"] or "null"
        bucket = by_code.setdefault(code, {"cases": 0, "agreements": 0})
        bucket["cases"] += 1
        mapped = JUDGE_TO_LEGACY[record["judge"]["output"]["workflow_disposition"]]
        if mapped == record["human"]["disposition"]:
            bucket["agreements"] += 1
    population = {}
    for record in active:
        if record.get("human"):
            disposition = record["human"]["disposition"]
            population[disposition] = population.get(disposition, 0) + 1
    gates = _release_gates(result)
    result.update({
        "superseded_excluded": superseded_excluded,
        "active_receipts": len(active),
        "judged_receipts": len(judged),
        "human_review_rate": ((needs_human + sampled) / len(judged))
        if judged else 0.0,
        "unsupported_disposition_rate": (converted / len(judged)) if judged else 0.0,
        "missing_context_rate": (
            sum(1 for r in active if r["missing_context"]) / len(active))
        if active else 0.0,
        "by_reason_code": by_code,
        "population_counts": population,
        "release_gates": gates,
    })
    return result


def _release_gates(scored: dict) -> dict:
    checks = {
        "min_cases": {"required": 50, "actual": scored["cases"],
                      "passed": scored["cases"] >= 50},
        "exact_agreement": {"required": 0.88, "actual": scored["exact_agreement"],
                            "passed": scored["exact_agreement"] >= 0.88},
        "cohen_kappa": {"required": 0.80, "actual": scored["cohen_kappa"],
                        "passed": scored["cohen_kappa"] >= 0.80},
        "per_class_recall": {
            "required": 0.80,
            "actual": {l: v["recall"] for l, v in scored["per_class"].items()},
            "passed": all(v["recall"] >= 0.80
                          for v in scored["per_class"].values()),
        },
    }
    checks["passed"] = all(c["passed"] for c in checks.values()
                           if isinstance(c, dict))
    return checks


# ---------------------------------------------------------------------------
# Policy candidates
# ---------------------------------------------------------------------------


def _override_pattern_key(record: dict) -> tuple | None:
    human = record.get("human")
    judge = record.get("judge")
    if not human or not judge or human["reason_code"] is None:
        return None
    mapped = JUDGE_TO_LEGACY[judge["output"]["workflow_disposition"]]
    if mapped == human["disposition"] and \
            judge["output"]["workflow_reason_code"] == human["reason_code"]:
        return None  # agreement, nothing to compile
    evidence_kinds = tuple(sorted({ref.split(":", 1)[0]
                                   for ref in human["evidence_refs"]}))
    return (human["reason_code"], evidence_kinds)


def detect_policy_candidates(records: list[dict], min_cases: int) -> list[dict]:
    active, _ = _active_receipts(records)
    groups: dict[tuple, list[dict]] = {}
    for record in active:
        key = _override_pattern_key(record)
        if key is not None:
            groups.setdefault(key, []).append(record)
    candidates = []
    for (reason_code, evidence_kinds), members in sorted(groups.items()):
        if len(members) < min_cases:
            continue
        counterexamples = [
            r["receipt_id"] for r in active
            if (key := _override_pattern_key(r)) is not None
            and key[1] == evidence_kinds and key[0] != reason_code]
        candidates.append(_candidate_record(
            reason_code, evidence_kinds, members, counterexamples, len(active)))
    return candidates


def _candidate_record(reason_code: str, evidence_kinds: tuple,
                      members: list[dict], counterexamples: list[str],
                      searched: int) -> dict:
    pattern = {
        "human_reason_code": reason_code,
        "evidence_kinds": list(evidence_kinds),
        "judge_disagreed": True,
    }
    record = {
        "status": "proposed",
        "created_at": _now_iso(),
        "pattern": pattern,
        "supporting_receipt_ids": [m["receipt_id"] for m in members],
        "case_count": len(members),
        "counterexamples": counterexamples,
        "counterexample_search": (
            f"scanned {searched} active receipts for judge-overridden decisions "
            f"sharing evidence kinds {list(evidence_kinds)} with a human reason "
            f"code other than {reason_code!r}"),
        "proposed_rule": (
            f"before the LLM judge runs, resolve refs of kind "
            f"{list(evidence_kinds)} deterministically; when they establish "
            f"{reason_code!r}, record that disposition from the reference "
            "itself instead of asking the judge"),
        "proposed_tests": [
            f"a finding whose context resolves {reason_code!r} evidence is "
            "dispositioned without a judge call",
            "a finding whose context lacks that evidence still reaches the judge",
        ],
        "false_positive_risk": (
            f"{len(counterexamples)} counterexample(s) in the scanned window; "
            "similarity-based references can collide on boilerplate findings"),
        "integration_point": "before-llm-judge",
    }
    body = {k: v for k, v in record.items() if k != "created_at"}
    record["candidate_id"] = "jpc-" + canonical_hash(body)[:12]
    return record


def append_candidates(path: Path, candidates: list[dict]) -> list[dict]:
    existing_ids = set()
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                try:
                    existing_ids.add(json.loads(raw).get("candidate_id"))
                except json.JSONDecodeError:
                    continue
    fresh = [c for c in candidates if c["candidate_id"] not in existing_ids]
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for candidate in fresh:
                handle.write(json.dumps(candidate, sort_keys=True,
                                        separators=(",", ":"),
                                        ensure_ascii=False) + "\n")
    return fresh


# ---------------------------------------------------------------------------
# Selftest (fully in-memory: must pass in a read-only sandbox)
# ---------------------------------------------------------------------------


def _fixture_packet(index: int = 0) -> dict:
    body = f"fixture objection {index}"
    packet = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "finding": {"prd_id": "prd-selftest", "finding_id": f"finding-{index + 1}",
                    "severity": "major", "body": body,
                    "body_sha256": _sha256_text(body)},
        "review": {"source": "codex-review", "review_run_id": None},
        "repo_state": {"branch": "unknown", "commit_sha": "unknown",
                       "dirty": "unknown"},
        "prd_state": {"path": "prd.md", "sha256": "unknown",
                      "status": "unknown", "revision": "unknown"},
        "issue_state": {"issue_id": None, "manifest_sha256": "unknown",
                        "issue_order": []},
        "scope": {"source": "unknown", "sha256": "unknown"},
        "duplicates": [], "remediation": [], "related_prds": [],
        "prior_receipts": [],
        "missing_context": ["repo_state.branch"],
    }
    packet["assembled_at"] = "2026-08-04T00:00:00Z"
    packet["packet_sha256"] = packet_hash(packet)
    return packet


def _selftest_receipt(existing: list[dict], index: int, **overrides) -> dict:
    packet = _fixture_packet(index)
    kwargs = dict(disposition="accepted", actor="selftest", reason_code=None,
                  evidence_refs=[], rationale=None, judge_run=None,
                  supersedes=None)
    kwargs.update(overrides)
    # cfg is unused by build_receipt's pure paths; pass None deliberately
    return build_receipt(None, packet, existing=existing, **kwargs)  # type: ignore[arg-type]


def selftest() -> int:
    failures: list[str] = []

    def expect(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    ledger: list[dict] = []
    ledger.append(_selftest_receipt(ledger, 0))
    ledger.append(_selftest_receipt(ledger, 1))
    expect(verify_ledger(ledger) == [], "clean chain verifies")

    mutated = [dict(ledger[0]), ledger[1]]
    mutated[0] = json.loads(json.dumps(mutated[0]))
    mutated[0]["human"]["disposition"] = "rejected"
    expect(bool(verify_ledger(mutated)), "mutated receipt is detected")

    try:
        _selftest_receipt(ledger, 2, disposition="rejected",
                          reason_code="duplicate")
        expect(False, "evidence-free duplicate is refused")
    except ValidationError:
        pass

    packet = _fixture_packet(3)
    judge_run = {
        "model": "selftest", "prompt_sha256": "0" * 64,
        "review_run_id": None, "input_sha256": packet["packet_sha256"],
        "output": {
            "technical_validity": "valid", "technical_reason": "fixture",
            "workflow_disposition": "already-remediated",
            "workflow_reason_code": "already-remediated",
            "evidence_refs": [], "missing_context": [], "confidence": 0.9,
        },
    }
    block = _judge_block_from_run(judge_run)
    expect(block["output"]["workflow_disposition"] == "needs-human",
           "unsupported judge disposition converts to needs-human")
    expect(block["converted_to_needs_human"] is True, "conversion is flagged")

    try:
        validate_judge_output({**judge_run["output"], "vibes": "good"}, "selftest")
        expect(False, "extra judge field is refused")
    except ValidationError:
        pass

    basis = _sha256_text("selftest-basis")
    expect(sample_decision(basis) == sample_decision(basis),
           "sampling is deterministic")

    report = evaluate(ledger)
    expect(report["release_gates"]["passed"] is False,
           "release gates stay closed with no judged cases")

    if failures:
        for failure in failures:
            print(f"SELFTEST FAIL: {failure}", file=sys.stderr)
        return 1
    print("SELFTEST PASS: chain, evidence gate, judge contract, sampling, "
          "release gates all enforced in memory")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_assemble(cfg: Config, args: argparse.Namespace) -> int:
    packet = assemble_packet(cfg, args.prd, args.finding)
    text = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(json.dumps({"packet_sha256": packet["packet_sha256"],
                          "missing_context": packet["missing_context"],
                          "path": args.output}, indent=2))
    else:
        print(text, end="")
    return 0


def cmd_capture(cfg: Config, args: argparse.Namespace) -> int:
    try:
        packet = json.loads(Path(args.context).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValidationError(f"context packet unreadable: {exc}") from exc
    if packet.get("finding", {}).get("prd_id") != args.prd or \
            packet.get("finding", {}).get("finding_id") != args.finding:
        raise ValidationError(
            "context packet is for a different finding than the capture args")
    judge_run = None
    if args.judge_run:
        validate_packet(packet)
        judge_run = _load_judge_run(Path(args.judge_run), packet)
    record = capture_episode(
        cfg, packet, disposition=args.disposition, actor=args.actor,
        reason_code=args.reason_code, evidence_refs=args.evidence or [],
        rationale=args.rationale, judge_run=judge_run,
        supersedes=args.supersedes)
    print(json.dumps({"receipt_id": record["receipt_id"],
                      "sampled": record["sampling"]["sampled"],
                      "supersedes": record["supersedes"],
                      "path": str(ledger_path(cfg))}, indent=2))
    return 0


def cmd_verify(cfg: Config, args: argparse.Namespace) -> int:
    records = read_ledger(ledger_path(cfg))
    errors = verify_ledger(records, read_tip(tip_path(cfg)))
    candidate_records = read_ledger(candidates_path(cfg))
    errors.extend(verify_candidates(candidate_records))
    if getattr(args, "cross_check", False):
        errors.extend(cross_check_findings(cfg, records,
                                           getattr(args, "since", None)))
    if args.packet or args.receipt_id:
        if not (args.packet and args.receipt_id):
            raise ValidationError("--packet and --receipt-id go together")
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        receipt = next((r for r in records
                        if r.get("receipt_id") == args.receipt_id), None)
        if receipt is None:
            errors.append(f"receipt not found: {args.receipt_id}")
        else:
            errors.extend(verify_packet_binding(packet, receipt))
    if errors:
        print("VERIFY FAIL:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    print(f"VERIFY PASS: {len(records)} receipt(s), "
          f"{len(candidate_records)} candidate(s), chain intact")
    return 0


def cmd_evaluate(cfg: Config, args: argparse.Namespace) -> int:
    records = read_ledger(ledger_path(cfg))
    errors = verify_ledger(records, read_tip(tip_path(cfg)))
    if errors:
        print("EVALUATE REFUSED: ledger fails verification:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    print(json.dumps(evaluate(records), indent=2, sort_keys=True))
    return 0


def cmd_sample_check(cfg: Config, args: argparse.Namespace) -> int:
    basis = args.basis.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", basis):
        raise ValidationError("--basis must be a 64-char sha256 hex digest")
    print(json.dumps({
        "basis_sha256": basis,
        "sampled": sample_decision(basis),
        "rule": SAMPLE_RULE,
        "salt": SAMPLE_SALT,
        "threshold": SAMPLE_THRESHOLD,
        "modulus": SAMPLE_MODULUS,
    }, indent=2))
    return 0


def cmd_policy_candidates(cfg: Config, args: argparse.Namespace) -> int:
    records = read_ledger(ledger_path(cfg))
    errors = verify_ledger(records, read_tip(tip_path(cfg)))
    if errors:
        print("POLICY-CANDIDATES REFUSED: ledger fails verification",
              file=sys.stderr)
        return 2
    candidates = detect_policy_candidates(records, args.min_cases)
    fresh = append_candidates(candidates_path(cfg), candidates) \
        if candidates else []
    print(json.dumps({
        "detected": len(candidates),
        "appended": len(fresh),
        "path": str(candidates_path(cfg)),
        "note": "candidates are proposals; promotion requires the "
                "human-reviewed prd-os path and runs before the LLM judge",
    }, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--repo-root", help="override repo root discovery")
    sub = parser.add_subparsers(dest="cmd")

    p_assemble = sub.add_parser("assemble")
    p_assemble.add_argument("--prd", required=True)
    p_assemble.add_argument("--finding", required=True)
    p_assemble.add_argument("--output")
    p_assemble.set_defaults(func=cmd_assemble)

    p_capture = sub.add_parser("capture")
    p_capture.add_argument("--prd", required=True)
    p_capture.add_argument("--finding", required=True)
    p_capture.add_argument("--context", required=True)
    p_capture.add_argument("--disposition", required=True)
    p_capture.add_argument("--reason-code", dest="reason_code")
    p_capture.add_argument("--evidence", action="append", default=[])
    p_capture.add_argument("--rationale")
    p_capture.add_argument("--actor", default="founder")
    p_capture.add_argument("--judge-run", dest="judge_run")
    p_capture.add_argument("--supersedes")
    p_capture.set_defaults(func=cmd_capture)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--packet")
    p_verify.add_argument("--receipt-id", dest="receipt_id")
    p_verify.add_argument("--cross-check", action="store_true",
                          dest="cross_check",
                          help="also require a receipt for every dispositioned "
                               "finding (independent completeness check)")
    p_verify.add_argument("--since", help="ISO timestamp floor for --cross-check")
    p_verify.set_defaults(func=cmd_verify)

    p_evaluate = sub.add_parser("evaluate")
    p_evaluate.set_defaults(func=cmd_evaluate)

    p_sample = sub.add_parser("sample-check")
    p_sample.add_argument("--basis", required=True)
    p_sample.set_defaults(func=cmd_sample_check)

    p_policy = sub.add_parser("policy-candidates")
    p_policy.add_argument("--min-cases", dest="min_cases", type=int, default=3)
    p_policy.set_defaults(func=cmd_policy_candidates)

    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not getattr(args, "func", None):
        parser.error("choose a subcommand or --selftest")
    try:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        cfg = load_config(repo_root, strict=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    try:
        return args.func(cfg, args)
    except ValidationError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
