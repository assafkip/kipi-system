#!/usr/bin/env python3
"""PRD state-machine runner for the prd-os plugin.

Subcommands:
  new <slug>                Create a PRD from template (status=idea)
  load <prd-id>             Hydrate active-PRD state from an existing spec
  status                    Print active-PRD state
  advance <new-status>      Validated transition
  archive                   Transition to `archived` (terminal)
  clear                     Clear active-PRD state (no spec change)

States:
  idea -> draft -> in-review -> approved -> archived

Allowed transitions (everything else is rejected with exit 2):
  idea      -> draft, archived
  draft     -> in-review, archived
  in-review -> draft, approved, archived
  approved  -> archived
  archived  -> (terminal)

Approval gate:
  `advance approved` enforces two checks:
    1. PRD frontmatter carries a `codex_reviewed_at` stamp. The stamp is
       only ever written by `findings_writer.py` (either as a side effect
       of an `add --source codex-*` call or via its `record-review`
       subcommand). No stamp means Codex review never ran, so approval
       must not proceed.
    2. The findings file, if present, has zero findings with
       `disposition: pending`. Any JSONL parse error or pending finding
       blocks advancement.

The PRD runner is intentionally independent of the issue runner. Cross-runner
concurrency (no concurrent PRD + issue active contexts) lives at the command
layer in step 6 where both runners are orchestrated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ConfigError, load as load_config  # noqa: E402
from concurrency import ConcurrencyError, assert_no_active_issue  # noqa: E402


PRD_STATES = ("idea", "draft", "in-review", "approved", "archived")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "idea": ("draft", "archived"),
    "draft": ("in-review", "archived"),
    "in-review": ("draft", "approved", "archived"),
    "approved": ("archived",),
    "archived": (),
}

TEMPLATE_RELPATH = Path(__file__).resolve().parent.parent / "templates" / "prd.md"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


# ---------------------------------------------------------------------------
# Spec parsing (same minimal YAML frontmatter style as issue_runner.py)
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        raise ValueError("spec missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("spec frontmatter not closed with ---")
    block = text[3:end].strip("\n")
    result: dict = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _empty_state() -> dict:
    return {"prd_id": None, "loaded_at": None, "spec_path": None, "status": None}


def _read_state(cfg: Config) -> dict:
    path = cfg.active_prd_state_path
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return _empty_state()


def _write_state(cfg: Config, state: dict) -> None:
    path = cfg.active_prd_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _relpath(cfg: Config, p: Path) -> str:
    try:
        return str(p.resolve().relative_to(cfg.repo_root))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_new(cfg: Config, args: argparse.Namespace) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug):
        sys.stderr.write(
            f"PRD slug must match {SLUG_RE.pattern!r}; got {slug!r}\n"
        )
        return 2
    try:
        assert_no_active_issue(
            cfg.active_issue_state_path, action=f"start PRD {slug!r}"
        )
    except ConcurrencyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    existing = _read_state(cfg)
    if existing.get("prd_id") and existing.get("status") != "archived":
        sys.stderr.write(
            f"PRD context busy: {existing['prd_id']} is active "
            f"(status={existing['status']!r}). Archive or clear first.\n"
        )
        return 2

    title = args.title or slug.replace("-", " ").title()
    owner = args.owner or os.environ.get("USER", "unknown")
    created_at = _now_iso()
    prd_id = f"prd-{slug}-{created_at[:10]}"
    spec_path = cfg.prds_dir / f"{prd_id}.md"
    if spec_path.exists():
        sys.stderr.write(f"PRD spec already exists: {spec_path}\n")
        return 2

    template = TEMPLATE_RELPATH.read_text()
    body = (
        template.replace("{{prd_id}}", prd_id)
        .replace("{{title}}", title)
        .replace("{{created_at}}", created_at)
        .replace("{{owner}}", owner)
    )
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(body)

    state = {
        "prd_id": prd_id,
        "loaded_at": created_at,
        "spec_path": _relpath(cfg, spec_path),
        "status": "idea",
    }
    _write_state(cfg, state)
    print(json.dumps({"created": prd_id, "spec_path": state["spec_path"]}, indent=2))
    return 0


def _depends_on_gate(cfg: Config, spec_path) -> tuple[int, str]:
    """Phase gating (prd-os-spine-native): a PRD with `depends_on: <prd-id>`
    cannot activate while the dependency's registered gates are RED — the
    spine's "phase N+1 starts only on green" rule, mechanized."""
    try:
        fm = _parse_frontmatter(spec_path.read_text())
    except ValueError:
        return 0, ""  # malformed specs fail later, with the better message
    dep = (fm.get("depends_on") or "").strip()
    if not dep:
        return 0, ""
    import subprocess as _subprocess
    gates = _gates_path(cfg)
    if not gates.is_file():
        return 0, ""  # no registry yet — nothing to gate on
    for raw in gates.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("prd_id") != dep:
            continue
        try:
            lifecycle = _gate_lifecycle(rec)
        except ValueError as exc:
            return 2, f"activation blocked: dependency gate registry is invalid ({exc}).\n"
        if lifecycle != "regression":
            continue
        result = _subprocess.run(rec["command"], shell=True,
                                 cwd=cfg.repo_root, capture_output=True,
                                 text=True, timeout=900)
        if result.returncode != 0:
            return 2, (
                f"activation blocked: dependency {dep} has a RED gate "
                f"({rec['gate_id']}: {rec['command'][:80]}). Fix the "
                "dependency before starting this PRD.\n")
    return 0, ""


def cmd_load(cfg: Config, args: argparse.Namespace) -> int:
    prd_id = args.prd_id
    try:
        assert_no_active_issue(
            cfg.active_issue_state_path, action=f"load PRD {prd_id!r}"
        )
    except ConcurrencyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    spec_path = cfg.prds_dir / f"{prd_id}.md"
    if not spec_path.is_file():
        sys.stderr.write(f"PRD spec not found: {spec_path}\n")
        return 2
    rc, err = _depends_on_gate(cfg, spec_path)
    if rc != 0:
        sys.stderr.write(err)
        return rc
    try:
        fm = _parse_frontmatter(spec_path.read_text())
    except ValueError as exc:
        sys.stderr.write(f"{spec_path}: {exc}\n")
        return 2
    status = fm.get("status", "idea")
    if status not in PRD_STATES:
        sys.stderr.write(
            f"{spec_path}: unknown status {status!r}. Expected one of {PRD_STATES}.\n"
        )
        return 2
    state = {
        "prd_id": fm.get("id", prd_id),
        "loaded_at": _now_iso(),
        "spec_path": _relpath(cfg, spec_path),
        "status": status,
    }
    _write_state(cfg, state)
    print(json.dumps({"loaded": state["prd_id"], "status": status}, indent=2))
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    print(json.dumps(_read_state(cfg), indent=2))
    return 0


def cmd_advance(cfg: Config, args: argparse.Namespace) -> int:
    target = args.new_status
    if target not in PRD_STATES:
        sys.stderr.write(f"unknown status: {target!r}. Expected one of {PRD_STATES}.\n")
        return 2
    state = _read_state(cfg)
    if not state.get("prd_id"):
        sys.stderr.write("no active PRD\n")
        return 2
    current = state.get("status") or "idea"
    if target not in ALLOWED_TRANSITIONS.get(current, ()):
        sys.stderr.write(
            f"illegal transition {current!r} -> {target!r}. "
            f"Allowed from {current!r}: {ALLOWED_TRANSITIONS.get(current, ())}.\n"
        )
        return 2

    rc, err = _issues_dedup_gate(cfg, state)
    if rc != 0:
        sys.stderr.write(err)
        return rc

    if target == "approved":
        rc, err = _findings_gate(cfg, state)
        if rc != 0:
            sys.stderr.write(err)
            return rc
        rc, err = _issues_manifest_gate(cfg, state)
        if rc != 0:
            sys.stderr.write(err)
            return rc

    if target == "archived":
        rc, err = _archive_coverage_gate(cfg, state)
        if rc != 0:
            sys.stderr.write(err)
            return rc
        rc, err = _manifest_status_gate(cfg, state)
        if rc != 0:
            sys.stderr.write(err)
            return rc

    spec_path = cfg.repo_root / state["spec_path"]
    text = spec_path.read_text()
    new_text = re.sub(r"(?m)^status:\s*.+$", f"status: {target}", text, count=1)
    new_text = re.sub(
        r"(?m)^updated_at:\s*.+$", f"updated_at: {_now_iso()}", new_text, count=1
    )
    spec_path.write_text(new_text)
    state["status"] = target
    _write_state(cfg, state)
    print(json.dumps({"advanced": state["prd_id"], "status": target}))
    return 0


