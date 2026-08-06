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
import contextlib
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ConfigError, load as load_config  # noqa: E402
from concurrency import ConcurrencyError, assert_no_active_issue  # noqa: E402
from spillover_events import (  # noqa: E402
    SpilloverLedgerError, fold_ledger_text, validate_for_append)


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
    # Strip a slug's own `prd-` before prefixing. An unconditional prefix made
    # `new prd-thing` produce `prd-prd-thing-<date>`, and the reported id is the
    # one findings_writer requires -- a caller that reused its slug got
    # "PRD spec not found" (virgin-repo run, 2026-08-05).
    base_slug = slug[4:] if slug.startswith("prd-") else slug
    prd_id = f"prd-{base_slug}-{created_at[:10]}"
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
        # Emitted on rc == 0 too: the judgment gate returns a decision-
        # disagreement WARNING alongside a passing code, and the old
        # `if rc != 0` guard would have swallowed it silently.
        if err:
            sys.stderr.write(err)
        if rc != 0:
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
    rc, err = _archive_spillover_gate(cfg, state.get("prd_id"))
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


def _archive_spillover_gate(cfg: Config, prd_id: str | None = None) -> tuple[int, str]:
    """Refuse archive while an item THIS PRD opened is still open.

    `no-orphan-findings.md` states the ledger "cannot be forgotten" and names
    `gates run` the enforcement of last resort. It was never wired into the one
    terminal step. Measured 2026-08-05 in a virgin repo: `gates run` exited 1
    GATE RED on `sp-0b8645ad` and `archive` exited 0 in the same repo, in the
    same moment. The only thing holding the line was prose in
    `commands/prd-archive.md` asking the model to check first -- prompt-only
    enforcement, which q-system/CLAUDE.md core rule 3 forbids.

    Deliberately no --force hatch: the two documented exits (resolve against a
    closed issue, or --void with a recorded reason) already cover every real
    case, and a third would be the hand-clear the rule refuses.
    """
    openv = _spillover_open(cfg)
    # SCOPED TO THIS PRD's OWN ITEMS (Codex, PR #110 round 3, with a repro).
    # Refusing on the GLOBAL ledger made archive permanently unreachable: 533
    # items carry the default `minor` severity, `gates run` correctly treats
    # them as non-blocking, and archive refused on all of them anyway. A
    # terminal step no run can ever reach is not a gate, it is a wall.
    #
    # This is what no-orphan-findings.md actually says -- "report every
    # spillover item THE WORK TOUCHED" -- not "resolve the fleet's backlog
    # before any PRD may close". The global backlog is real work; it is not
    # THIS PRD's exit condition.
    if prd_id:
        openv = [r for r in openv if r.get("source") == prd_id]
    if not openv:
        return 0, ""
    detail = "\n".join(
        f"  {r['id']}: {r.get('description', '')[:90]} (src {r.get('source')})"
        for r in openv
    )
    return 2, (
        f"refusing to archive: {len(openv)} open spillover item(s) opened by "
        f"{prd_id or 'this PRD'}\n{detail}\n"
        "Resolve each via `prd_runner.py spillover resolve <id> "
        "--resolution-ref <closed-issue>` or `--void \"<reason>\"`.\n"
    )


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
    """Every dispositioned finding in this PRD must carry a receipt.

    NO EXEMPTION, and deliberately no date logic of any kind. Three shapes all
    failed the same way. Rounds 2/7/8 of PR #101 inferred eligibility from
    `resolved_at`, a mutable strippable field. PR #102 moved the inference to
    the PRD id's creation date, and its review round matched a date-SHAPED
    suffix no calendar can produce. Then Codex found the defect underneath
    both: a PRD-creation floor exempts every FUTURE decision on an old PRD, and
    35 of 36 real PRDs predate the floor, so the gate was a near-permanent
    no-op -- the opposite of "receipts are required from here on".

    The signal was simply wrong. This gate fires when a PRD is APPROVED, and a
    PRD being approved now is being decided now, whatever date its id carries.
    So the rule is unconditional and reads no date at all.

    Measured before removing the exemption, because "a gate that cannot be
    satisfied gets switched off" is a real risk that deserved a number rather
    than a worry: of the 36 real PRDs, 21 are archived and 13 approved, so they
    can never reach this gate again. Exactly ONE is still in-review, with 13
    dispositioned findings, and its remedy is one `set-disposition` re-run per
    finding, which mints the receipt as a side effect. A bounded, one-time,
    self-service cost bought back the whole guarantee.

    Returns (exit_code, text). The text is NOT only an error: a decision-
    disagreement warning rides back with exit 0, so the caller must emit it
    regardless of the code.
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
            # Cross-check INSIDE the lock, with the read that feeds it (Codex
            # major, PR #102). It used to run after the lock was released, so a
            # concurrent and perfectly valid triage landing in that gap wrote a
            # disposition this stale ledger snapshot could not see, and approval
            # false-blocked on a missing receipt that did exist. The round-4 fix
            # locked the read; the comparison needs the same span.
            # No `since`: eligibility is unconditional now, so there is nothing
            # to date-filter.
            raw_missing, raw_drift = ([], []) if chain_errors else \
                judgment_compiler.cross_check_findings(
                    cfg, records, None, prd_id=prd_id)
        if chain_errors:
            return 2, (
                "approval blocked: the judgment ledger does not verify, so its "
                "receipts cannot be trusted as evidence:\n  "
                + "\n  ".join(chain_errors[:5])
                + ("\n  ..." if len(chain_errors) > 5 else "")
                + "\n\nRun `kipi judgment verify` for the full report.\n"
            )
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
    drift = [d for d in raw_drift if d.startswith(f"{prd_id}/")]
    # WARNING, never a block (PR #101 rounds 6-8). This compares the MUTABLE
    # findings file against the IMMUTABLE receipt, and when they disagree the
    # receipt is still the honest record of the decision -- `cmd_evaluate`,
    # which feeds the release gates, reads ONLY the ledger. Rounds 6-8 blocked
    # on it and produced two self-inflicted regressions; three of the four
    # tests guarding it existed to stop it blocking legitimate work rather than
    # to catch a real threat. A gate that false-blocks gets switched off, and
    # an off gate protects nothing. It is not dropped: `kipi judgment evaluate`
    # counts it as decision_disagreement_count and gates AUTOMATION on it.
    warning = ""
    if drift:
        warning = (
            f"WARNING: {len(drift)} finding(s) whose findings-file record "
            "disagrees with the receipt that froze the decision:\n  "
            + "\n  ".join(drift[:5])
            + ("\n  ..." if len(drift) > 5 else "")
            + "\n\nApproval is NOT blocked: the receipt is the immutable record "
              "and the ledger is what calibration reads, while the findings "
              "file is mutable operational state. Counted as "
              "decision_disagreement_count by `kipi judgment evaluate`.\n"
        )
    if missing:
        return 2, (
            f"approval blocked: {len(missing)} dispositioned finding(s) with "
            "no judgment receipt:\n  "
            + "\n  ".join(missing[:5])
            + ("\n  ..." if len(missing) > 5 else "")
            + "\n\nRe-run the disposition through findings_writer.py "
              "set-disposition so the decision is recorded, or explain the gap. "
              "Receipts are the calibration set; a hole in them is invisible "
              "later.\n"
        ) + warning
    return 0, warning


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
    if not path.is_file():
        return {}
    # FAILS CLOSED (scs-validated-event-fold). This used to be a per-line
    # `except json.JSONDecodeError: continue` plus an `if rec.get("id")` filter,
    # so an unparseable or id-less line was dropped and the fold returned
    # successfully without it. Reproducer: truncate a `blocker` record mid-line
    # and `gates run` printed "all 0 regression gates green; no blocking-severity
    # spillover" and exited 0 -- a silent way to clear the standing gate.
    #
    # The chokepoint for PRD_RUNNER'S OWN readers (gates run, spillover
    # check/list/triage/resolve/reclassify) and for findings_writer, which
    # imports these helpers.
    #
    # NARROWED after review: this comment used to claim it was the ONE reader in
    # the plugin, "which is why the validator is called here and nowhere else".
    # That is false. `judgment_compiler._resolve_one_ref` opens
    # `.prd-os/spillover.jsonl` itself and still carries the lenient
    # `except json.JSONDecodeError: continue` this issue removed here, reached
    # live via `/prd-triage --evidence spillover:<id>`. Its failure direction is
    # safe (a missed record reads as "no such item", i.e. a refusal), so it is
    # not a hole in the security property -- but the claim was load-bearing, and
    # a future reader auditing whether the ledger is strictly read would have
    # trusted it and stopped here. Second site tracked in spillover.
    # DECODE INSIDE THE GUARD. This was `path.read_text()`, so the decode
    # happened OUTSIDE fail-closed handling: a single non-UTF-8 byte raised
    # UnicodeDecodeError, which is not a SpilloverLedgerError and sailed past
    # the handler in main() as a raw traceback exiting 1 -- the same code
    # `spillover check` returns for the healthy "there are open items" state.
    # That is precisely the hole this issue exists to close, left open for one
    # corruption class because every test fixture here was ASCII.
    #
    # Explicit encoding, not the locale default: a torn write or a non-prd-os
    # writer produces arbitrary bytes, and the failure must not depend on the
    # machine's locale.
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpilloverLedgerError(
            f"{path}: byte {exc.start} is not valid UTF-8 ({exc.reason}). The "
            "ledger holds bytes no reader can decode, so it is refused rather "
            "than partially read.") from exc
    return fold_ledger_text(text, path)


def _spillover_open(cfg: Config) -> list:
    return [r for r in _read_spillover(cfg).values() if r.get("status") == "open"]


@contextlib.contextmanager
def _spillover_lock(cfg: Config):
    """Serialize read-modify-append on the ledger across PROCESSES.

    `resolve` and `reclassify` both read a record, copy it, and append the
    copy, while `_read_spillover` is last-write-wins on the WHOLE record. So
    two concurrent runs interleave as: reclassify reads (status=open), resolve
    appends (status=resolved), reclassify appends its stale copy (status=open)
    -- and the resolved item is RESURRECTED into the standing gate. Codex found
    it on PR #112 with an executed reproducer.

    This is the single-writer chokepoint rule applied where it was skipped: two
    writers to one file is a corruption waiting for a race. The lock spans the
    READ as well as the write, because a lock around the append alone still
    lets the stale copy be formed.

    A sibling .lock file rather than the ledger itself: flock on the ledger
    would be released by any unrelated reader closing its own handle.

    DEGRADES, NEVER REFUSES. Taking the lock needs to CREATE a file, so it
    needs write permission on the DIRECTORY -- while appending to the existing
    ledger only needs it on the FILE. A read-only `.prd-os` therefore turned a
    working `resolve` into a PermissionError traceback the moment this lock was
    added, and read-only sandboxes are real here (every Codex round this
    session reported one).

    So a lock we cannot take degrades to the unlocked behaviour that shipped
    for months, loudly, rather than becoming a new hard failure. The race it
    protects against costs a FALSE RED gate, which is recoverable; refusing to
    resolve at all is not. Same rule the review gate uses when Codex is down:
    degrade and say so out loud.
    """
    path = _spillover_path(cfg)
    lock_path = path.with_name(path.name + ".lock")
    fh = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = lock_path.open("w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        if fh is not None:
            fh.close()
        sys.stderr.write(
            f"WARNING: could not lock the spillover ledger ({exc}); proceeding "
            "UNLOCKED.\nA concurrent resolve/reclassify could resurrect a "
            "resolved item into the standing gate.\n")
        yield
        return
    try:
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _spillover_append(cfg: Config, record: dict) -> None:
    path = _spillover_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    # VALIDATE BEFORE WRITING (sp-940e1013). _read_spillover fails closed now,
    # so a malformed record reaching the file bricks every prd-os read until
    # someone hand-edits the ledger. This is the paired half of that change:
    # strict reads REQUIRE a strict writer. Refusal happens before the open()
    # so a rejected record leaves the file byte-identical.
    validate_for_append(record, path)
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


def _print_reclassifications(items: list) -> None:
    """Surface severity changes, and DOWNGRADES loudest.

    `reclassify` writes `reclassified_from` / `reclassify_reason` and, until
    this function existed, nothing anywhere read them. A sanctioned way to stop
    the standing gate blocking, whose use no report ever shows, is not an
    audited escape hatch -- it is an unaudited one with a paper trail nobody
    opens. Same shape as the void hatch, same requirement: a writer needs a
    reader (ASK-402, PR #112 review).

    A downgraded item is NOT invisible -- it stays open and still counts in the
    gate's reported bucket -- but the ACT of demoting it is the thing an
    operator needs to see, because that is what moved the gate.
    """
    # EXPLICIT order. The first version built this by concatenating
    # NONBLOCKING + BLOCKING, which assumed those tuples were ordered by
    # severity. They are not -- `blocker` sits at index 0 of its tuple and
    # `high` at 2 -- so `blocker -> high` reported as a RAISE and
    # `low -> minor` as a gate-affecting downgrade (Codex, PR #112, minor).
    # A membership set is not a scale; reusing one as a scale is the bug.
    rank = {s: i for i, s in enumerate(SPILLOVER_SEVERITY_ORDER)}
    changed = [r for r in items if r.get("reclassified_from")]
    if not changed:
        return
    lowered, raised = [], []
    for r in changed:
        before = rank.get((r.get("reclassified_from") or "").lower(), -1)
        after = rank.get((r.get("severity") or "").lower(), -1)
        (lowered if after < before else raised).append(r)

    def show(group, label):
        if not group:
            return
        print(f"\n{label} ({len(group)}):")
        for r in group:
            print(f"  {r['id']}: {r.get('reclassified_from')} -> "
                  f"{r.get('severity')}  ({(r.get('reclassify_reason') or '')[:70]})")

    # Lowered first and named as gate-affecting: that is the direction that
    # stops the gate blocking, so it is the direction someone must review.
    show(lowered, "severity LOWERED (these stopped blocking the gate)")
    show(raised, "severity raised")


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
        # THE DEFAULT MOVED OUT OF ARGPARSE. It used to be
        # `add_argument("--severity", default="minor")`, which is why nothing
        # downstream could tell a chosen `minor` from an unchosen one: by the
        # time this line ran, `args.severity` was the string "minor" either way
        # and the distinction had already been erased one frame up. Resolving it
        # here is what makes the provenance observable at all (ASK-430).
        # REFUSE BEFORE THE FILE IS TOUCHED (ASK-446). A gate that appends and
        # then errors is the worst of both: the row is on disk AND the caller
        # saw a failure. Same contract validate_for_append already holds.
        #
        # The bypass is deliberate and it is NOT a switch: it needs a stated
        # reason, and the reason is recorded on the row so `spillover rate` can
        # count bypasses. A hatch whose use no report shows is an unaudited
        # hatch with a paper trail nobody opens -- the lesson `reclassify`
        # already paid for (ASK-402, PR #112).
        raw_bypass = getattr(args, "unstructured", None)
        bypass = (raw_bypass or "").strip()
        if raw_bypass is not None and not bypass:
            # A BARE --unstructured would be a silent opt-out. The reason is the
            # only thing that makes this auditable instead of a switch somebody
            # flips once and forgets.
            sys.stderr.write(
                "--unstructured requires a reason explaining why this finding "
                "is not about one artifact. An unexplained bypass is the "
                "hand-clear this ledger refuses everywhere else.\n")
            return 2
        if raw_bypass is None:
            if not spillover_actionable_signals(args.desc):
                sys.stderr.write(
                    "refusing to add: the description names nothing a reader "
                    "could act on.\n"
                    "Name at least one of: a path (plugins/prd-os/scripts/"
                    "prd_runner.py), a filename, a symbol or function "
                    "(severity_source, _spillover_lock()), a command "
                    "(python3 -m pytest ...), a `code span`, or a reference "
                    "(sp-1234abcd, ASK-446).\n"
                    "This ledger's problem is that it grows: a row nobody can "
                    "act on can never leave it.\n"
                    "If the finding genuinely is not about one artifact, "
                    "re-run with --unstructured '<why>' and it is recorded and "
                    "counted.\n")
                return 2
        chosen = args.severity is not None
        _spillover_append(cfg, {
            "id": sid, "source": args.source, "description": args.desc,
            # Recorded ONLY when bypassed, so its presence is the signal. A row
            # that carries this is one somebody consciously chose to write
            # unstructured, which is a different fact from an unassessed
            # severity -- hence a separate field and NOT a `severity_source`
            # value. severity_source describes where the SEVERITY came from;
            # folding description-structure into it would corrupt the field
            # ASK-430 just shipped (my call, ASK-446).
            **({"unstructured_reason": bypass} if bypass else {}),
            "severity": args.severity if chosen else SPILLOVER_DEFAULT_SEVERITY,
            "severity_source": (SEVERITY_SOURCE_EXPLICIT if chosen
                                else SEVERITY_SOURCE_DEFAULT),
            "status": "open", "created_at": _now_iso(),
        })
        print(json.dumps({"id": sid, "status": "open"}))
        return 0
    if sub == "reclassify":
        # Correct a severity through a NEW EVENT, never a mutation. Approved
        # PRD prd-spillover-current-state-2026-07-24: "correct severity through
        # new events only", "preserve append-only history"; editing a prior
        # event is an explicit non-goal there.
        #
        # This verb did not exist, and its absence was the real blocker on the
        # backlog: 549 of 559 open items sit at the `minor` DEFAULT (untriaged,
        # not assessed), `gates run` blocks only on blocker/major/high, and
        # nothing could raise or lower an item once written.
        severity = (args.severity or "").strip().lower()
        if severity not in SPILLOVER_KNOWN_SEVERITIES:
            sys.stderr.write(
                f"--severity must be one of {SPILLOVER_KNOWN_SEVERITIES}; "
                f"got {args.severity!r}. The standing gate reads this field, so "
                "an unknown value would silently stop blocking.\n")
            return 2
        if not (args.reason or "").strip():
            sys.stderr.write(
                "--reason is required: a severity change with no stated reason "
                "is the hand-clear this ledger refuses everywhere else.\n")
            return 2
        # READ AND APPEND UNDER ONE LOCK. Reading outside it lets a concurrent
        # `resolve` land between the two and be overwritten by this stale copy.
        with _spillover_lock(cfg):
            items = _read_spillover(cfg)
            current = items.get(args.id)
            if current is None:
                sys.stderr.write(
                    f"unknown spillover id: {args.id!r}. Reclassify never creates an "
                    "item -- a typo must not invent open work.\n")
                return 2
            # Carry the whole prior record forward and move ONE field, so a
            # reclassify can never drop the description or resolve by side effect.
            new_rec = dict(current)
            prior = current.get("severity")
            new_rec.update({
                "severity": severity,
                # ASSESSED BY CONSTRUCTION: this verb requires --severity AND a
                # stated --reason, so reaching this line means somebody read the
                # item and said why. It is also the ONLY way an existing row
                # leaves `unknown` -- one item, one reason, one append-only
                # event. There is deliberately no bulk path: a mechanical pass
                # stamping a severity nobody read is the hand-clear in a
                # different coat (ASK-430 explicit non-goal).
                "severity_source": SEVERITY_SOURCE_EXPLICIT,
                "reclassified_at": _now_iso(),
                "reclassified_from": prior,
                "reclassify_reason": args.reason,
            })
            _spillover_append(cfg, new_rec)
        print(json.dumps({"id": args.id, "severity": severity,
                          "was": prior, "status": new_rec.get("status")}))
        return 0
    if sub == "rate":
        # RATE, NOT LEVEL. A gate on the total open count is permanently red,
        # which teaches everyone to step over it -- the same failure the
        # severity split was built to fix. The measurable property is
        # added-minus-resolved over a trailing window, and this REPORTS rather
        # than refuses: the moment it returns non-zero on a healthy repo it
        # becomes another number people route around (ASK-446).
        import datetime as _dt
        days = getattr(args, "days", None) or 7
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)

        def _within(stamp) -> bool:
            if not isinstance(stamp, str) or not stamp.strip():
                return False
            try:
                parsed = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                return False
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_dt.timezone.utc)
            return parsed >= cutoff

        items = list(_read_spillover(cfg).values())
        added = [r for r in items if _within(r.get("created_at"))]
        resolved = [r for r in items if _within(r.get("resolved_at"))]
        bypassed = [r for r in added if r.get("unstructured_reason")]
        # UNDATED IS PRINTED, NOT DROPPED. A row whose created_at will not parse
        # is invisible to both counts; saying so is the difference between a
        # rate and a rate-shaped number.
        undated = [r for r in items
                   if not isinstance(r.get("created_at"), str)
                   or not r.get("created_at", "").strip()]
        net = len(added) - len(resolved)
        print(f"spillover rate over {days}d: {len(added)} added, "
              f"{len(resolved)} resolved, net {net:+d} "
              f"({len(bypassed)} bypassed the inflow gate)")
        if undated:
            print(f"  {len(undated)} row(s) carry no parseable created_at and "
                  f"are in neither count")
        print(f"  {len(_spillover_open(cfg))} open in total (level, not rate: "
              f"reported for context, never gated on)")
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
        # PROVENANCE IS A GROUPING HERE TOO. `gates run` splits its report into
        # assessed / untriaged / unknown and then tells the operator to "Triage
        # with `prd_runner.py spillover triage`" -- and arriving here used to
        # drop the distinction the report had just made, at the exact moment
        # somebody acts on it. A legacy row has no key and renders as "(unset)",
        # which is the honest label: not assessed, and not a claim that nobody
        # looked (ASK-465).
        _print_spillover_groups(openv, "severity_source", "severity_source")
        _print_spillover_groups(openv, "source", "source")
        _print_reclassifications(openv)
        return 0
    if sub == "resolve":
        # Same chokepoint as reclassify. This read-modify-append was
        # ALREADY unlocked before PR #112; reclassify only added a third
        # writer to it. A `with` block, not a manual enter/exit: two of
        # the refusal paths below return early and would leak the lock.
        with _spillover_lock(cfg):
            # Same chokepoint as reclassify: this read-modify-append was already
            # unlocked before PR #112: reclassify only added a third writer to it.
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


# Severities that turn the standing gate RED. Approved PRD
# prd-spillover-current-state-2026-07-24, goal 5: "make `gates run` identify
# pre-existing debt separately from new debt". Before this, every open item was
# one undifferentiated red group; the ledger reached 550 open and the gate had
# been red for months, which teaches everyone to step over it -- strictly worse
# than no gate, because it launders "we have enforcement".
#
# `minor`/`low`/`medium` are REPORTED, never silent. The 533 sitting at the
# `minor` DEFAULT are untriaged rather than assessed, which the report says
# out loud instead of implying they were judged small.
SPILLOVER_BLOCKING_SEVERITIES = ("blocker", "major", "high")
# Everything the gate is willing to call NON-blocking. Anything outside the union
# of these two tuples is treated as BLOCKING, not as minor.
#
# Codex, PR #110 round 2, with a reproducer: `spillover add --severity critical`
# was accepted, stored verbatim, reported as "minor-or-untriaged", and the gate
# returned green. The word a human reaches for under pressure ("critical",
# "urgent", "sev1") is exactly the one the allowlist did not contain, so the
# louder the label the quieter the gate got. Fail-closed here and validate at the
# CLI: an unknown severity is a triage failure, never a silent pass (ASK-402).
SPILLOVER_NONBLOCKING_SEVERITIES = ("minor", "low", "medium")
# Least -> most severe. Separate from the membership tuples above ON PURPOSE:
# those answer "does this block?", this answers "which way did it move?", and
# conflating the two is how `blocker -> high` read as a raise.
SPILLOVER_SEVERITY_ORDER = ("low", "minor", "medium", "high", "major", "blocker")
SPILLOVER_KNOWN_SEVERITIES = (
    SPILLOVER_BLOCKING_SEVERITIES + SPILLOVER_NONBLOCKING_SEVERITIES)

# How a FINDINGS-WRITER severity maps into THIS ledger's vocabulary. Lives here,
# with the ledger it translates into, because both findings writers
# (prd-os findings_writer, kipi-dsse issue_findings) fan `deferred` findings into
# the same file and a mapping defined twice is a drift waiting to happen
# (sp-a05c37a4 records the lock version of exactly that mistake).
#
# `nit` is the load-bearing entry. It is a legal severity for BOTH writers and is
# absent from SPILLOVER_KNOWN_SEVERITIES, and `_is_blocking_severity` treats an
# unknown severity as BLOCKING -- correct and deliberate (ASK-402: `critical` used
# to read as minor and green the gate). The two facts compose badly: deferring the
# LEAST important finding a reviewer can file turned the standing gate RED
# fleet-wide until a human hand-resolved the row. The gate got louder the less the
# finding mattered.
#
# Translate at the boundary rather than widening the allowlist: `nit` is the
# findings writers' word, and the ledger should not have to learn it.
FINDING_TO_LEDGER_SEVERITY = {
    "blocker": "blocker",
    "major": "major",
    "minor": "minor",
    "nit": "minor",
}


def _is_blocking_severity(value: str) -> bool:
    """Unknown severities block. See SPILLOVER_NONBLOCKING_SEVERITIES."""
    sev = (value or "").strip().lower()
    if not sev:
        return False  # absent == the documented `minor` default, not unknown
    return sev not in SPILLOVER_NONBLOCKING_SEVERITIES


# WHERE A SEVERITY CAME FROM, which is a different question from what it is.
# `spillover add` defaults `--severity minor`, so a row nobody assessed and a row
# someone judged small were byte-identical apart from id and timestamp. That was
# survivable while `severity` was a hint for a human reading `gates run`. It is
# not survivable now: any deferred item becomes an issue worked by a machine, and
# `severity` is the ROUTING INPUT deciding whether an item ever reaches one. A
# routing rule keyed on a field indistinguishable from its own default is keying
# on nothing (ASK-430).
SEVERITY_SOURCE_EXPLICIT = "explicit"   # a human or agent passed --severity
SEVERITY_SOURCE_DEFAULT = "default"     # the flag was omitted; nobody chose
SEVERITY_SOURCE_UNKNOWN = "unknown"     # written before the field existed
SPILLOVER_DEFAULT_SEVERITY = "minor"
SEVERITY_SOURCE_KNOWN = (SEVERITY_SOURCE_EXPLICIT, SEVERITY_SOURCE_DEFAULT)


def severity_source(record: dict) -> str:
    """Provenance of `record`'s severity: explicit | default | unknown.

    MISSING MEANS UNKNOWN, NEVER ASSESSED, and that is the whole point of the
    field. Measured on the live ledger 2026-08-06: 610 open items, 589 at
    `minor`, zero carrying provenance. Defaulting a missing key to `explicit`
    here would relabel every one of those rows as examined in a single deploy
    without anyone having read one of them -- the same hand-clear this ledger
    refuses everywhere else, wearing a provenance field as a coat.

    Fails toward `unknown` on an unrecognised value, matching
    `_is_blocking_severity`'s fail-closed direction: junk in this field is not
    evidence that somebody looked.
    """
    value = record.get("severity_source")
    if isinstance(value, str) and value.strip().lower() in SEVERITY_SOURCE_KNOWN:
        return value.strip().lower()
    return SEVERITY_SOURCE_UNKNOWN


# THE INFLOW GATE (ASK-446). The ledger grows without bound and no amount of
# triage changes that: inflow is automated (every deferred finding fans out),
# outflow is manual. Measured 2026-08-06: 574 -> 590 open during a single
# session that was actively RESOLVING items.
#
# A slice of the ledger is not untriaged because nobody looked. It is
# UNTRIAGEABLE because nothing actionable was written down at write time. So the
# gate sits on the WRITE path, the same shape as evidence_ledger.py refusing a
# row with no command and no result.
#
# CALIBRATED READ-ONLY AGAINST THE LIVE LEDGER before it was written, 603 open
# non-blocking items:
#   - names no FILE ARTIFACT (path or filename):  49 (8.1%)
#   - names NOTHING by the rule below:             6 (1.0%)
# ASK-446 quotes "77 of 571 (13.5%)". That is the FILE-ARTIFACT measure, not
# this rule. Recorded so nobody reads this gate as reclaiming 13.5% of the
# ledger -- it does not. Its value is the rows never written from here on.
#
# WHY HYPHENATED NAMES ARE NOT A SIGNAL, though `voice-lint` and
# `test-severity-floor` are real script names in the refused set: a hyphenated
# lowercase token is shape-identical to ordinary English ("read-only",
# "fleet-wide", "per-entry"). Accepting that shape accepts essentially every
# description and turns the gate into a filter with an opinion. The author's fix
# is to write the extension or backtick it, which is the capture habit this gate
# exists to teach -- and `--unstructured` is there for when it genuinely is not
# about one artifact.
SPILLOVER_ACTIONABLE_SIGNALS = (
    ("path", re.compile(r"[\w.\-]+/[\w.\-/]+")),
    ("filename", re.compile(
        r"\b[\w\-]+\.(?:py|sh|js|ts|tsx|json|jsonl|md|ya?ml|toml|html|css|sql"
        r"|txt|plist|cfg|ini)\b")),
    ("call", re.compile(r"\b\w+\(\)|\b\w+\.\w+\(")),
    ("code span", re.compile(r"`[^`]+`")),
    # snake_case / SCREAMING_SNAKE / lowerCamel / UpperCamel. All four are
    # shapes ordinary prose does not produce by accident.
    ("symbol", re.compile(
        r"\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+\b"
        r"|\b[a-z]+[A-Z]\w*\b"
        r"|\b[A-Z][a-z]+[A-Z]\w*\b")),
    ("command", re.compile(
        r"\b(?:python3?|bash|sh|git|npm|npx|pytest|make|curl|rg|grep"
        r"|launchctl|codex|claude)\s+\S")),
    ("reference", re.compile(
        r"\b(?:sp-[0-9a-f]{8}|[A-Z][A-Z0-9]{1,9}-\d+|PR #\d+)\b")),
)


def spillover_actionable_signals(text: str) -> tuple:
    """Which actionable signals a description carries. Empty tuple == refuse."""
    body = text or ""
    return tuple(name for name, rx in SPILLOVER_ACTIONABLE_SIGNALS
                 if rx.search(body))


def spillover_provenance_split(items: list) -> dict:
    """Partition items into assessed / never_triaged / unknown.

    A FUNCTION rather than a formatted report line, because there are now two
    consumers and only one of them reads prose. `gates run` prints it; the
    edit-time ratchet (`spillover-ratchet.py`, ASK-457) routes on it, and that
    one decides whether an item ever reaches a machine at all.

    It lives HERE because prd-os owns this ledger and therefore owns its
    vocabulary -- the same reason FINDING_TO_LEDGER_SEVERITY sits in this file
    rather than in the two findings writers that feed it. The import direction is
    load-bearing: a consumer imports from the owner. prd-os pulling a severity
    vocabulary back out of kipi-dsse or q-system to avoid a drift would only
    trade one derivation split for a worse one.

    Every input lands in exactly one bucket. A consumer iterating the buckets
    must not silently drop a row -- the ratchet's `severity == "minor"` literal
    drops all 9 open low/medium items today, which is sp-61faebb3, filed against
    that file rather than fixed from this one.
    """
    split = {"assessed": [], "never_triaged": [], "unknown": []}
    bucket = {
        SEVERITY_SOURCE_EXPLICIT: "assessed",
        SEVERITY_SOURCE_DEFAULT: "never_triaged",
        SEVERITY_SOURCE_UNKNOWN: "unknown",
    }
    for record in items:
        split[bucket[severity_source(record)]].append(record)
    return split


def cmd_gates(cfg: Config, args) -> int:
    """gates list prints the registry; gates run executes regression gates from
    the repo root (operator-authored shell commands, the same trust boundary
    as required_checks), per-gate green/RED, non-zero exit on any RED. `run`
    ALSO fails while any spillover item is open (out-of-scope findings are part
    of the standing no-bypass re-proof, so they can never be silently dropped)."""
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
    # Out-of-scope findings are part of the standing re-proof: an open spillover
    # item turns the gate RED until it is resolved against a closed issue.
    openv = _spillover_open(cfg)
    blocking = [r for r in openv if _is_blocking_severity(r.get("severity"))]
    reported = [r for r in openv if r not in blocking]
    if blocking:
        names = ", ".join(r["id"] for r in blocking)
        detail = "\n".join(f"  {r['id']} [{r.get('severity')}]: {r.get('description', '')[:90]} (src {r.get('source')})" for r in blocking)
        print(f"[RED] spillover: {len(blocking)} open blocking-severity item(s): {names}")
        failures.append(("spillover", f"{len(blocking)} open blocking-severity spillover item(s):\n{detail}\n"
                                      f"Resolve via `prd_runner.py spillover resolve <id> --resolution-ref <closed-issue>`."))
    if reported:
        # Reported, never silent. These do not block, but a bucket nobody can
        # see is how 533 of them accumulated. `--severity` DEFAULTS to minor, so
        # a defaulted item is indistinguishable from one assessed as minor --
        # the label says "untriaged" rather than laundering "nobody looked" as
        # "we judged it small".
        ids = ", ".join(r["id"] for r in reported[:10])
        more = f" (+{len(reported) - 10} more)" if len(reported) > 10 else ""
        # SPLIT, because one number answered two different questions. This
        # printed "N open minor-or-untriaged item(s)" -- the founder's standing
        # complaint is "550 sit at minor, untriaged" and this line could neither
        # prove it nor refute it, because a defaulted severity and an assessed
        # one were the same bytes. Three buckets, and `unknown` is its own rather
        # than folded into either: folding it into assessed launders ~610
        # unexamined rows, and folding it into never-triaged asserts nobody
        # looked, which is equally unobserved (ASK-430).
        split = spillover_provenance_split(reported)
        print(f"[REPORT] spillover: {len(reported)} open non-blocking "
              f"item(s): {len(split['assessed'])} assessed, "
              # "untriaged", not "never triaged": test_spillover.py's
              # `test_the_report_does_not_call_untriaged_items_minor` holds this
              # exact word, guarding the property that the report never presents
              # a DEFAULT as a judgement. Same property this split sharpens, so
              # the vocabulary matches rather than forking.
              f"{len(split['never_triaged'])} untriaged (severity defaulted), "
              f"{len(split['unknown'])} unknown provenance "
              f"(pre-dates severity_source): {ids}{more}")
        print("  Triage with `prd_runner.py spillover triage`; raise one with "
              "`spillover add --severity major|blocker`. An `unknown` row moves "
              "to assessed only via `spillover reclassify <id> --severity X "
              "--reason ...` -- one item, one reason, never a bulk pass.")
    if failures:
        for gid, tail in failures:
            sys.stderr.write(f"GATE RED: {gid}\n{tail}\n")
        return 1
    print(f"all {len(records)} regression gates green; "
          f"no blocking-severity spillover")
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
    p_gates.set_defaults(func=cmd_gates)

    p_spill = sub.add_parser("spillover")
    spill_sub = p_spill.add_subparsers(dest="spillover_cmd", required=True)
    sp_add = spill_sub.add_parser("add")
    sp_add.add_argument("--source", required=True, help="originating prd-id or issue-id")
    sp_add.add_argument("--desc", required=True, help="what the out-of-scope finding is")
    sp_add.add_argument("--id", help="stable id (default: derived from source+desc)")
    # choices, so the CLI refuses an unrecognized severity at the door rather
    # than storing it and letting the gate mis-bucket it (Codex, PR #110 r2).
    # default=None, NOT "minor". The value still defaults to minor -- but it is
    # resolved in cmd_spillover so the code can see whether the operator chose
    # it. argparse filling the default in here is what erased the distinction
    # (ASK-430); `choices` still refuses an unknown value at the door, and
    # argparse does not validate a default against `choices`, so None is safe.
    sp_add.add_argument("--severity", default=None,
                        choices=SPILLOVER_KNOWN_SEVERITIES)
    # The inflow gate's recorded bypass (ASK-446). Takes a REASON, never a bare
    # flag: `default=None` distinguishes "not passed" from "passed empty", and
    # the empty case is refused rather than treated as absent.
    sp_add.add_argument("--unstructured", default=None,
                        help="record why this finding names no concrete "
                             "artifact; bypasses the inflow gate and is counted "
                             "by `spillover rate`")
    sp_rate = spill_sub.add_parser(
        "rate", help="added minus resolved over a trailing window (rate, not level)")
    sp_rate.add_argument("--days", type=int, default=7)
    sp_list = spill_sub.add_parser("list")
    sp_list.add_argument("--open", dest="open_only", action="store_true", help="only open items")
    sp_list.add_argument("--json", dest="as_json", action="store_true")
    sp_recl = spill_sub.add_parser(
        "reclassify", help="correct an item's severity via a new append-only event")
    sp_recl.add_argument("id")
    sp_recl.add_argument("--severity", required=True)
    sp_recl.add_argument("--reason", required=True,
                         help="why the severity is wrong; recorded on the event")

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
    try:
        return args.func(cfg, args)
    except SpilloverLedgerError as exc:
        # An unreadable ledger is an OPERATOR-ACTIONABLE refusal, not a crash.
        # Caught at the one dispatch point so every subcommand that reads the
        # ledger reports it identically.
        #
        # WHAT THIS ACTUALLY BUYS, stated narrowly after review called the
        # earlier wording an overclaim: a refusal instead of a traceback, with
        # the cause on stderr. It does NOT give a caller a unique exit code for
        # "ledger corrupt" -- exit 2 is already returned for unknown spillover
        # id, invalid --severity, missing --reason, missing --resolution-ref,
        # LinearRefError, unknown subcommand, config error and a malformed
        # gates registry. A machine caller still has to read stderr to tell
        # them apart. The win is only that exit 1 no longer collides with
        # `spillover check`'s healthy "there are open items" result.
        sys.stderr.write(f"spillover ledger unreadable: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
