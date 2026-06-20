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
            "(close each issue with `issue_runner.py close` before archiving the PRD.)"
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
            "close each issue with `issue_runner.py close` to record a receipt.)"
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


def gate_register(cfg: Config, *, prd_id: str, issue_id: str, command: str) -> dict:
    """Idempotent append: gate_id = <issue_id>-<sha256(command)[:8]>; an
    existing gate_id is a no-op. Single-line write + flush (atomic at line
    granularity); raises on I/O failure so the CALLER (dsse close) aborts."""
    import hashlib as _hashlib
    gate_id = f"{issue_id}-{_hashlib.sha256(command.encode()).hexdigest()[:8]}"
    path = _gates_path(cfg)
    if path.is_file():
        for raw in path.read_text().splitlines():
            try:
                if json.loads(raw).get("gate_id") == gate_id:
                    return {"gate_id": gate_id, "registered": False}
            except json.JSONDecodeError:
                continue
    record = {"gate_id": gate_id, "prd_id": prd_id, "issue_id": issue_id,
              "command": command,
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


def _spillover_path(cfg: Config):
    return cfg.repo_root / ".prd-os" / "spillover.jsonl"


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


def cmd_spillover(cfg: Config, args) -> int:
    """add | list | check | resolve — the out-of-scope finding ledger."""
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
            if not _issue_is_closed(cfg, args.resolution_ref):
                sys.stderr.write(
                    f"cannot resolve {args.id}: issue '{args.resolution_ref}' is not closed. "
                    f"Build it through the normal reproducer-first issue flow and close it first.\n")
                return 2
            new.update(status="resolved", resolution_ref=args.resolution_ref, resolved_at=_now_iso())
        _spillover_append(cfg, new)
        print(json.dumps({"id": args.id, "status": "resolved"}))
        return 0
    sys.stderr.write(f"unknown spillover subcommand: {sub}\n")
    return 2


def cmd_gates(cfg: Config, args) -> int:
    """gates list — print the registry; gates run — execute every gate from
    the repo root (operator-authored shell commands, the same trust boundary
    as required_checks), per-gate green/RED, non-zero exit on any RED. `run`
    ALSO fails while any spillover item is open (out-of-scope findings are part
    of the standing no-bypass re-proof, so they can never be silently dropped)."""
    import subprocess as _subprocess
    path = _gates_path(cfg)
    records = []
    if path.is_file():
        for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                sys.stderr.write(f"{path}:{lineno}: invalid JSONL — fix before running gates\n")
                return 2
    if args.gates_cmd == "list":
        print(json.dumps(records, indent=2))
        return 0
    failures = []
    for rec in records:
        result = _subprocess.run(rec["command"], shell=True, cwd=cfg.repo_root,
                                 capture_output=True, text=True, timeout=900)
        status = "green" if result.returncode == 0 else "RED"
        print(f"[{status}] {rec['gate_id']}: {rec['command'][:90]}")
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            failures.append((rec["gate_id"], "\n".join(tail)))
    # Out-of-scope findings are part of the standing re-proof: an open spillover
    # item turns the gate RED until it is resolved against a closed issue.
    openv = _spillover_open(cfg)
    if openv:
        names = ", ".join(r["id"] for r in openv)
        detail = "\n".join(f"  {r['id']}: {r.get('description', '')[:90]} (src {r.get('source')})" for r in openv)
        print(f"[RED] spillover: {len(openv)} open out-of-scope item(s): {names}")
        failures.append(("spillover", f"{len(openv)} open spillover item(s):\n{detail}\n"
                                      f"Resolve via `prd_runner.py spillover resolve <id> --resolution-ref <closed-issue>`."))
    if failures:
        for gid, tail in failures:
            sys.stderr.write(f"GATE RED: {gid}\n{tail}\n")
        return 1
    print(f"all {len(records)} registered gates green; no open spillover")
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
    sp_res = spill_sub.add_parser("resolve")
    sp_res.add_argument("id")
    sp_res.add_argument("--resolution-ref", dest="resolution_ref", help="closed issue-id that fixed it")
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