def cmd_archive(cfg: Config, args: argparse.Namespace) -> int:
    state = _read_state(cfg)
    if not state.get("prd_id"):
        sys.stderr.write("no active PRD\n")
        return 2
    current = state.get("status") or "idea"
    if current == "archived":
        print(json.dumps({"archived": state["prd_id"], "note": "already"}))
        return 0
    rc, err = _archive_coverage_gate(cfg, state)
    if rc != 0:
        sys.stderr.write(err)
        return rc
    rc, err = _manifest_status_gate(cfg, state)
    if rc != 0:
        sys.stderr.write(err)
        return rc
    spec_path = cfg.repo_root / state["spec_path"]
    text = spec_path.read_text()
    new_text = re.sub(r"(?m)^status:\s*.+$", "status: archived", text, count=1)
    new_text = re.sub(
        r"(?m)^updated_at:\s*.+$", f"updated_at: {_now_iso()}", new_text, count=1
    )
    spec_path.write_text(new_text)
    archived_id = state["prd_id"]
    _write_state(cfg, _empty_state())
    _propose_skeptic_antipatterns_best_effort(cfg, archived_id)
    print(json.dumps({"archived": archived_id}))
    return 0


def _propose_skeptic_antipatterns_best_effort(cfg: Config, prd_id: str) -> None:
    """Generate a Skeptic anti-pattern proposal from Codex findings on this PRD.

    Best-effort: archive is the load-bearing step. If proposal generation
    fails for any reason (missing script, parse error, IO error), log to
    stderr and continue. Archive remains successful.
    """
    try:
        from propose_skeptic_antipatterns import propose
        _, proposal_path = propose(cfg, prd_id)
        sys.stderr.write(f"skeptic proposal written: {proposal_path}\n")
    except Exception as exc:  # intentional best-effort catch-all
        sys.stderr.write(f"skeptic proposal skipped: {exc}\n")


def cmd_clear(cfg: Config, args: argparse.Namespace) -> int:
    _write_state(cfg, _empty_state())
    print("cleared")
    return 0


# ---------------------------------------------------------------------------
# Findings gate
# ---------------------------------------------------------------------------


def _issues_dedup_gate(cfg: Config, state: dict) -> tuple[int, str]:
    """Reject advance when the PRD body has more than one `## Issues` heading.

    Recurring drafting artifact: author adds a second `## Issues` block while
    filling Problem/Goals/etc., on top of the template's pre-existing one.
    Downstream `prd_split.py` and `_issues_manifest_gate` use `re.search`,
    which silently picks the first match — so a misordered or empty leading
    block parses garbage. Catch it deterministically at every transition.
    """
    spec_path = cfg.repo_root / state["spec_path"]
    text = spec_path.read_text()
    if not text.startswith("---"):
        return 0, ""  # frontmatter checks live elsewhere; nothing to dedup yet
    fm_end = text.find("\n---", 3)
    if fm_end == -1:
        return 0, ""
    body = text[fm_end + len("\n---"):]
    matches = re.findall(r"(?m)^##\s+Issues\s*$", body)
    if len(matches) > 1:
        return 2, (
            f"advance blocked: PRD body has {len(matches)} `## Issues` "
            "headings; the template already provides one. Remove the "
            "duplicate before advancing.\n"
        )
    return 0, ""


def _issues_manifest_gate(cfg: Config, state: dict) -> tuple[int, str]:
    """G1: PRD must carry a ## Issues manifest covering every accepted finding.

    Returns (exit_code, stderr_text). Zero means approval may proceed.
    """
    spec_path = cfg.repo_root / state["spec_path"]
    text = spec_path.read_text()

    # Find body after frontmatter end.
    if not text.startswith("---"):
        return 2, f"{spec_path}: spec missing YAML frontmatter\n"
    fm_end = text.find("\n---", 3)
    if fm_end == -1:
        return 2, f"{spec_path}: frontmatter not closed with ---\n"
    body = text[fm_end + len("\n---"):]

    issues_match = re.search(r"(?m)^##\s+Issues\s*$", body)
    if not issues_match:
        return 2, (
            "approval blocked: PRD has no ## Issues manifest. "
            "Add a `## Issues` section with a fenced ```json block listing "
            "one entry per accepted finding (finding_id, allowed_files, required_checks).\n"
        )
    rest = body[issues_match.end():]
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", rest, flags=re.DOTALL)
    if not fence:
        return 2, (
            "approval blocked: PRD ## Issues manifest is missing a fenced ```json block.\n"
        )
    try:
        entries = json.loads(fence.group(1))
    except json.JSONDecodeError as exc:
        return 2, f"approval blocked: issues manifest is not valid JSON ({exc}).\n"
    if not isinstance(entries, list):
        return 2, "approval blocked: issues manifest must be a JSON array.\n"

    # Per-entry field validation.
    seen_finding_ids: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return 2, f"approval blocked: manifest entry #{i} must be a JSON object.\n"
        fid = entry.get("finding_id")
        if not isinstance(fid, str) or not fid:
            return 2, (
                f"approval blocked: manifest entry #{i} is missing a non-empty "
                "`finding_id` string.\n"
            )
        if fid in seen_finding_ids:
            return 2, (
                f"approval blocked: finding_id {fid!r} appears in multiple "
                "manifest entries.\n"
            )
        seen_finding_ids.add(fid)
        allowed = entry.get("allowed_files")
        if not isinstance(allowed, list) or not allowed or not all(
            isinstance(x, str) and x for x in allowed
        ):
            return 2, (
                f"approval blocked: manifest entry for {fid!r} has empty or "
                "invalid allowed_files (must be a non-empty list of non-empty strings).\n"
            )
        checks = entry.get("required_checks")
        if not isinstance(checks, list) or not checks or not all(
            isinstance(x, str) and x for x in checks
        ):
            return 2, (
                f"approval blocked: manifest entry for {fid!r} has empty or "
                "invalid required_checks (must be a non-empty list of non-empty strings).\n"
            )
        # Spine contract (prd-os-spine-native): every entry proves no-bypass
        # or states why it is exempt. Acceptance-as-negative-invariant is the
        # machinery now, not operator discipline.
        bypass_check = entry.get("bypass_check")
        bypass_exempt = entry.get("bypass_exempt")
        if not (isinstance(bypass_check, str) and bypass_check.strip()) and not (
            isinstance(bypass_exempt, str) and bypass_exempt.strip()
        ):
            return 2, (
                f"approval blocked: manifest entry for {fid!r} has neither "
                "`bypass_check` (the command proving no bypass remains) nor "
                "`bypass_exempt: <reason>` (spine contract).\n"
            )

    # Cross-check against findings JSONL.
    fm = _parse_frontmatter(text)
    rel = fm.get("findings_path")
    accepted: set[str] = set()
    if rel:
        findings_file = cfg.repo_root / rel
        if findings_file.is_file():
            with findings_file.open() as fh:
                for lineno, raw in enumerate(fh, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # _findings_gate already fails closed on this
                    if isinstance(rec, dict) and rec.get("disposition") == "accepted":
                        fid = rec.get("id")
                        if isinstance(fid, str):
                            accepted.add(fid)

    if fm.get("kind") == "umbrella":
        # An umbrella PRD has no manifest of its own — its accepted findings
        # are owned by phase PRDs via covered_by on the disposition
        # (prd-os-spine-native). Verify every accepted finding names one.
        uncovered = []
        if rel:
            findings_file = cfg.repo_root / rel
            if findings_file.is_file():
                with findings_file.open() as fh:
                    for raw in fh:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (isinstance(rec, dict)
                                and rec.get("disposition") == "accepted"
                                and not (rec.get("covered_by") or "").strip()):
                            uncovered.append(rec.get("id"))
        if uncovered:
            return 2, ("approval blocked: umbrella PRD accepted findings lack "
                       f"covered_by (the owning phase PRD): {sorted(uncovered)}\n")
        return 0, ""

    missing = sorted(accepted - seen_finding_ids)
    if missing:
        lines = ["approval blocked: accepted findings have no manifest entry (not covered):"]
        for fid in missing:
            lines.append(f"  - {fid}")
        return 2, "\n".join(lines) + "\n"

    unknown = sorted(seen_finding_ids - accepted)
    if unknown:
        lines = ["approval blocked: manifest references unknown finding_id values:"]
        for fid in unknown:
            lines.append(f"  - {fid}")
        return 2, "\n".join(lines) + "\n"

    return 0, ""


def _findings_gate(cfg: Config, state: dict) -> tuple[int, str]:
    """Return (exit_code, stderr_text). Zero when the PRD can advance to approved."""
    spec_path = cfg.repo_root / state["spec_path"]
    try:
        fm = _parse_frontmatter(spec_path.read_text())
    except ValueError as exc:
        return 2, f"{spec_path}: {exc}\n"
    reviewed_at = (fm.get("codex_reviewed_at") or "").strip()
    if not reviewed_at:
        return 2, (
            "approval blocked: PRD has no `codex_reviewed_at` stamp. "
            "Run `/prd-review` (or `findings_writer.py record-review` if "
            "Codex found nothing) before advancing.\n"
        )
    rel = fm.get("findings_path")
    if not rel:
        return 0, ""
    findings_file = cfg.repo_root / rel
    if not findings_file.is_file():
        return 0, ""  # stamp present, no findings recorded — approval allowed
    pending: list[str] = []
    with findings_file.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                return 2, (
                    f"{findings_file}:{lineno}: invalid JSONL ({exc}). "
                    "Fix or remove the line before advancing.\n"
                )
            if not isinstance(rec, dict):
                return 2, (
                    f"{findings_file}:{lineno}: record must be an object\n"
                )
            if rec.get("disposition") == "pending":
                pending.append(rec.get("id", f"line-{lineno}"))
    if pending:
        return 2, (
            f"approval blocked: {len(pending)} pending finding(s): "
            f"{', '.join(pending)}. Set a disposition on each before advancing.\n"
        )
    return _judgment_receipt_gate(cfg, state["prd_id"])


# The Judgment Compiler shipped WRITING a receipt on every triage and REQUIRING
# one nowhere, which made it available rather than baked in: KIPI_JUDGMENT_CAPTURE=0,
# a hand-edited findings file, or a capture that failed and got ignored all left
# a silent hole no gate could see. A ledger with unnoticed holes cannot be the
# calibration set it exists to be.
JUDGMENT_RECEIPT_FLOOR = "2026-08-04T00:00:00Z"


def _judgment_receipt_gate(cfg: Config, prd_id: str) -> tuple[int, str]:
    """Every finding dispositioned since the floor must carry a receipt.

    FLOOR, not a blanket requirement: ~342 findings were adjudicated before the
    compiler existed and can never have receipts. Demanding them would block
    every pre-existing PRD forever, and a gate that cannot be satisfied gets
    switched off -- which protects nothing. So the rule binds only decisions
    made after the feature landed.
    """
    try:
        import judgment_compiler
    except ImportError:
        # The ONLY fail-open case: the compiler is not installed (an older
        # instance), so there is no contract to enforce and nothing to read.
        return 0, ""
    try:
        # Read UNDER THE WRITER'S LOCK. capture appends the receipt and then
        # writes the tip; observed between those two, the ledger holds N+1
        # records against a tip of N, which the chain check below correctly
        # calls "receipts BEYOND the tip anchor" -- and would block approval
        # over a concurrent capture that was perfectly fine (Codex, PR #101
        # round 4). I gave the writer a lock and left the reader without one.
        with judgment_compiler.ledger_lock(cfg):
            records = judgment_compiler.read_ledger(
                judgment_compiler.ledger_path(cfg))
            tip = judgment_compiler.read_tip(judgment_compiler.tip_path(cfg))
        # VERIFY before trusting. read_ledger only parses JSON, so without this
        # a receipt appended by hand -- right prd_id, right finding_id, right
        # disposition, broken chain -- satisfied the gate and authorized
        # approval (Codex, PR #101 round 3). A hash chain no consumer checks is
        # decoration; the gate is the consumer that matters.
        chain_errors = judgment_compiler.verify_ledger(records, tip)
        if chain_errors:
            return 2, (
                "approval blocked: the judgment ledger does not verify, so its "
                "receipts cannot be trusted as evidence:\n  "
                + "\n  ".join(chain_errors[:5])
                + ("\n  ..." if len(chain_errors) > 5 else "")
                + "\n\nRun `kipi judgment verify` for the full report.\n"
            )
        raw_missing = judgment_compiler.cross_check_findings(
            cfg, records, JUDGMENT_RECEIPT_FLOOR)
    except Exception as exc:
        # FAIL CLOSED. The first version caught everything and returned 0,
        # defended as "a bug in the check must not cause an approval outage".
        # That conflated two different things: a corrupt or truncated ledger is
        # not a bug in the gate, it is precisely the integrity failure the gate
        # exists to catch, and letting approval through on it is the worst
        # possible response (Codex, PR #101, executed repro: a ValueError from
        # read_ledger returned rc=0). A required integrity gate fails closed.
        return 2, (
            f"approval blocked: the judgment ledger could not be checked ({exc}).\n"
            "This is refused rather than skipped: an unreadable or corrupt "
            "ledger is the integrity failure this gate exists to catch. Run "
            "`kipi judgment verify` to see the damage.\n"
        )
    # Exact prd_id match, not `in`: cross_check_findings emits
    # "<prd_id>/<finding_id>: ...", so a substring test let a missing receipt
    # for `prd-alpha-2` block approval of `prd-alpha` (Codex, PR #101).
    missing = [m for m in raw_missing if m.startswith(f"{prd_id}/")]
    if missing:
        return 2, (
            f"approval blocked: {len(missing)} finding(s) dispositioned since "
            f"{JUDGMENT_RECEIPT_FLOOR} with no judgment receipt:\n  "
            + "\n  ".join(missing[:5])
            + ("\n  ..." if len(missing) > 5 else "")
            + "\n\nRe-run the disposition through findings_writer.py "
              "set-disposition so the decision is recorded, or explain the gap. "
              "Receipts are the calibration set; a hole in them is invisible "
              "later.\n"
        )
    return 0, ""


# ---------------------------------------------------------------------------
# Archive coverage gate
# ---------------------------------------------------------------------------


DEFERRED_WARN_DAYS = 30


def _load_receipt_issue_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    with path.open() as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and isinstance(rec.get("issue_id"), str):
                ids.add(rec["issue_id"])
    return ids


def _load_receipts_for_prd(path: Path, prd_id: str) -> set[str]:
    covered: set[str] = set()
    if not path.is_file():
        return covered
    with path.open() as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("prd_id") != prd_id:
                continue
            fid = rec.get("finding_id")
            if isinstance(fid, str) and fid:
                covered.add(fid)
    return covered


def _parse_iso_z(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _manifest_status_gate(cfg: Config, state: dict) -> tuple[int, str]:
    """G6: every issue in the PRD's `## Issues` manifest must be `status: closed`.

    Closes the failure mode observed 2026-05-04 in the warming-ladder PRD: a
    parent PRD archived with 5 issues at `status: open` and 0 implementation
    files on disk. The existing `_archive_coverage_gate` (G4) only verifies
    that *accepted findings* have receipts. A PRD whose findings were rejected
    or deferred could archive with every manifest issue still open.

    PRDs without a `## Issues` section pass through (legacy / content-only).
    """
    spec_path = cfg.repo_root / state["spec_path"]
    try:
        text = spec_path.read_text()
    except OSError as exc:
        return 2, f"{spec_path}: {exc}\n"

    if not text.startswith("---"):
        return 2, f"{spec_path}: spec missing YAML frontmatter\n"
    fm_end = text.find("\n---", 3)
    if fm_end == -1:
        return 2, f"{spec_path}: frontmatter not closed with ---\n"
    body = text[fm_end + len("\n---"):]

    # Umbrella archive gate (prd-os-spine-native): every accepted finding's
    # covered_by must name an EXISTING phase-PRD spec that is past `idea` —
    # coverage is real work, never a placeholder.
    fm = _parse_frontmatter(text)
    if fm.get("kind") == "umbrella":
        rel = fm.get("findings_path")
        if rel:
            findings_file = cfg.repo_root / rel
            if findings_file.is_file():
                with findings_file.open() as fh:
                    for raw in fh:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not (isinstance(rec, dict)
                                and rec.get("disposition") == "accepted"):
                            continue
                        target = (rec.get("covered_by") or "").strip()
                        target_path = cfg.prds_dir / f"{target}.md"
                        if not target or not target_path.is_file():
                            return 2, (
                                f"archive blocked: umbrella finding {rec.get('id')} "
                                f"covered_by {target!r} does not name an existing "
                                "PRD spec.\n")
                        t_fm = _parse_frontmatter(target_path.read_text())
                        if t_fm.get("status") == "idea":
                            return 2, (
                                f"archive blocked: umbrella finding {rec.get('id')} "
                                f"covered_by {target} is still `idea` — coverage "
                                "must be real work, not a placeholder.\n")
                        if t_fm.get("kind") == "umbrella":
                            return 2, (
                                f"archive blocked: umbrella finding {rec.get('id')} "
                                f"covered_by {target} is itself an umbrella — "
                                "coverage must name a concrete phase PRD.\n")
        return 0, ""

    issues_match = re.search(r"(?m)^##\s+Issues\s*$", body)
    if not issues_match:
        return 0, ""
    rest = body[issues_match.end():]
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", rest, flags=re.DOTALL)
    if not fence:
        return 0, ""
    try:
        entries = json.loads(fence.group(1))
    except json.JSONDecodeError as exc:
        return 2, f"archive blocked: issues manifest is not valid JSON ({exc}).\n"
    if not isinstance(entries, list):
        return 2, "archive blocked: issues manifest must be a JSON array.\n"

    open_issues: list[tuple[str, str]] = []
    missing_specs: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return 2, f"archive blocked: manifest entry #{index} must be a JSON object.\n"
        issue_id = entry.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            return 2, (
                f"archive blocked: manifest entry #{index} is missing a non-empty "
                "`id` string.\n"
            )
        issue_path = cfg.issues_dir / f"{issue_id}.md"
        if not issue_path.is_file():
            missing_specs.append(issue_id)
            continue
        try:
            issue_text = issue_path.read_text()
        except OSError as exc:
            return 2, f"{issue_path}: {exc}\n"
        if not issue_text.startswith("---"):
            return 2, f"{issue_path}: spec missing YAML frontmatter\n"
        i_end = issue_text.find("\n---", 3)
        if i_end == -1:
            return 2, f"{issue_path}: frontmatter not closed with ---\n"
        block = issue_text[3:i_end].strip("\n")
        status: str | None = None
        for raw in block.splitlines():
            line = raw.rstrip()
            if line.startswith("status:"):
                status = line.partition(":")[2].strip()
                break
        if status != "closed":
            open_issues.append((issue_id, status or "<missing>"))
        else:
            # A hand-edited `status: closed` without a close receipt skipped
            # the contract enforcement (deletes grep + gate registration) —
            # only issue_runner.close writes receipts, and close enforces
            # the contract first (codex blocker).
            receipt_ids = _load_receipt_issue_ids(cfg.receipts_path)
            if issue_id not in receipt_ids:
                return 2, (
                    f"archive blocked: issue {issue_id} is marked closed but "
                    "has NO close receipt — a hand-edited status bypasses the "
                    "spine contract. Re-open and close via issue_runner.\n")

    if missing_specs:
        lines = [
            "archive blocked: PRD manifest references issue specs that do not "
            "exist on disk:"
        ]
        for iid in missing_specs:
            lines.append(f"  - {iid} (expected at {_relpath(cfg, cfg.issues_dir / (iid + '.md'))})")
        lines.append(
            "(run `prd_split.py` to materialize the manifest, or fix the entries.)"
        )
        return 2, "\n".join(lines) + "\n"

    if open_issues:
        lines = [
            "archive blocked: PRD manifest issues are not all closed:"
        ]
        for iid, status in open_issues:
            lines.append(f"  - {iid}: status={status}")
        lines.append(
            "(close each issue with `/issue-closeout` before archiving the PRD.)"
        )
        return 2, "\n".join(lines) + "\n"

    return 0, ""


def _archive_coverage_gate(cfg: Config, state: dict) -> tuple[int, str]:
    """G4: every accepted finding must have a matching closed-issue receipt.

    Rejected findings pass through. Deferred findings require a non-empty
    `rationale`; warnings (>30 days old) go to stderr but don't block.
    """
    prd_id = state.get("prd_id")
    if not prd_id:
        return 2, "archive blocked: no active PRD\n"

    spec_path = cfg.repo_root / state["spec_path"]
    try:
        fm = _parse_frontmatter(spec_path.read_text())
    except ValueError as exc:
        return 2, f"{spec_path}: {exc}\n"

    rel = fm.get("findings_path")
    if not rel:
        return 0, ""
    findings_file = cfg.repo_root / rel
    if not findings_file.is_file():
        return 0, ""

    accepted: list[str] = []
    deferred: list[tuple[str, str, str]] = []  # (fid, rationale, created_at)
    with findings_file.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                return 2, (
                    f"{findings_file}:{lineno}: invalid JSONL ({exc}). "
                    "Fix or remove the line before archiving.\n"
                )
            if not isinstance(rec, dict):
                return 2, f"{findings_file}:{lineno}: record must be an object\n"
            disposition = rec.get("disposition")
            fid = rec.get("id") or f"line-{lineno}"
            if disposition == "accepted":
                if fm.get("kind") == "umbrella" and (rec.get("covered_by") or "").strip():
                    # Umbrella findings are owned by phase PRDs (covered_by),
                    # not by this PRD's issues — the manifest gate verifies
                    # the coverage target exists; no receipt expected here.
                    continue
                if isinstance(fid, str):
                    accepted.append(fid)
            elif disposition == "deferred":
                rationale = (rec.get("rationale") or "").strip()
                created_at = rec.get("created_at") or ""
                deferred.append((fid, rationale, created_at))
            # rejected / other: pass through

    covered = _load_receipts_for_prd(cfg.receipts_path, prd_id)
    missing = [fid for fid in accepted if fid not in covered]
    if missing:
        lines = [
            "archive blocked: accepted findings missing an issue receipt for "
            f"prd_id={prd_id!r}:"
        ]
        for fid in missing:
            lines.append(f"  - {fid}")
        lines.append(
            f"(receipts source: {_relpath(cfg, cfg.receipts_path)}; "
            "close each issue with `/issue-closeout` to record a receipt.)"
        )
        return 2, "\n".join(lines) + "\n"

    empty_rationale = [fid for fid, rationale, _ in deferred if not rationale]
    if empty_rationale:
        lines = ["archive blocked: deferred findings without rationale:"]
        for fid in empty_rationale:
            lines.append(f"  - {fid}")
        return 2, "\n".join(lines) + "\n"

    now = datetime.now(timezone.utc)
    stale = []
    for fid, _, created_at in deferred:
        ts = _parse_iso_z(created_at) if isinstance(created_at, str) else None
        if ts and (now - ts).days > DEFERRED_WARN_DAYS:
            stale.append((fid, created_at))
    if stale:
        warn_lines = [
            f"archive warning: deferred findings older than {DEFERRED_WARN_DAYS} days:"
        ]
        for fid, created_at in stale:
            warn_lines.append(f"  - {fid} (created_at={created_at})")
        sys.stderr.write("\n".join(warn_lines) + "\n")

    return 0, ""


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Gate registry (prd-os-spine-native): permanent bypass proofs
# ---------------------------------------------------------------------------


def _gates_path(cfg: Config):
    return cfg.repo_root / ".prd-os" / "gates.jsonl"


GATE_LIFECYCLES = (
    "regression",
    "historical-receipt",
    "retired",
    "external",
)
LEGACY_GATE_LIFECYCLE = "historical-receipt"


def _gate_lifecycle(record: dict) -> str:
    lifecycle = record.get("lifecycle", LEGACY_GATE_LIFECYCLE)
    if lifecycle not in GATE_LIFECYCLES:
        gate_id = record.get("gate_id", "<missing gate_id>")
        raise ValueError(
            f"gate {gate_id!r} has invalid lifecycle {lifecycle!r}; "
            f"expected one of {', '.join(GATE_LIFECYCLES)}"
        )
    return lifecycle


def gate_register(
    cfg: Config,
    *,
    prd_id: str,
    issue_id: str,
    command: str,
    lifecycle: str = LEGACY_GATE_LIFECYCLE,
) -> dict:
    """Idempotent append: gate_id = <issue_id>-<sha256(command)[:8]>; an
    existing gate_id is a no-op. Single-line write + flush (atomic at line
    granularity); raises on I/O failure so the CALLER (dsse close) aborts."""
    import hashlib as _hashlib
    if lifecycle not in GATE_LIFECYCLES:
        raise ValueError(
            f"invalid gate lifecycle {lifecycle!r}; "
            f"expected one of {', '.join(GATE_LIFECYCLES)}"
        )
    gate_id = f"{issue_id}-{_hashlib.sha256(command.encode()).hexdigest()[:8]}"
    path = _gates_path(cfg)
    if path.is_file():
        for raw in path.read_text().splitlines():
            try:
                existing = json.loads(raw)
                if existing.get("gate_id") == gate_id:
                    existing_lifecycle = _gate_lifecycle(existing)
                    if existing_lifecycle != lifecycle:
                        raise ValueError(
                            f"gate {gate_id!r} already registered as "
                            f"{existing_lifecycle!r}, not {lifecycle!r}"
                        )
                    return {"gate_id": gate_id, "registered": False}
            except json.JSONDecodeError:
                continue
    record = {"gate_id": gate_id, "prd_id": prd_id, "issue_id": issue_id,
              "command": command,
              "lifecycle": lifecycle,
              "registered_at": _now_iso()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
    return {"gate_id": gate_id, "registered": True}


# ---------------------------------------------------------------------------
# Spillover ledger (prd-os-spine-native): out-of-scope findings, durable + gated
#
# spillover-skip -- file-level ack for the fable-discipline deferral lint.
# That lint flags the phrase "out-of-scope" in code as an UNCAPTURED deferral.
# This file is the capture MECHANISM, so its own docstrings and --help text
# necessarily name the thing it captures; every hit here is the vocabulary of
# the ledger, not a finding being written down and walked away from. Acked at
# file level (the lint's own convention, one marker per file) rather than by
# rewording the API help, which would make the command harder to understand in
# order to satisfy a detector aimed at a different shape of line.
# ---------------------------------------------------------------------------
# The scar: a finding marked `deferred`, or an adjacent issue "mentioned" in
# prose, used to be terminal — it vanished and nobody (least of all an operator
# with ADHD) revisited it. The ledger makes capture a file write, and the
# standing gate (gates run) stays RED while any item is `open`, so forgetting an
# item is a permanently red gate, not a silent drop. Resolution requires a real
# CLOSED issue (or an explicitly recorded void), never a hand flip.


_SPILLOVER_ROOT_CACHE: dict = {}


def _ledger_root(repo_root):
    """The ONE directory the spillover ledger lives under, shared by every worktree.

    WHY THIS IS NOT JUST repo_root (sp-bc42f1d3, scale in sp-10ea7b66).
    `.gitignore` excludes `*.jsonl`, so the ledger is never committed and never
    shared through git. Resolving it from the per-worktree root therefore gave
    EVERY worktree its own private ledger. Measured 2026-07-30: 26 worktree
    ledgers held 71 open findings that did not exist in the main checkout's copy,
    so `gates run` from main was green about work it structurally could not see.
    That is the no-orphan-findings enforcement of last resort failing silently,
    which is worse than not having it -- it reported safety it could not provide.

    `--git-common-dir` is the shared `.git` for the whole worktree set, so its
    parent is the main checkout no matter which worktree we are called from. One
    ledger, one writer, one thing the gate reads. Same load-path lesson as the
    marketplace-clone scar: the file you wrote must be the file the runtime reads.

    Falls back to repo_root when git cannot answer (not a repo, git missing, a
    bare or otherwise odd layout). A capture must never be lost to a failed
    lookup -- writing to the local root is degraded but recoverable, while
    raising here would turn a git hiccup into a dropped finding.
    """
    key = str(repo_root)
    if key in _SPILLOVER_ROOT_CACHE:
        return _SPILLOVER_ROOT_CACHE[key]
    # Local import and `Path`, matching this file's existing convention (see the
    # `import subprocess as _subprocess` call sites). Written as bare
    # `subprocess.run` / `pathlib.Path` the first time, which are NameErrors that
    # the except-clause below would have SWALLOWED -- the function would have
    # returned repo_root every time and the fix would have looked correct while
    # changing nothing. Caught by the worktree case in test_spillover_ledger_root.py.
    import subprocess as _subprocess
    root = repo_root
    try:
        out = _subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = Path(repo_root) / common
            parent = common.resolve().parent
            # Only trust it if it really looks like a checkout root. A bare repo's
            # parent is an arbitrary directory, and silently relocating the ledger
            # there would be a new invisible-ledger bug wearing the fix's clothes.
            if (parent / ".git").exists():
                root = parent
    except Exception:
        pass
    _SPILLOVER_ROOT_CACHE[key] = root
    return root


def _spillover_path(cfg: Config):
    return _ledger_root(cfg.repo_root) / ".prd-os" / "spillover.jsonl"


def _read_spillover(cfg: Config) -> dict:
    """Append-only ledger read with last-write-wins per id (the crash-safe
    pattern: state changes append a new record, reads collapse to the latest)."""
    path = _spillover_path(cfg)
    items: dict = {}
    if path.is_file():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("id"):
                items[rec["id"]] = rec
    return items


def _spillover_open(cfg: Config) -> list:
    return [r for r in _read_spillover(cfg).values() if r.get("status") == "open"]


def _spillover_append(cfg: Config, record: dict) -> None:
    path = _spillover_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()


def _issue_is_closed(cfg: Config, issue_id: str) -> bool:
    """A spillover item may only resolve against an issue that actually closed.
    The deterministic signal is the issue spec's frontmatter `status: closed`,
    which issue_runner sets only after every receipt verified."""
    spec = cfg.issues_dir / f"{issue_id}.md"
    if not spec.is_file():
        return False
    for line in spec.read_text().splitlines():
        s = line.strip()
        if s.startswith("status:"):
            return s.split(":", 1)[1].strip() == "closed"
    return False


class LinearRefError(Exception):
    """A resolution reference could not be PROVEN closed.

    Covers every unverifiable case alike — no API key, no network, no such
    issue, issue still open. They collapse to one class on purpose: the caller's
    only correct response to any of them is to refuse, so a code path that could
    tell them apart would only invite one of them being downgraded to a warning.
    """


LINEAR_API_URL = "https://api.linear.app/graphql"
# Linear identifiers are TEAMKEY-number. Anything else is a local spec id (or a
# typo), and must never become a live lookup.
LINEAR_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}-\d+$")
LINEAR_STATE_QUERY = "query($id: String!) { issue(id: $id) { state { name type } } }"


def _linear_api_key() -> str:
    """The same auth path linear-sync.py uses: env first, then the 0600 secret.

    Read here rather than imported from linear-sync.py because prd-os ships as a
    standalone plugin into repos with no q-system tree. What is shared is the
    CONVENTION (this env name, this file path), not code that could drift.
    """
    env = os.environ.get("KIPI_LINEAR_API_KEY", "").strip()
    if env:
        return env
    path = Path(os.path.expanduser("~/.config/kipi/linear-api-key"))
    if not path.is_file():
        raise LinearRefError(
            "closure cannot be verified: no Linear API key. Create one at "
            "https://linear.app/settings/api then:\n"
            f"  umask 077 && printf '%s' '<key>' > {path}\n"
            "or export KIPI_LINEAR_API_KEY. An unverified reference is never recorded")
    key = path.read_text().strip()
    if not key:
        raise LinearRefError(f"closure cannot be verified: {path} is empty")
    return key


def _linear_issue_state(identifier: str) -> dict:
    """The `{name, type}` of a Linear issue's workflow state.

    Raises LinearRefError for anything short of a definite answer, including an
    unreachable API — offline is a refusal, not an assumption.
    """
    import urllib.error
    import urllib.request

    body = json.dumps({"query": LINEAR_STATE_QUERY, "variables": {"id": identifier}}).encode("utf-8")
    request = urllib.request.Request(
        LINEAR_API_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": _linear_api_key()},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LinearRefError(f"Linear returned HTTP {exc.code} for {identifier}") from exc
    except urllib.error.URLError as exc:
        raise LinearRefError(f"cannot reach Linear to verify {identifier}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise LinearRefError(f"Linear sent a non-JSON answer for {identifier}: {exc}") from exc
    # Linear answers HTTP 200 with an `errors` array for application-level
    # failures, so a status-code-only check would read a failed lookup as a
    # verified one -- the exact shape of bug this command exists to prevent.
    if payload.get("errors"):
        raise LinearRefError(
            f"Linear rejected the lookup for {identifier}: {json.dumps(payload['errors'])[:200]}")
    issue = (payload.get("data") or {}).get("issue")
    if not isinstance(issue, dict) or not isinstance(issue.get("state"), dict):
        raise LinearRefError(f"Linear has no issue {identifier}")
    return issue["state"]


def _verify_resolution_ref(cfg: Config, ref: str) -> dict:
    """Prove `ref` names a closed issue; return the evidence that proved it.

    Raises LinearRefError with an operator-readable reason when closure cannot
    be proven. Nothing here accepts the operator's word: the returned evidence
    describes what the TRACKER said, which is why a resolution still cannot be
    hand-flipped through this command.

    Local specs answer first. A repo that tracks its own issues under
    `.prd-os/issues/` keeps resolving offline even when its ids look like Linear
    keys; the Linear path only opens for a ref this repo has no spec for.
    """
    local_spec = cfg.issues_dir / f"{ref}.md"
    if local_spec.is_file() or not LINEAR_ID_RE.match(ref):
        if _issue_is_closed(cfg, ref):
            return {"resolution_tracker": "prd-os"}
        raise LinearRefError(
            f"issue '{ref}' is not closed. Build it through the normal "
            "reproducer-first issue flow and close it first.")
    state = _linear_issue_state(ref)
    if state.get("type") != "completed":
        # `canceled` lands here too, and should: a canceled issue shipped no fix,
        # so clearing the item with it would green the gate on work that never
        # happened. The honest exit for a non-item is --void, which records why.
        raise LinearRefError(
            f"Linear issue '{ref}' is not completed (state: {state.get('name')}). "
            "Close it first, or record a non-item with --void <reason>.")
    return {
        "resolution_tracker": "linear",
        "resolution_verified_state": state.get("name"),
        "resolution_verified_at": _now_iso(),
    }


# A spec in one of these states is finished work. Finished work must not carry
# a live amnesty. Spelled both ways because specs are hand-edited.
_TERMINAL_SPEC_STATES = frozenset({
    "archived", "closed", "cancelled", "canceled", "done", "abandoned",
})


def _spec_status(spec: Path) -> str | None:
    """The `status:` frontmatter value, lowercased, or None if it has none."""
    try:
        lines = spec.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        s = line.strip()
        if s.startswith("status:"):
            return s.split(":", 1)[1].strip().strip("\"'").lower()
    return None


def _is_git_tracked(repo_root, spec: Path) -> bool:
    """Whether git has this path committed. False for every unprovable case.

    Durability, not tidiness: a spec that exists only in one working tree
    vanishes on a fresh checkout. `_enforce_wiring_contract` (issue_runner)
    already blocks issue close on exactly this test, after a created-but-unstaged
    file passed every gate and then disappeared. A unit of work that can narrow a
    fleet safety gate is held to the same bar.
    """
    import subprocess as _subprocess
    try:
        out = _subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(spec)],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
    except Exception:
        # git missing, not a repo, timeout: unprovable. Refusing here costs a
        # red gate; guessing True would hand out the amnesty this exists to stop.
        return False
    return out.returncode == 0


def _scope_is_live(cfg: Config, scope_id: str, spec_dir: Path) -> bool:
    """Whether `scope_id` is PROVABLY a live, durable unit of work (ASK-527).

    Three independent proofs, all deterministic and none of them a clock: the
    spec exists, git has it tracked, and its status is not terminal. Any one
    failing -- or being unanswerable -- means no scope, which falls through to
    the fail-closed path in cmd_gates where every open item blocks.
    """
    spec = spec_dir / f"{scope_id}.md"
    # No separate existence check: `git ls-files --error-unmatch` already answers
    # False for a path that is not there, and a redundant branch here would be a
    # line no mutation test can kill. The distinction between "missing" and
    # "untracked" is preserved where it earns its keep -- the operator-facing
    # message in _scope_refusal_note.
    if not _is_git_tracked(cfg.repo_root, spec):
        return False
    status = _spec_status(spec)
    # A spec with no status frontmatter is unprovable, not permissive.
    return status is not None and status not in _TERMINAL_SPEC_STATES


def _active_scope(cfg: Config) -> str | None:
    """The id `gates run` holds THIS run accountable for, or None.

    The active issue wins over the active PRD: an issue is the narrower unit of
    work and both state files exist at once during closeout. A DEAD active issue
    does not fall back to the PRD -- that state is inconsistent, and resolving an
    inconsistency in the direction of less enforcement is how amnesties happen.

    Returning None is not a failure, it is the fail-closed signal -- see
    cmd_gates, where no scope means every open item blocks.

    WHY LIVENESS IS PROVEN AND NOT ASSUMED (ASK-527). This used to return the id
    the state file named, full stop. Measured on kipi-system 2026-08-09: the file
    named `prd-judgment-compiler-not-deployed-2026-08-05`, still at status "idea"
    three days after it was loaded, whose spec was present on disk but never
    committed. `gates run` exited 0 over 635 open items. A forgotten draft in one
    working tree was silently granting a standing amnesty over the whole ledger --
    the same lapse the age-cutoff design was rejected for in ASK-526, through a
    different door.

    An mtime age cap was rejected: it re-introduces a clock deciding what nobody
    decided, and mtime does not survive checkout, rsync or `kipi update`, so the
    gate would flap for reasons unrelated to the work. "Last ledger write by this
    scope" was rejected as perverse -- a scope would stay alive by producing MORE
    spillover.
    """
    for path, key, spec_dir in (
        (cfg.active_issue_state_path, "issue_id", cfg.issues_dir),
        (cfg.active_prd_state_path, "prd_id", cfg.prds_dir),
    ):
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text()).get(key)
        except (json.JSONDecodeError, OSError):
            continue
        # `_empty_state()` writes the key with a None value on clear, so a
        # cleared state file must read as "no scope", not as scope "None".
        if isinstance(value, str) and value.strip():
            scope_id = value.strip()
            return scope_id if _scope_is_live(cfg, scope_id, spec_dir) else None
    return None


def _scope_refusal_note(cfg: Config) -> str | None:
    """Display-only: WHY a named active scope was refused, or None.

    A fail-closed run over a large ledger must be red for a NAMEABLE, one-command
    reason ("this spec was never committed"), not just red. A red gate whose cause
    the operator cannot see is the uninformative-roll-up defect from ASK-526
    reappearing as the cure for ASK-527.

    Deliberately separate from `_scope_is_live`: the predicate answers one
    question and is what the gate depends on, while this only builds a sentence.
    A single function returning both would make the message a load-bearing part
    of the security decision.
    """
    for path, key, spec_dir, kind in (
        (cfg.active_issue_state_path, "issue_id", cfg.issues_dir, "issue"),
        (cfg.active_prd_state_path, "prd_id", cfg.prds_dir, "PRD"),
    ):
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text()).get(key)
        except (json.JSONDecodeError, OSError):
            continue
        if not (isinstance(value, str) and value.strip()):
            continue
        sid = value.strip()
        spec = spec_dir / f"{sid}.md"
        where = _relpath(cfg, spec)
        if not spec.is_file():
            return f"active {kind} '{sid}' refused: spec {where} does not exist"
        if not _is_git_tracked(cfg.repo_root, spec):
            return (f"active {kind} '{sid}' refused: spec {where} is not git-tracked, "
                    f"so it is not a durable unit of work. Commit it, or clear the "
                    f"active state, then re-run")
        status = _spec_status(spec)
        if status is None:
            return f"active {kind} '{sid}' refused: spec {where} has no status frontmatter"
        if status in _TERMINAL_SPEC_STATES:
            return (f"active {kind} '{sid}' refused: spec status is '{status}' "
                    f"(terminal). Finished work carries no amnesty")
        return None
    return None


def _spillover_group_counts(items: list, field: str) -> list:
    """(value, count) pairs for one field, biggest group first, ties by name.

    Deterministic order matters more than it looks: this report is read to
    decide which producer to open an issue against, and a set-iteration order
    would reshuffle the priorities between two runs over the same ledger.
    """
    counts: dict = {}
    for record in items:
        value = record.get(field) or "(unset)"
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def _print_spillover_groups(items: list, field: str, heading: str) -> None:
    print(f"\nby {heading} ({len(_spillover_group_counts(items, field))} group(s)):")
    for value, count in _spillover_group_counts(items, field):
        print(f"  {count:5d}  {value}")


def cmd_spillover(cfg: Config, args) -> int:
    """add | list | check | resolve | triage — the out-of-scope finding ledger."""
    import hashlib as _hashlib
    sub = args.spillover_cmd
    if sub == "add":
        sid = args.id or f"sp-{_hashlib.sha256((args.source + args.desc).encode()).hexdigest()[:8]}"
        _spillover_append(cfg, {
            "id": sid, "source": args.source, "description": args.desc,
            "severity": args.severity, "status": "open", "created_at": _now_iso(),
        })
        print(json.dumps({"id": sid, "status": "open"}))
        return 0
    if sub == "list":
        items = list(_read_spillover(cfg).values())
        if args.open_only:
            items = [r for r in items if r.get("status") == "open"]
        if args.as_json:
            print(json.dumps(items))
        else:
            for r in items:
                print(f"[{r.get('status')}] {r['id']}: {r.get('description', '')[:80]} (src {r.get('source')})")
        return 0
    if sub == "check":
        openv = _spillover_open(cfg)
        if openv:
            for r in openv:
                sys.stderr.write(f"SPILLOVER OPEN: {r['id']}: {r.get('description', '')[:100]} (src {r.get('source')})\n")
            sys.stderr.write(
                f"{len(openv)} open spillover item(s). Resolve each against a CLOSED issue "
                f"(prd_runner.py spillover resolve <id> --resolution-ref <issue-id>) or void it "
                f"(--void <reason>). They cannot be silently dropped.\n")
            return 1
        print("no open spillover items")
        return 0
    if sub == "triage":
        # Read-only by construction: no _spillover_append call reachable from
        # here. A ledger this size (350+ open, ~50/day arriving from a handful
        # of producers) is unworkable as a flat list, but the fix is a better
        # LENS, never a bulk exit. The only two ways out of the ledger stay
        # `resolve --resolution-ref <closed-issue>` and `resolve --void`.
        openv = _spillover_open(cfg)
        if not openv:
            print("no open spillover items")
            return 0
        print(f"{len(openv)} open spillover item(s)")
        _print_spillover_groups(openv, "severity", "severity")
        _print_spillover_groups(openv, "source", "source")
        return 0
    if sub == "resolve":
        rec = _read_spillover(cfg).get(args.id)
        if not rec:
            sys.stderr.write(f"unknown spillover id: {args.id}\n")
            return 2
        if not args.resolution_ref and not args.void:
            sys.stderr.write("resolve requires --resolution-ref <issue-id> or --void <reason>\n")
            return 2
        new = dict(rec)
        if args.void:
            new.update(status="resolved", void_reason=args.void, resolved_at=_now_iso())
        else:
            try:
                evidence = _verify_resolution_ref(cfg, args.resolution_ref)
            except LinearRefError as exc:
                sys.stderr.write(f"cannot resolve {args.id}: {exc}\n")
                return 2
            new.update(status="resolved", resolution_ref=args.resolution_ref,
                       resolved_at=_now_iso(), **evidence)
            if args.evidence:
                # Operator-supplied context (PR, merge commit). Recorded for the
                # next reader, never consulted above: it is a note attached to a
                # verified resolution, not a substitute for verifying one.
                new["resolution_evidence"] = args.evidence
        _spillover_append(cfg, new)
        print(json.dumps({"id": args.id, "status": "resolved"}))
        return 0
    sys.stderr.write(f"unknown spillover subcommand: {sub}\n")
    return 2


def cmd_gates(cfg: Config, args) -> int:
    """gates list prints the registry; gates run executes regression gates from
    the repo root (operator-authored shell commands, the same trust boundary
    as required_checks), per-gate green/RED, non-zero exit on any RED.

    `run` ALSO fails on open spillover items ATTRIBUTABLE to the run's scope --
    the active issue/PRD, or everything when there is no active scope. Items
    inherited from other work are printed in the census on every run but do not
    block, so the red light means "this work left something behind" instead of
    "a backlog exists". See the block above the census for the measurement that
    forced the split and for the age-cutoff design that was rejected."""
    import subprocess as _subprocess
    import re as _re
    path = _gates_path(cfg)
    records = []
    if path.is_file():
        for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"{path}:{lineno}: invalid JSONL; fix before running gates\n")
                return 2
            try:
                record["lifecycle"] = _gate_lifecycle(record)
            except ValueError as exc:
                sys.stderr.write(f"{path}:{lineno}: {exc}\n")
                return 2
            records.append(record)
    if args.gates_cmd == "list":
        if args.lifecycle:
            records = [
                record for record in records
                if record["lifecycle"] == args.lifecycle
            ]
        print(json.dumps(records, indent=2))
        return 0
    if args.lifecycle and args.lifecycle != "regression":
        sys.stderr.write(
            "gates run only supports lifecycle 'regression'; "
            "other lifecycles are retained as non-current evidence\n"
        )
        return 2
    records = [
        record for record in records
        if record["lifecycle"] == "regression"
    ]
    failures = []
    skipped_self_ref = 0
    for rec in records:
        command = rec["command"]
        # Self-reference guard (scar 2026-06-24): a gate whose command runs
        # `gates run` re-enters this very loop and recurses without bound — each
        # level re-runs the whole registry including itself, an exponential
        # process fork bomb (observed: 160+ prd_runner processes). Such a gate is
        # the anti-pattern created when an issue's bypass_check is `gates run`
        # (the prior qep-wiring-sweep did exactly that). Skip it: a gate that runs
        # all gates can never be a meaningful member of the set it runs.
        if "prd_runner.py gates run" in command or _re.search(r"\bgates\s+run\b", command):
            skipped_self_ref += 1
            print(f"[skip] {rec['gate_id']}: self-referential `gates run` gate (not executed)")
            continue
        result = _subprocess.run(command, shell=True, cwd=cfg.repo_root,
                                 capture_output=True, text=True, timeout=900)
        status = "green" if result.returncode == 0 else "RED"
        print(f"[{status}] {rec['gate_id']}: {command[:90]}")
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            failures.append((rec["gate_id"], "\n".join(tail)))
    # Spillover verdict, scoped by ATTRIBUTION and never by the clock (ASK-526).
    #
    # WHY THIS IS NOT ONE BOOLEAN ANY MORE. This block used to append a failure
    # whenever ANY item was open, which collapsed two unrelated verdicts into
    # one exit code: "a regression gate failed" (you broke something) and "the
    # ledger is non-empty" (there is a backlog). Measured on kipi-system
    # 2026-08-08: 640 open items arriving ~50/day from 141 sources against ~4/day
    # resolved. A boolean over a queue whose arrival rate is 12x its service rate
    # is red with probability 1 forever, so the red light carried no information
    # and a genuine new regression was invisible inside it. The gate had the FORM
    # of enforcement without the function: it was continuously red across exactly
    # the period in which those 640 accumulated, and caused none of them to be
    # worked.
    #
    # WHAT WAS REJECTED. An age cutoff ("only items newer than N days block").
    # It would let this function print "no open spillover" while 640 items sat
    # open -- a gate that states something false is strictly worse than one that
    # is uninformative, and items would leave enforcement with nobody deciding,
    # which is the silent drop no-orphan-findings.md exists to prevent.
    #
    # Nothing here removes an item, changes its status, or expires it. The two
    # ways out of the ledger are still exactly resolve-against-a-closed-issue and
    # record-a-void.
    openv = _spillover_open(cfg)
    scope = args.scope or _active_scope(cfg)
    if scope:
        attributable = [r for r in openv if r.get("source") == scope]
        inherited = [r for r in openv if r.get("source") != scope]
    else:
        # Fail-closed. No active issue means no excuse: the bare `gates run`
        # that wiring-check.md tells you to run still answers for the WHOLE
        # ledger, so the scoping can never hide the tail from an audit.
        attributable, inherited = openv, []
        note = _scope_refusal_note(cfg)
        if note:
            print(f"[scope] {note}")
    if attributable:
        names = ", ".join(r["id"] for r in attributable)
        detail = "\n".join(f"  {r['id']}: {r.get('description', '')[:90]} (src {r.get('source')})"
                           for r in attributable)
        label = f"spillover[{scope}]" if scope else "spillover"
        print(f"[RED] {label}: {len(attributable)} open item(s) this work must answer for: {names}")
        failures.append((label, f"{len(attributable)} open spillover item(s):\n{detail}\n"
                                f"Resolve via `prd_runner.py spillover resolve <id> --resolution-ref <closed-issue>`."))
    # The census prints on EVERY run, red or green, passing or failing. An
    # inherited backlog that stops being PRINTED is functionally deleted for an
    # operator with ADHD, so the number leaving the blocking set must never mean
    # the number leaving the screen. `spillover triage` is the lens on it.
    census = f"[census] spillover: {len(openv)} open total"
    if inherited:
        census += (f"; {len(inherited)} inherited from other work (not attributable "
                   f"to {scope}), reported not blocking")
    print(census)
    if failures:
        for gid, tail in failures:
            sys.stderr.write(f"GATE RED: {gid}\n{tail}\n")
        return 1
    print(f"all {len(records)} regression gates green; "
          f"{len(attributable)} attributable spillover item(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="override repo root discovery")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new")
    p_new.add_argument("slug")
    p_new.add_argument("--title")
    p_new.add_argument("--owner")
    p_new.set_defaults(func=cmd_new)

    p_load = sub.add_parser("load")
    p_load.add_argument("prd_id")
    p_load.set_defaults(func=cmd_load)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p_advance = sub.add_parser("advance")
    p_advance.add_argument("new_status")
    p_advance.set_defaults(func=cmd_advance)

    sub.add_parser("archive").set_defaults(func=cmd_archive)
    sub.add_parser("clear").set_defaults(func=cmd_clear)
    p_gates = sub.add_parser("gates")
    p_gates.add_argument("gates_cmd", choices=("list", "run"))
    p_gates.add_argument("--lifecycle", choices=GATE_LIFECYCLES)
    p_gates.add_argument(
        "--scope",
        help="issue/PRD id whose spillover items block this run. Default: the "
             "active issue, then the active PRD. With NO scope the run is "
             "fail-closed and every open item blocks. Items outside the scope "
             "are always printed in the census, never expired")
    p_gates.set_defaults(func=cmd_gates)

    p_spill = sub.add_parser("spillover")
    spill_sub = p_spill.add_subparsers(dest="spillover_cmd", required=True)
    sp_add = spill_sub.add_parser("add")
    sp_add.add_argument("--source", required=True, help="originating prd-id or issue-id")
    sp_add.add_argument("--desc", required=True, help="what the out-of-scope finding is")
    sp_add.add_argument("--id", help="stable id (default: derived from source+desc)")
    sp_add.add_argument("--severity", default="minor")
    sp_list = spill_sub.add_parser("list")
    sp_list.add_argument("--open", dest="open_only", action="store_true", help="only open items")
    sp_list.add_argument("--json", dest="as_json", action="store_true")
    spill_sub.add_parser("check")
    spill_sub.add_parser("triage", help="read-only: open items grouped by severity and by source")
    sp_res = spill_sub.add_parser("resolve")
    sp_res.add_argument("id")
    sp_res.add_argument("--resolution-ref", dest="resolution_ref",
                        help="closed issue that fixed it: a local .prd-os issue-id, "
                             "or a Linear identifier (ASK-204) verified against Linear")
    sp_res.add_argument("--evidence",
                        help="auditable note recorded alongside a VERIFIED resolution "
                             "(e.g. 'PR #19 / 990d7c1'); never a substitute for closure")
    sp_res.add_argument("--void", help="record a non-item (with reason) instead of fixing")
    p_spill.set_defaults(func=cmd_spillover)

    args = parser.parse_args(argv)
    try:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        cfg = load_config(repo_root, strict=True)
    except ConfigError as exc:
        sys.stderr.write(f"prd-os config error: {exc}\n")
        return 2
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
