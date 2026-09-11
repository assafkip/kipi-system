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
import shutil
import subprocess
import tempfile
import os
import re
import shlex
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

    Deliberately no --force hatch. There are three documented exits (resolve
    against a closed issue, resolve against a MERGED commit that names the item,
    or --void with a recorded reason) and each is evidence-bound; a --force would
    be the hand-clear the rule refuses.

    The third arrived with sp-8c0b2d87, which measured what the original claim
    ("two exits cover every real case") got wrong: an item fixed OUTSIDE a PRD
    manifest had no closed issue to point at and was not voidable, so archive
    refused forever on work that was already merged.
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
        "Resolve each via `prd_runner.py spillover resolve <id>` with one of: "
        "`--resolution-ref <closed-issue>`, `--resolution-commit <merged-sha>`, "
        "`--resolution-proof '<cmd with {tree}>' --broken-at <sha>`, or "
        "`--void \"<reason>\"`.\n"
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
    """finding_ids whose LATEST receipt event is a close (reopen-aware, ASK-988).

    State resolves by event timestamp via _parse_iso_z, never by physical line
    order: a union merge can interleave appended rows, and a reopened finding
    must not satisfy coverage because its old close row still exists.
    """
    latest: dict[str, tuple[datetime, bool]] = {}
    if not path.is_file():
        return set()
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
            if not (isinstance(fid, str) and fid):
                continue
            if rec.get("reopened_at"):
                ts, is_close = _parse_iso_z(rec["reopened_at"]), False
            elif rec.get("closed_at"):
                ts, is_close = _parse_iso_z(rec["closed_at"]), True
            else:
                continue
            if ts is None:
                continue  # an unparseable timestamp proves nothing either way
            prev = latest.get(fid)
            # ASK-988 round 6: identical timestamps tie-break to REOPEN, never
            # to physical ledger order (see accept-rate.py for the reasoning).
            if (prev is None or ts > prev[0]
                    or (ts == prev[0] and not is_close)):
                latest[fid] = (ts, is_close)
    return {fid for fid, (_ts, is_close) in latest.items() if is_close}


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


def _reject_unrunnable_gate(command: str) -> None:
    """Refuse a gate whose command cannot run. Validated AT THE DOOR.

    Scar 2026-08-24 (ASK-1040), measured by executing all 47 registered gates:
    12 were not runnable at all. SEVEN held PROSE in the command slot -- the
    shell was being asked to run `check:the`, `check:adding`, `asserting` --
    because somebody wrote a DESCRIPTION of the check where the check goes.
    Three were shell syntax errors. Registration accepted every one of them
    without a word, and each was then recorded as permanent protection.

    A gate that cannot execute is worse than no gate: it is counted, reported,
    and believed. The registry is append-only, so a bad row is close to
    permanent -- which is exactly why the check belongs here and not downstream.

    NOT validated here: whether the command TESTS anything real. `true` is a
    legal gate and a useless one. This refuses the unrunnable, not the useless;
    the zero-collecting pytest class is its own item.
    """
    cmd = (command or "").strip()
    if not cmd:
        raise ValueError("gate command is empty; a gate that runs nothing is not a gate")
    import shutil
    import subprocess as _sp
    # 1. Does it parse? Catches the unterminated-heredoc class.
    syntax = _sp.run(["bash", "-n", "-c", cmd], capture_output=True, text=True)
    if syntax.returncode != 0:
        raise ValueError(
            f"gate command is not valid shell: {syntax.stderr.strip()[:200]}\n"
            f"  command: {cmd[:160]}")
    # 2. Is the first word a real command? Catches the prose class, which is the
    #    one that actually happened seven times. Builtins resolve too, so
    #    `cd x && ...` passes; `check:the ...` does not.
    # THE ONLY DEVIATION FROM THE RESTORED ORIGINAL, and it is measured. The raw
    # first token of `PYTHONPATH=src python3 -m pytest ...` is an ASSIGNMENT, not a
    # command name, so the original refuses a command bash runs. Against THIS repo's
    # 204 bypass_checks the original refuses 16, of which 2 are that false positive
    # (srsa-authoritative-path-contract, srsa-check-repairs-survived-merge). issue_runner
    # RUNS the bypass_check and requires exit 0 BEFORE registering, then turns any raise
    # here into a hard `cannot close` -- so restoring the guard verbatim would break
    # closeout on two specs whose checks had just gone green.
    #
    # Assignments are stripped and nothing else is. Shell GRAMMAR openers are
    # deliberately NOT special-cased: 0 of 204 bypass_checks start with ( { ! < or >,
    # so probing them as a first token refuses them and fails CLOSED at zero measured
    # cost. That is the whole contested surface of PR #330 left out on purpose.
    probe_cmd = cmd
    while True:
        head = probe_cmd.split(None, 1)
        if not head:
            break
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head[0]):
            if len(head) == 1:
                raise ValueError(
                    "gate command is only environment assignments, so it runs "
                    f"no check.\n  command: {cmd[:160]}")
            probe_cmd = head[1]
            continue
        break
    # A LEADING `!` IS STRIPPED, and this is the one shell shape that must be handled.
    # Not a general grammar heuristic -- `!` alone earns it, because it INVERTS:
    #
    #   `command -v !` RESOLVES (it is a bash reserved word), so without this the probe
    #   accepts `! <anything>`, and `bash -c '! <missing command>'` exits 0. A negated
    #   prose gate would register and pass forever in an append-only registry.
    #   `(` and `{` do not need this: prose inside them exits 127 and the gate goes RED
    #   loudly, which is the tolerable direction.
    #
    # `! grep -q ...` (assert-absent) is a REAL and recurring idiom, not a hypothetical.
    # Censused across both populations on this machine 2026-09-08:
    #   registered gates.jsonl : 1032 rows / 699 distinct -> 5 distinct start with `!`
    #   spec bypass_checks     : 41588 rows / 958 distinct -> the same 5
    # all five are `! grep`-shaped absence assertions and one is a secret scan. An
    # earlier census of ONE repo's 204 bypass_checks found 0 and concluded this shape
    # was unused; that was the wrong population (see ASK-1354).
    #
    # Stripping keeps all five registrable AND refuses `! <prose>`.
    while probe_cmd.lstrip()[:1] == "!":
        probe_cmd = probe_cmd.lstrip()[1:]
        if not probe_cmd.strip():
            raise ValueError(
                "gate command is only a negation, so it runs no check.\n"
                f"  command: {cmd[:160]}")
    first = probe_cmd.split()[0]
    probe = _sp.run(["bash", "-lc", f"command -v {shlex.quote(first)} >/dev/null 2>&1"],
                    capture_output=True, text=True)
    if probe.returncode != 0 and not shutil.which(first):
        raise ValueError(
            f"gate command does not start with a runnable command: {first!r}. "
            "This is the prose-in-the-command-slot class (ASK-1040): write the "
            "CHECK here, not a description of it.\n"
            f"  command: {cmd[:160]}")


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
    # AFTER the idempotency lookup, never before: gate_id is issue_id+sha256(command),
    # so a RE-CLOSE resolves to an existing row and must be a no-op. Validating first
    # turned that into a raise, and issue_runner converts any raise into `cannot close`,
    # breaking a workflow issue_runner itself documents.
    _reject_unrunnable_gate(command)
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


class LinearUnreachableError(LinearRefError):
    """The tracker could not be ASKED — transport failure, not an answer.

    Subclass, not sibling: every existing `except LinearRefError` still refuses,
    so the collapse-to-refuse property above is intact. What this adds is honest
    REPORTING for the one caller that buckets its refusals: the promoted audit
    was filing outages under STILL OPEN, because an HTTP 500 and a Backlog state
    both arrived as the same class (Codex review PR #213, 2026-08-18). An outage
    is "could not read", never "read it and it is open".
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
        # Unreachable, not still-open: with no key the tracker was never ASKED,
        # so the promoted audit must file this UNVERIFIABLE (Codex, PR #213 r2).
        raise LinearUnreachableError(
            "closure cannot be verified: no Linear API key. Create one at "
            "https://linear.app/settings/api then:\n"
            f"  umask 077 && printf '%s' '<key>' > {path}\n"
            "or export KIPI_LINEAR_API_KEY. An unverified reference is never recorded")
    key = path.read_text().strip()
    if not key:
        raise LinearUnreachableError(f"closure cannot be verified: {path} is empty")
    return key


def _linear_issue_state(identifier: str) -> dict:
    """The `{name, type}` of a Linear issue's workflow state.

    Raises LinearRefError for anything short of a definite answer, including an
    unreachable API — offline is a refusal, not an assumption.
    """
    import urllib.error
    import urllib.request

    # A SUITE MUST NEVER SPEND A REAL LINEAR CALL. This is the only outbound
    # request in this file, and `spillover promoted-audit` newly routes a whole
    # sweep through it -- one command, seventeen requests. Adding an outbound
    # call to shared code retroactively puts every older suite that reaches it on
    # the live path, and the failure is invisible while the network happens to be
    # up and the token happens to be valid.
    #
    # Tests that need a state monkeypatch THIS function, which replaces the
    # refusal along with the request, so this never blocks a legitimate test. It
    # only catches the one that forgot.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise LinearRefError(
            f"refusing to query Linear for {identifier} from inside a test. "
            "Monkeypatch _linear_issue_state with the state you mean to test.")

    body = json.dumps({"query": LINEAR_STATE_QUERY, "variables": {"id": identifier}}).encode("utf-8")
    request = urllib.request.Request(
        LINEAR_API_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": _linear_api_key()},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LinearUnreachableError(f"Linear returned HTTP {exc.code} for {identifier}") from exc
    except urllib.error.URLError as exc:
        raise LinearUnreachableError(f"cannot reach Linear to verify {identifier}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise LinearUnreachableError(f"Linear sent a non-JSON answer for {identifier}: {exc}") from exc
    # Linear answers HTTP 200 with an `errors` array for application-level
    # failures, so a status-code-only check would read a failed lookup as a
    # verified one -- the exact shape of bug this command exists to prevent.
    if payload.get("errors"):
        # An application-level rejection (bad auth scope, malformed query) is a
        # failed READ, not an answer about the issue's state (Codex, PR #213 r2).
        raise LinearUnreachableError(
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
            "Close it first, point at the merged fix with --resolution-commit "
            "<sha>, or record a non-item with --void <reason>.")
    return {
        "resolution_tracker": "linear",
        "resolution_verified_state": state.get("name"),
        "resolution_verified_at": _now_iso(),
    }


class CommitRefError(LinearRefError):
    """A resolution COMMIT could not be proven to be merged evidence for this item.

    Subclasses LinearRefError so the single `except` on the resolve path catches
    both trackers. Same contract, different evidence: unverifiable is refused,
    never downgraded to a warning.
    """


def _git(repo_root, *args):
    """One git invocation against `repo_root`. Never raises on a git failure --
    every caller below reads the returncode, because "git said no" and "git is
    missing" must both become a REFUSAL and not a traceback."""
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(repo_root), *args],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        # Narrow on purpose: a bare `except Exception` here would swallow a
        # NameError in this module and report it as "git is missing".
        raise CommitRefError(f"cannot run git in {repo_root}: {exc}") from exc


def _integration_branch(repo_root) -> str:
    """The branch a commit must be merged into to count as shipped.

    Origin's view first, the local branch only when no origin exists. Local
    `main` can hold commits origin has never seen, so "ancestor of local main"
    certifies work as shipped from an unpushed checkout -- the exact laundering
    Codex named on PR #213 round 2. The remote-tracking ref is what this
    machine last SAW of the shared branch; it can be stale, never fabricated.
    NEVER a fallback to HEAD: HEAD is the branch you are standing on, so
    "ancestor of HEAD" is satisfied by the commit you just made on your own
    unmerged feature branch -- which is the hand-clear this whole verb exists
    to refuse. A repo with none of these refuses rather than guessing.
    """
    probe = _git(repo_root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    ref = probe.stdout.strip()
    if probe.returncode == 0 and ref:
        return ref.removeprefix("refs/remotes/")
    for name in ("origin/main", "origin/master"):
        probe = _git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{name}")
        if probe.returncode == 0 and probe.stdout.strip():
            return name
    for name in ("main", "master"):
        probe = _git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
        if probe.returncode == 0 and probe.stdout.strip():
            return name
    raise CommitRefError(
        "no integration branch to measure against: this repo has no local "
        "main/master and no origin/HEAD. A commit cannot be shown merged, so "
        "the commit exit is unavailable here.")


PROOF_TIMEOUT_SECONDS = 600


def _verify_resolution_proof(cfg: Config, item_id: str, command: str,
                             broken_at: str) -> dict:
    """THE FOURTH EXIT (sp-1dfc48a8). Prove the defect is gone by watching a
    check fail before the fix and pass after it.

    ## The hole this fills, and why the obvious patch is a workaround

    The third exit requires a MERGED commit whose MESSAGE names the item id.
    That binding is made at fix time, and three items are fixed at main HEAD and
    cannot leave the ledger because it was never made: sp-9066e068 (a1f33b15),
    sp-43b11b74 (6ef8278d) and sp-cd9ccc16 (b3d95c66). The commit carrying each
    fix never named the item, and the commit that named it does not contain the
    fix -- checked both directions with `merge-base --is-ancestor`.

    The two patches that suggest themselves are both worse than the hole:

    - **An empty commit, or a retroactive commit that names the id.** This
      fabricates the proxy and adds no evidence. The third exit's real claim is
      "somebody with the context bound this fix to this item"; a commit written
      today to satisfy a checker is that claim with the context removed. It
      would pass, and it would mean nothing, and the next reader would trust it.
    - **Loosening --resolution-commit to accept any sha whose ANCESTRY contains
      a named fix.** Every sha's ancestry contains every older commit, so this
      degrades to `--because-i-said-so` with extra steps.

    ## What this exit requires instead

    Not a name. A DEMONSTRATION, and one that stays re-runnable:

      1. `command` PASSES against the current checkout;
      2. the same `command` FAILS against `broken_at`, in a throwaway worktree;
      3. both results, the command, and both shas are recorded.

    `{tree}` in the command is substituted with the tree being graded, and BOTH
    runs happen from the main checkout. That placement is the load-bearing
    detail. The naive version runs the command with cwd set to each tree, which
    breaks on the most common case there is: the check that proves a fix
    normally SHIPPED WITH the fix, so at `broken_at` the checker does not exist
    and the command fails because the file is missing rather than because the
    defect is present. A checker that fails for the wrong reason is a false
    positive wearing a green suit. Running the HEAD checker against a pre-fix
    TREE is the reproducer-ref-hatch discipline: one checker, two subjects.

    That is strictly stronger than a string in a commit message. A message can
    be typed; a check that flips across a specific ref cannot be, and a later
    reader can re-run it. It is the reproducer-ref-hatch discipline applied to
    the ledger's own exit: a regression check that has never been watched fail
    is not evidence, so this exit refuses to accept one that does not.

    ## The failure this guards against by construction

    If the worktree cannot be created, this RAISES. It does not fall back to
    running the command in the main checkout, which would run the "before" case
    against fixed code, see it pass, and report a false SURVIVED -- the item
    would then be refused for the wrong reason, or worse, a nearby variant would
    pass for the wrong reason. The resolved record carries the worktree's own
    resolved HEAD so the next reader can see WHERE each half ran.

    ## Honest boundary (what this exit does NOT catch)

    The COMMAND is chosen by the operator, and no code can verify it is
    semantically ABOUT the item: `grep -q 'IS FIXED' {tree}/README` flips
    across any commit that edited that file, item or no item. What the exit
    guarantees is narrower and stated exactly: the flip crosses this repo's
    MERGED history (both shas ancestry-checked against the integration
    branch), and the record binds command + both shas + the item id, so a
    later reader can re-run it and judge the relevance themselves. Closing
    the semantic half would need a machine-readable link from a free-text
    ledger item to code, which does not exist; captured as an open spillover
    item rather than papered over (Codex, PR #213 rounds 1-2).
    """
    root = Path(cfg.repo_root).resolve()
    probe = _git(root, "rev-parse", "--verify", "--quiet", f"{broken_at}^{{commit}}")
    before_sha = probe.stdout.strip()
    if probe.returncode != 0 or not before_sha:
        raise CommitRefError(
            f"no commit {broken_at!r} in {root}. --broken-at must name a real "
            "pre-fix commit; the whole exit is that the check flips across it.")
    head_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    if before_sha == head_sha:
        raise CommitRefError(
            "--broken-at is HEAD, so there is nothing for the check to flip "
            "across. Name the commit where the defect was still present.")
    # Same ancestry rule as the commit exit. Without it, any commit that EXISTS
    # (a dangling branch, a fetched fork) can host the failing half of the flip,
    # and the demonstration says nothing about this repo's actual history — the
    # unrelated-commit hand-clear Codex named on PR #213.
    branch = _integration_branch(root)
    if _git(root, "merge-base", "--is-ancestor", before_sha, branch).returncode != 0:
        raise CommitRefError(
            f"--broken-at {before_sha[:9]} is not an ancestor of '{branch}'. "
            "The flip must cross this repo's real history; a commit outside it "
            "demonstrates nothing about when this item was broken.")
    if _git(root, "merge-base", "--is-ancestor", head_sha, branch).returncode != 0:
        raise CommitRefError(
            f"HEAD {head_sha[:9]} is not an ancestor of '{branch}': the fix "
            "being demonstrated has not merged. A proof run from an unpushed "
            "checkout would record local work as shipped (Codex, PR #213 r2). "
            "Merge first, then resolve.")

    if "{tree}" not in command:
        raise CommitRefError(
            "--resolution-proof must contain '{tree}', the placeholder for the "
            "tree being graded. Without it both runs inspect the same code and "
            "the command cannot flip, so it proves nothing.")

    # BOTH halves run from a clean worktree of HEAD, never the live working
    # directory. Two distinct laundering paths die here (Codex, PR #213 r4+r6):
    # an uncommitted FIX passing while the record points at a commit that does
    # not contain it, and an uncommitted CHECKER swaying the verdict while the
    # committed checker at the recorded HEAD is red. cwd is the HEAD worktree,
    # so the checker resolving relatively is HEAD's COMMITTED copy; {tree}
    # substitution still moves only the SUBJECT.
    tmp_after = Path(tempfile.mkdtemp(prefix="prd-os-proof-"))
    worktree_after = tmp_after / "after"
    added_after = _git(root, "worktree", "add", "--detach", str(worktree_after), head_sha)
    try:
        if added_after.returncode != 0 or not (worktree_after / ".git").exists():
            raise CommitRefError(
                f"could not create a worktree at HEAD {head_sha[:9]}: "
                f"{(added_after.stderr or added_after.stdout).strip()[:300]}")

        def _run(tree):
            """cwd is the clean HEAD worktree: the CHECKER is HEAD's committed
            copy, never the live checkout's. Only the SUBJECT moves."""
            return subprocess.run(command.replace("{tree}", str(tree)), shell=True,
                                  cwd=str(worktree_after), capture_output=True,
                                  text=True, timeout=PROOF_TIMEOUT_SECONDS)

        after = _run(worktree_after)
        if after.returncode != 0:
            raise CommitRefError(
                f"the proof command does not pass at HEAD ({head_sha[:9]}), exit "
                f"{after.returncode}. An item is not resolved while its own check is "
                f"red -- and only COMMITTED state counts: an uncommitted fix in the "
                f"working tree is not shipped.\n{(after.stdout + after.stderr)[-800:]}")

        tmp = Path(tempfile.mkdtemp(prefix="prd-os-proof-"))
        worktree = tmp / "before"
        added = _git(root, "worktree", "add", "--detach", str(worktree), before_sha)
        try:
            if added.returncode != 0 or not (worktree / ".git").exists():
                # RAISE, never fall through. A failed worktree add followed by a run
                # in the main checkout would grade the "before" case against FIXED
                # code and report a false pass.
                raise CommitRefError(
                    f"could not create a worktree at {before_sha[:9]}: "
                    f"{(added.stderr or added.stdout).strip()[:300]}")
            seen = _git(worktree, "rev-parse", "HEAD").stdout.strip()
            if seen != before_sha:
                raise CommitRefError(
                    f"the worktree is at {seen[:9]}, not the requested {before_sha[:9]}")
            before = _run(worktree)
            if before.returncode == 0:
                raise CommitRefError(
                    f"the proof command ALSO passes at {before_sha[:9]}, so it does "
                    "not demonstrate this item was ever broken. Point --broken-at at "
                    "a commit where the defect was still present, or pick a check "
                    "that actually fails there.")
        finally:
            _git(root, "worktree", "remove", "--force", str(worktree))
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree_after))
        shutil.rmtree(tmp_after, ignore_errors=True)

    return {
        "resolution_tracker": "proof",
        # The binding Codex flagged as missing: the stored record names WHICH
        # item this proof was executed for, so a proof pasted onto a different
        # row is detectable by any later reader.
        "resolution_proof_item": item_id,
        "resolution_proof_command": command,
        "resolution_proof_head": head_sha,
        "resolution_proof_broken_at": before_sha,
        "resolution_proof_before_exit": before.returncode,
        "resolution_proof_after_exit": 0,
        "resolution_verified_at": _now_iso(),
    }


def _verify_resolution_commit(cfg: Config, item_id: str, sha: str) -> dict:
    """Prove `sha` is merged evidence that `item_id` was fixed; return that proof.

    THE THIRD EXIT (sp-8c0b2d87). The first two -- a CLOSED tracked issue, or a
    recorded void -- cannot cover an item fixed outside a PRD manifest:
    issue_runner has no `create` verb, prd_split is the only issue minter, and
    voiding a real defect records a falsehood. Measured live on sp-d912cc82 and
    sp-3aa375a6, both merged into main and both stuck open.

    Three conditions, ALL required, none assertable by the operator:

      1. the object exists here and is a commit;
      2. it is an ancestor of the integration branch -- merged, not a dangling
         local commit on the branch that wants the item cleared;
      3. its MESSAGE names `item_id`.

    (3) is the whole anti-hand-clear property. Without it any of this repo's
    thousands of merged shas clears any item, which is `--because-i-said-so`
    with a sha typed in front of it. With it, clearing an item costs a real
    commit on the real branch that says which item it fixes -- and the binding
    is made at fix time, by the person holding the context.

    MESSAGE ONLY, never the diff. `git log -S` / a diff scan reads as the more
    generous rule and is the more dangerous one: any commit touching a file
    that merely QUOTES an id (an RCA doc, a plan, a review note, a ledger dump)
    would resolve that id, and those files exist by the dozen here. One channel,
    written on purpose, is the point.
    """
    root = Path(cfg.repo_root).resolve()
    probe = _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    full = probe.stdout.strip()
    if probe.returncode != 0 or not full:
        raise CommitRefError(
            f"no commit {sha!r} in {root}. A resolution commit must exist in the "
            "repo that holds the ledger.")
    branch = _integration_branch(root)
    if _git(root, "merge-base", "--is-ancestor", full, branch).returncode != 0:
        raise CommitRefError(
            f"commit {full[:9]} is not an ancestor of '{branch}': the fix is not "
            "merged. Merge it first -- an unmerged commit is a promise, not evidence.")
    message = _git(root, "log", "-1", "--format=%B", full).stdout
    if item_id not in message:
        subject = _git(root, "log", "-1", "--format=%s", full).stdout.strip()
        raise CommitRefError(
            f"commit {full[:9]} ({subject[:60]}) does not name {item_id} in its "
            f"message. Bind the fix to the item: put '{item_id}' in the commit "
            "message of the commit that fixes it, or use --void with a reason.")
    return {
        "resolution_tracker": "git",
        "resolution_commit": full,
        "resolution_commit_subject": _git(root, "log", "-1", "--format=%s", full).stdout.strip()[:200],
        "resolution_branch": branch,
        "resolution_verified_at": _now_iso(),
    }


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
            # PRESENT BUT UNREADABLE IS A REFUSAL, NOT A MISS (Codex round 2,
            # PR #131, MAJOR). This used to `continue`, which walked on to the
            # broader PRD scope and let a half-written active-issue.json widen
            # the amnesty from one issue to a whole PRD. The producer writes this
            # file NON-ATOMICALLY, so a partial write is a real failure mode, not
            # a constructed one; reproduced with `{partial-json` yielding
            # active_scope=prd-live. An absent file means "no issue is active",
            # which is information; a corrupt file means "we cannot tell", which
            # is not. Refuse outright and let the caller fail closed.
            return None
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


# Severities the standing gate blocks on. These are WORK, so they carry a DoR and
# become a Linear issue at file time. Everything else is a note.
SPILLOVER_BLOCKING_SEVERITIES = ("major", "blocker")


def _spillover_read_dor(args):
    """The DoR text from --dor or --dor-file, or None."""
    if getattr(args, "dor_file", None):
        return Path(args.dor_file).read_text(encoding="utf-8").strip()
    return (getattr(args, "dor", None) or "").strip() or None


def _spillover_autopromote(cfg: Config, sid: str, args, dor: str) -> dict:
    """File the Linear issue immediately. Never route through the founder.

    why (founder, 2026-08-13, verbatim): "notification dont work for me. I get a ton
    of notifications and all id do is open an instance and say 'make an issue for it'.
    whats the point of having me in the middle". A ping that only produces that
    sentence is a router, not a signal.

    And when this fails, the answer is still not him: "if an engineering decision
    needs to be made, it can and should be made by Sana, not wait for me". So a
    failure here prints the exact command that completes the job and names Sana as
    its owner. The ITEM IS ALREADY RECORDED before this runs, so a promotion failure
    can never lose the finding -- it degrades to the pre-2026-08-13 behaviour, which
    was the whole system a day ago.
    """
    import subprocess
    root = Path(cfg.repo_root) if hasattr(cfg, "repo_root") else Path.cwd()
    promoter = root / "q-system" / ".q-system" / "scripts" / "spillover-promote.py"
    if not promoter.exists():
        return {"status": "skipped", "reason": f"no promoter at {promoter}"}

    title = getattr(args, "title", None) or args.desc.strip().split(". ")[0][:110]
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(dor)
        dor_path = fh.name
    cmd = ["python3", str(promoter), sid, "--title", title, "--dor-file", dor_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                             cwd=str(root))
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "reason": str(exc)[:200],
                "owner": "sana", "rerun": " ".join(cmd)}
    if res.returncode == 0:
        try:
            return {"status": "promoted", **json.loads(res.stdout.strip().splitlines()[-1])}
        except Exception:  # noqa: BLE001
            return {"status": "promoted", "raw": res.stdout.strip()[-200:]}
    # A refusal is an ENGINEERING problem (usually the Linear project mapping,
    # sp-421fa27d), so it is addressed to Sana with the command that finishes it.
    return {"status": "not_promoted",
            "reason": (res.stderr or res.stdout).strip()[-300:],
            "owner": "sana",
            "rerun": " ".join(cmd),
            "note": "item IS recorded and the gate is RED; only the Linear issue is missing"}


def _spillover_ack(cfg: Config, args) -> int:
    """Record that an issue NAMED this item and deliberately did not fix it.

    THE THIRD DISPOSITION, and the reason it is not a fourth exit. `ack` does not
    change `status`: the item stays open, the standing gate stays red, and the
    backlog cannot be emptied with it. All it clears is the closeout block for
    ONE issue, so the gate below can demand a decision without making the very
    common filed-not-fixed case unclosable.

    That case is the majority, measured rather than assumed: of 38 open items
    named by a merged commit on 2026-08-17, 28 were named by the commit that
    FILED them. Without `ack`, every issue that captures a spillover item would
    be blocked from closing by its own capture.

    why an explicit reason is required: the value is the sentence, not the row.
    A disposition with no reason is a hand-clear with extra steps.

    APPENDS A FULL COPY of the record, never a patch. `_read_spillover` is
    last-write-wins on the WHOLE record (`items[rec["id"]] = rec`), not a merge,
    so appending `{"id": ..., "acked_by_issue": ...}` alone would erase the
    item's description, severity and status and resurrect it as a malformed row.
    The lock's own docstring names this shape; it applies here identically.
    """
    with _spillover_lock(cfg):
        items = _read_spillover(cfg)
        rec = items.get(args.id)
        if rec is None:
            sys.stderr.write(f"no spillover item {args.id}\n")
            return 2
        if rec.get("status") != "open":
            sys.stderr.write(
                f"{args.id} is {rec.get('status')}, not open: nothing to acknowledge\n")
            return 2
        out = dict(rec)
        out["acked_by_issue"] = args.issue
        out["ack_reason"] = args.reason
        out["acked_at"] = _now_iso()
        _spillover_append(cfg, out)
    print(json.dumps({"id": args.id, "acked_by_issue": args.issue,
                      "status": rec.get("status")}))
    return 0


def _spillover_promoted_audit(cfg: Config, args) -> int:
    """Re-check every `promoted` row against the tracker. sp-0d76a138.

    ## The defect

    `promoted` is the ONE exit from this ledger that fires automatically, and it
    was the one exit that proved nothing. `_spillover_open` filters
    `status == "open"`, so the moment a row is promoted it stops blocking
    `gates run` AND stops blocking archive. `spillover-promote.py` says so in its
    own docstring -- "promoting is not fixing, and a status that claimed
    otherwise would let the pile launder itself clean" -- and then nothing ever
    re-read the Linear issue. Creating the issue was what cleared the gate.

    ## What this does and does not change

    This closes the half that is unambiguously a defect: nothing re-checks. A
    promoted row whose Linear issue has since COMPLETED is resolvable with real
    evidence, and now gets resolved by a command instead of waiting for someone
    to remember. Rows whose issue is still open are named, with age, so they are
    visible rather than silently gone.

    It deliberately does NOT flip `promoted` back to blocking, and that is a
    measurement, not a preference. Measured 2026-08-17 against Linear: of the 17
    promoted rows, 13 refs were readable in one page and 2 of those 13 were
    Done. Making `promoted` block today would turn the standing gate red on ~15
    items at once, for work whose arrival rate exceeds its service rate. A gate
    that is red for months teaches everyone to step over it, which is strictly
    worse than no gate -- the same reasoning the severity split in
    SPILLOVER_BLOCKING_SEVERITIES was built on. The flip is a separate decision
    that needs the backlog drained first, and it is captured as its own item
    rather than smuggled in here.

    ## Why it reuses `_verify_resolution_ref`

    Because a second Linear client is a second opinion about what "closed"
    means. That function already refuses `canceled` (a canceled issue shipped no
    fix), already prefers a local `.prd-os/issues/` spec, and is already the
    thing the operator-facing resolve path trusts. One authority.

    Offline is a REPORT, never a resolution: a row whose state could not be read
    is listed as unverifiable and left promoted.
    """
    rows = [r for r in _read_spillover(cfg).values() if r.get("status") == "promoted"]
    dry = getattr(args, "dry_run", False)
    closed, still_open, unreadable = [], [], []
    transport_failures = 0
    for rec in sorted(rows, key=lambda r: r.get("id", "")):
        ref = rec.get("linear_ref")
        if not ref:
            unreadable.append((rec.get("id"), None, "no linear_ref recorded"))
            continue
        try:
            evidence = _verify_resolution_ref(cfg, ref)
        except LinearUnreachableError as exc:
            # BEFORE the still-open catch, because it is a subclass. An outage
            # is "could not read", never "read it and it is open" — filing it
            # under STILL OPEN made a down tracker look like a triaged backlog
            # (Codex review PR #213).
            unreadable.append((rec.get("id"), ref, f"tracker unreachable: {exc}"))
            transport_failures += 1
            continue
        except LinearRefError as exc:
            # A refusal here is the NORMAL case: the issue is simply still open.
            # It is reported, not raised, because one open issue must not stop
            # the sweep from resolving the rows that did close.
            age = ""
            created = str(rec.get("created_at") or "")[:10]
            if created:
                try:
                    from datetime import date
                    days = (date.today() - date.fromisoformat(created)).days
                    age = f"open {days}d"
                except ValueError:
                    age = f"created {created}"
            still_open.append((rec.get("id"), ref, age, str(exc).split(". ")[0]))
            continue
        except Exception as exc:                              # noqa: BLE001
            unreadable.append((rec.get("id"), ref, f"tracker unreachable: {exc}"))
            transport_failures += 1
            continue
        closed.append((rec.get("id"), ref))
        if dry:
            continue
        with _spillover_lock(cfg):
            current = _read_spillover(cfg).get(rec.get("id"))
            if not current or current.get("status") != "promoted":
                continue          # someone resolved it between the read and here
            new = dict(current)
            new.update(status="resolved", resolution_ref=ref, resolved_at=_now_iso(),
                       resolution_evidence="promoted-audit: tracker reports completed",
                       **evidence)
            _spillover_append(cfg, new)
    for label, items in (("RESOLVED" if not dry else "WOULD RESOLVE", closed),
                         ("STILL OPEN", still_open), ("UNVERIFIABLE", unreadable)):
        print(f"{label}: {len(items)}")
        for row in items:
            print("  " + "  ".join(str(x) for x in row if x))
    print(f"promoted rows audited: {len(rows)}")
    if transport_failures or (rows and len(unreadable) == len(rows)):
        # ANY transport failure exits nonzero, not only a fully-blind sweep
        # (Codex, PR #213 r5: partial outages returned success, so the daily
        # detector discarded unreachable rows). The resolutions already applied
        # above are kept -- the exit code reports the sweep's own health, it
        # does not undo work. Rows with no linear_ref are a DATA gap, reported
        # in UNVERIFIABLE but not a transport failure; they fail the sweep only
        # when they are all it contains (nothing was auditable at all).
        sys.stderr.write(
            "promoted-audit: %d transport failure(s), %d of %d rows unverifiable\n"
            % (transport_failures, len(unreadable), len(rows)))
        return 1
    return 0


def cmd_spillover(cfg: Config, args) -> int:
    """add | list | check | resolve | ack | triage — the out-of-scope finding ledger."""
    import hashlib as _hashlib
    sub = args.spillover_cmd
    if sub == "ack":
        return _spillover_ack(cfg, args)
    if sub == "add":
        sid = args.id or f"sp-{_hashlib.sha256((args.source + args.desc).encode()).hexdigest()[:8]}"
        dor = _spillover_read_dor(args)
        blocking = args.severity in SPILLOVER_BLOCKING_SEVERITIES
        # REFUSED AT THE DOOR, not later. The founder's words, 2026-08-13: "all id do
        # is open an instance and say 'make an issue for it'. whats the point of having
        # me in the middle". A notification turns him into a router between two agents.
        #
        # The DoR cannot be deferred to whoever picks the item up, because
        # spillover-promote.py's own header says it "is written by the agent that
        # CONFIRMED the finding" -- that agent has the context and a later one guesses,
        # and "guessing is worse". So the moment to demand it is the moment of filing,
        # when the context is still in the room.
        #
        # Minor and untriaged items are untouched: they are notes, not work, and
        # demanding a DoR for every passing observation is how the ledger stops being
        # written to at all.
        # NOT a refusal. The first version of this raised, and broke 34 tests -- which
        # was the design telling the truth: many spillover items are created by
        # MACHINERY (a `deferred` finding auto-creates one in both findings systems,
        # sp-5bcfbfe8), where no agent holds the context a DoR needs. Refusing there
        # would break the auto-capture that exists to stop orphans, which is a worse
        # failure than a missing DoR.
        #
        # So a blocking item with no DoR is HANDED OFF, never dropped and never routed
        # to the founder. His rule, 2026-08-13: "if an engineering decision needs to be
        # made, it can and should be made by Sana, not wait for me." Writing a DoR from
        # a confirmed finding is an engineering decision. `spillover needs-dor` lists
        # them so a Sana run can drain the queue.
        record = {
            "id": sid, "source": args.source, "description": args.desc,
            "severity": args.severity, "status": "open", "created_at": _now_iso(),
            # RULE-2026-08-24-B [USER-DIRECTED]: "Everything should be owned by
            # Sana." Never blank, never the founder. Consistent with
            # founder-notifications.md, where engineering signals go to Sana's
            # triage and never to his desk. `--owner` exists so a future second
            # engineer is expressible without another schema change; it does not
            # exist so an agent can file work onto nobody.
            "owner": (getattr(args, "owner", None) or DEFAULT_SPILLOVER_OWNER),
        }

        # STORE THE DoR (Codex review of #147, major). The --no-promote path replied
        # "DoR recorded; no Linear issue created" while this record discarded it, so
        # the DoR existed only in the caller's argv and `needs-dor` could never use
        # it. A status naming an artifact that was never written is the exact defect
        # this whole mechanism was built to stop, committed inside it.
        if dor:
            record["dor"] = dor
        _spillover_append(cfg, record)
        out = {"id": sid, "status": "open"}
        if dor and not getattr(args, "no_promote", False):
            out["promotion"] = _spillover_autopromote(cfg, sid, args, dor)
        elif dor:
            # A DoR WAS supplied and promotion was suppressed by the caller. Say that
            # explicitly: the first version fell through to "needs_dor" here, which
            # reported the opposite of the truth -- the one defect class this whole
            # ledger exists to catch.
            out["promotion"] = {"status": "suppressed", "reason": "--no-promote",
                                "note": "DoR recorded; no Linear issue created"}
        elif blocking:
            out["promotion"] = {
                "status": "needs_dor", "owner": "sana",
                "note": ("blocking severity with no DoR: no Linear issue was created. "
                         "Drain with `prd_runner.py spillover needs-dor`."),
            }
        print(json.dumps(out))
        return 0
    if sub == "needs-dor":
        # SANA'S QUEUE. Blocking items with no Linear issue: they turn the standing
        # gate red but nothing can pick them up. Writing the DoR is an engineering
        # decision, so it goes to Sana rather than waiting on the founder.
        rows = _spillover_open(cfg)
        pending = [r for r in rows
                   if r.get("status") == "open"
                   and r.get("severity") in SPILLOVER_BLOCKING_SEVERITIES
                   and not r.get("linear")]
        for r in pending:
            print(f"{r['id']} [{r.get('severity')}] src={r.get('source')}")
            print(f"    {(r.get('description') or '')[:200]}")
        print(f"\n{len(pending)} blocking item(s) need a DoR. Each one: write the DoR "
              f"(allowed files, a reproducer that fails first, acceptance), then\n"
              f"    python3 q-system/.q-system/scripts/spillover-promote.py <id> "
              f"--title '...' --dor-file <f>")
        return 0
    if sub == "own":
        # BACKFILL AND CORRECTION, through the same locked read-append chokepoint
        # as reclassify and resolve. Never an in-place edit: the ledger is
        # append-only and a prior event is evidence, not a draft.
        owner = (args.owner or DEFAULT_SPILLOVER_OWNER).strip()
        if not owner:
            sys.stderr.write("--owner cannot be empty; ownership is never blank\n")
            return 2
        with _spillover_lock(cfg):
            items = _read_spillover(cfg)
            if args.all_open:
                targets = [r for r in items.values() if r.get("status") == "open"]
            else:
                rec = items.get(args.id)
                if rec is None:
                    sys.stderr.write(
                        f"unknown spillover id: {args.id!r}. own never creates an "
                        "item -- a typo must not invent owned work.\n")
                    return 2
                targets = [rec]
            changed = 0
            for rec in targets:
                if rec.get("owner") == owner:
                    continue          # idempotent: no event for a no-op
                new_rec = dict(rec)
                new_rec.update({"owner": owner, "owner_set_at": _now_iso(),
                                "owner_was": rec.get("owner")})
                _spillover_append(cfg, new_rec)
                changed += 1
        print(json.dumps({"owner": owner, "considered": len(targets),
                          "changed": changed}))
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
                "reclassified_at": _now_iso(),
                "reclassified_from": prior,
                "reclassify_reason": args.reason,
            })
            _spillover_append(cfg, new_rec)
        print(json.dumps({"id": args.id, "severity": severity,
                          "was": prior, "status": new_rec.get("status")}))
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
                f"(prd_runner.py spillover resolve <id> --resolution-ref <issue-id>), "
                f"against a merged commit that names it (--resolution-commit <sha>), "
                f"or void it (--void <reason>). They cannot be silently dropped.\n")
            return 1
        print("no open spillover items")
        return 0
    if sub == "triage":
        # Read-only by construction: no _spillover_append call reachable from
        # here. A ledger this size (350+ open, ~50/day arriving from a handful
        # of producers) is unworkable as a flat list, but the fix is a better
        # LENS, never a bulk exit. The only three ways out of the ledger stay
        # `resolve --resolution-ref <closed-issue>`, `resolve --resolution-commit
        # <merged-sha-naming-this-id>`, and `resolve --void`. Each is verified;
        # none is assertable.
        openv = _spillover_open(cfg)
        if not openv:
            print("no open spillover items")
            return 0
        print(f"{len(openv)} open spillover item(s)")
        _print_spillover_groups(openv, "severity", "severity")
        _print_spillover_groups(openv, "source", "source")
        _print_reclassifications(openv)
        return 0
    if sub == "promoted-audit":
        return _spillover_promoted_audit(cfg, args)
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
            # EXACTLY ONE exit, not "at least one" (sp-8c0b2d87 added the third).
            # `--resolution-ref X --void "not real"` would otherwise take the ref
            # branch and silently drop the void reason, recording an item as
            # fixed-and-tracked when the operator said it was a non-item.
            chosen = [name for name, value in (
                ("--resolution-ref", args.resolution_ref),
                ("--resolution-commit", getattr(args, "resolution_commit", None)),
                ("--resolution-proof", getattr(args, "resolution_proof", None)),
                ("--void", args.void),
            ) if value]
            if not chosen:
                sys.stderr.write(
                    "resolve requires exactly one of --resolution-ref <issue-id>, "
                    "--resolution-commit <sha> or --void <reason>\n")
                return 2
            if len(chosen) > 1:
                sys.stderr.write(
                    f"resolve takes exactly one exit, got {', '.join(chosen)}\n")
                return 2
            new = dict(rec)
            if getattr(args, "resolution_proof", None):
                if not getattr(args, "broken_at", None):
                    sys.stderr.write(
                        "--resolution-proof requires --broken-at <sha>: a check "
                        "that has never been watched fail is not evidence.\n")
                    return 2
                try:
                    evidence = _verify_resolution_proof(
                        cfg, args.id, args.resolution_proof, args.broken_at)
                except LinearRefError as exc:
                    sys.stderr.write(f"cannot resolve {args.id}: {exc}\n")
                    return 2
                new.update(status="resolved", resolved_at=_now_iso(), **evidence)
            elif args.void:
                new.update(status="resolved", void_reason=args.void, resolved_at=_now_iso())
            elif getattr(args, "resolution_commit", None):
                try:
                    evidence = _verify_resolution_commit(
                        cfg, args.id, args.resolution_commit)
                except LinearRefError as exc:
                    sys.stderr.write(f"cannot resolve {args.id}: {exc}\n")
                    return 2
                new.update(status="resolved", resolved_at=_now_iso(), **evidence)
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

# RULE-2026-08-24-B [USER-DIRECTED 2026-08-24]: "Everything should be owned
# by Sana." One constant so the default cannot drift between the add door,
# the backfill verb and the tests that pin them.
DEFAULT_SPILLOVER_OWNER = "sana"
# Least -> most severe. Separate from the membership tuples above ON PURPOSE:
# those answer "does this block?", this answers "which way did it move?", and
# conflating the two is how `blocker -> high` read as a raise.
SPILLOVER_SEVERITY_ORDER = ("low", "minor", "medium", "high", "major", "blocker")
# Least -> most severe. Separate from the membership tuples above ON PURPOSE:
# those answer "does this block?", this answers "which way did it move?", and
# conflating the two is how `blocker -> high` read as a raise.
SPILLOVER_SEVERITY_ORDER = ("low", "minor", "medium", "high", "major", "blocker")
SPILLOVER_KNOWN_SEVERITIES = (
    SPILLOVER_BLOCKING_SEVERITIES + SPILLOVER_NONBLOCKING_SEVERITIES)


def _spillover_blocks(record: dict, scope: str | None) -> bool:
    """Does this open item turn `gates run` red?

    THE COMBINED RULE. Attribution narrows WHICH items count; severity still sets
    the bar; a `blocker` anywhere is the floor.

        no live scope        -> severity decides (ASK-363's rule, unchanged)
        item source == scope -> severity decides (your own item, normal bar)
        inherited item       -> only `blocker` blocks

    WHY BOTH AXES. ASK-363 shipped severity alone; ASK-526/527 shipped attribution
    alone; neither is sufficient and each deletes the other's contract if landed
    naively. Measured on kipi-system 2026-08-09: 636 open items, severity blocks 18,
    and all 18 are inherited from other work -- attributable to no change under
    review. A verdict RED with probability 1 regardless of the diff carries no
    information about the diff. Attribution alone, though, blocks on a MINOR item
    your own work opened, which collapses the deliberate two-bar split (`gates run`
    is the day-to-day light, `archive` is the closeout bar that refuses on ANY open
    item this work touched) -- see test_archive_still_refuses_on_a_minor_item.

    THE KNOWN COST, named here rather than discovered later: one inherited `blocker`
    wedges EVERY scope in the repo until somebody acts on it. That is the intended
    blast radius of the word, but it makes severity a loaded gun -- mislabel one item
    and all work halts. The escapes are auditable and there are exactly three, each
    of which records a decision: `spillover reclassify --reason`, `resolve` against a
    closed issue, or `void` with a reason. There is deliberately NO
    --ignore-inherited flag; that would be the hand-clear no-orphan-findings.md
    refuses everywhere else.
    """
    severity = (record.get("severity") or "").strip().lower()
    # The ack disposition's one effect, wired where the closeout block actually
    # decides (Codex, PR #213 r3: `ack` wrote acked_by_issue and nothing read
    # it -- a write-only integration cannot report state). An item THIS scope
    # acknowledged, with a recorded reason, stops blocking THIS scope's
    # closeout and nothing else: other scopes, scopeless runs, the census and
    # the still-open status are all untouched.
    if scope is not None and record.get("acked_by_issue") == scope:
        return False
    if scope is None:
        # SCOPELESS RUNS BLOCK ON UNOWNED BLOCKERS, NOT ON THE WHOLE BACKLOG.
        #
        # Measured 2026-08-24, this repo: 419 open items, 54 at blocking
        # severity, active-issue.json and active-prd.json both null. So every
        # ad-hoc `gates run` -- the normal state between issues -- failed closed
        # over the entire ledger and had been RED for weeks. A verdict that is
        # red with probability 1 carries no information about your diff, which
        # is the exact defect ASK-526 removed for SCOPED runs and left standing
        # here. A gate nobody can ever turn green stops being read, so
        # fail-closed produced fail-open in practice.
        #
        # This is a RE-TARGET, not a relaxation. You still cannot dodge by
        # clearing scope: an unowned blocker blocks every run, scoped or not.
        # What stops blocking is a blocker that already has an address -- a
        # Linear ref or a DoR -- because that is tracked work with a person on
        # it, and a second blunter alarm on top of it buys nothing. What keeps
        # blocking is a blocker nobody can pick up, which is a triage failure
        # and is precisely what should stop the line.
        #
        # Honesty check on the numbers, so this cannot be mistaken for a trick
        # to lower a count: of the 54 blocking items, 0 had a Linear ref and 5
        # had a DoR. This exempts FIVE. The gate stays red on the other 33 and
        # the path to green is to give each one an owner, which is the action
        # that was wanted all along.
        return _is_blocking_severity(severity) and not _spillover_has_tracker_ref(record)
    if record.get("source") == scope:
        return _is_blocking_severity(severity)
    return severity == "blocker"


# OWNERSHIP IS POLICY. AN ADDRESS IS EARNED. Keep these two apart.
#
# Founder, 2026-08-24, verbatim: "Everything should be owned by Sana." That is
# RULE-2026-08-24-B and it settles the owner field: every item defaults to sana
# at the add door, so no finding can ever again be filed with nobody on it.
#
# THE TRAP THAT CREATES, and why this function does NOT read `owner`. Earlier
# today the gate's cost for a blocking severity was "has an owner". If owner
# auto-fills on every add, that cost is paid automatically, filing at blocking
# severity is free again, and I would have rebuilt the exact asymmetry measured
# this morning: 611 filed against 169 resolved, 0 of 419 carrying a tracker ref.
# A check its own default satisfies is not a check.
#
# So the cost moves to the one thing a default cannot mint: a TRACKER REF. A
# blocker that is worth stopping a run over is worth an issue in the queue
# somebody actually works. `spillover-promote.py` creates it and Linear was
# probed reachable before this shipped, so the path to green is real and
# automated, not aspirational.
#
# A DoR NO LONGER EXEMPTS, and that is the point. A DoR is the INPUT to
# promotion; the tracker ref is its RECEIPT. Accepting the promise instead of
# the receipt is how 5 items sat "ready" with no issue behind them. Require the
# receipt, which cannot be written by intending to do something.
#
# WHAT ACTUALLY MOVES AN ITEM OUT OF THE BLOCKING SET, stated precisely because
# a comment that overclaims is the defect this whole day was spent removing.
# `spillover-promote.py` sets status=promoted, and `_spillover_open` filters on
# status=="open", so PROMOTION is the mechanism; this predicate is the belt for
# the leftover case, an item that carries a ref and is still open (a reopen, or a
# ref written by hand). Measured at ship time it fires on ZERO of 327 open rows.
# It is deliberately kept rather than deleted: without it, an item that is
# reopened after promotion would block despite having a real address.
#
# PROMOTION IS NOT A HAND-CLEAR, and that claim is checkable rather than hopeful.
# `spillover promoted-audit` re-reads every promoted row against Linear, resolves
# the ones whose issue actually closed, and reports the rest with their age. It is
# wired into q-system/.q-system/scripts/fleet-health-daily.py:1542 and raises a
# `promoted-audit-blind` alarm if it cannot run. Probed 2026-08-24: 25 promoted
# rows audited, 0 unverifiable, four reported still open at 16d, 14d, 14d and 4d.
#
# Honesty check, same standard as _spillover_blocks: measured at ship time, 0 of
# 39 blocking items carried a tracker ref, so this change exempts ZERO and is
# strictly tighter than the DoR-accepting rule it replaces. It cannot be read as
# a move to lower a count.
def _spillover_has_tracker_ref(record):
    """A blocking item's earned address: an issue in the tracker, not a promise.

    `linear` is what spillover-promote.py writes, `linear_ref` what the promoted
    audit reads. Both count -- keying on one would silently un-address every item
    filed through the other door.
    """
    return bool(str(record.get("linear") or "").strip()
                or str(record.get("linear_ref") or "").strip())




def _is_blocking_severity(value: str) -> bool:
    """Unknown severities block. See SPILLOVER_NONBLOCKING_SEVERITIES."""
    sev = (value or "").strip().lower()
    if not sev:
        return False  # absent == the documented `minor` default, not unknown
    return sev not in SPILLOVER_NONBLOCKING_SEVERITIES


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
    registered_total = len(records)
    records = [
        record for record in records
        if record["lifecycle"] == "regression"
    ]
    # SCOPE IS RESOLVED AND FROZEN BEFORE ANY GATE COMMAND RUNS (Codex round 3,
    # PR #131, MAJOR). It used to be read AFTER the regression loop, so a gate
    # command -- or a concurrent `gates run` in another worktree -- could switch
    # .claude/state/active-issue.json mid-run and the verdict would be computed
    # against a DIFFERENT scope than the one the run started under. Reproduced:
    # scope ASK-A at gate start, ASK-B by verdict time, and the run's own open
    # major was reclassified as 'inherited' and stopped blocking -- exit 0 over a
    # major that run had left behind. Read once, hold it immutable for the run.
    # An EXPLICIT --scope clears the same liveness bar as an inferred one.
    #
    # THE SCAR (Codex round 1, PR #131, reproduced against the real 638-record
    # ledger): --scope used to be honoured unverified, on the rationale that the
    # flag is "a caller ASSERTING accountability, which is a decision by
    # somebody". Measured, that assertion bought:
    #     blocking_unscoped=19  blocking_fake_scope=1  fake_scope_live=False
    # A scope id naming nothing at all suppressed 18 inherited majors. The caller
    # here is usually an unattended agent, so "somebody decided" is precisely what
    # nobody can audit at 3am; an unverifiable assertion is not a decision, it is a
    # hand-clear, and no-orphan-findings.md refuses hand-clears everywhere else.
    # The flag is not removed (that would make it a lie) -- it is verified.
    explicit = getattr(args, "scope", None)
    if explicit:
        live = (_scope_is_live(cfg, explicit, cfg.issues_dir)
                or _scope_is_live(cfg, explicit, cfg.prds_dir))
        if live:
            scope = explicit
        else:
            scope = None
            print(f"[scope] --scope '{explicit}' refused: it names no tracked, live "
                  f"issue or PRD spec. Falling through to fail-closed; every open "
                  f"item answers.")
    else:
        scope = _active_scope(cfg)
    if not scope:
        # Say WHY there is no scope. A silent fall-through reads as "the gate is
        # just always red"; the note names the dead/missing/terminal spec that
        # refused to grant amnesty, which is the actionable half (ASK-527).
        note = _scope_refusal_note(cfg)
        if note:
            print(f"[scope] {note}")
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
    # WHY ATTRIBUTION AND NOT SEVERITY ALONE. The severity filter that shipped
    # in ASK-363 was a real improvement over the original boolean-over-the-whole
    # -ledger, but it is the same defect one order of magnitude smaller, and
    # measurement says so. Run against kipi-system 2026-08-09: 636 open items,
    # of which the severity filter blocks 18 -- and all 18 are inherited from
    # other work (prd-silent-absence, scs-validated-event-fold, ASK-402, PR-123).
    # None is attributable to any change under review. A verdict that is RED with
    # probability 1 no matter what you did carries no information about your
    # diff, so a genuine new regression is invisible inside it. Severity answers
    # "how bad is this?"; only attribution answers "did THIS work cause it?", and
    # the gate's job is the second question.
    #
    # SEVERITY IS NOT DISCARDED, it is demoted to reporting: the census ranks the
    # inherited tail by blocking-severity so the 18 stay visible and countable
    # without holding every future PR hostage. Both signals survive; only the
    # exit code changed hands.
    #
    # WHAT WAS REJECTED. An age cutoff ("only items newer than N days block").
    # It would let this function print "no open spillover" while 636 items sat
    # open -- a gate that states something false is strictly worse than one that
    # is uninformative, and items would leave enforcement with nobody deciding,
    # which is the silent drop no-orphan-findings.md exists to prevent.
    #
    # Nothing here removes an item, changes its status, or expires it. The two
    # ways out of the ledger are still exactly resolve-against-a-closed-issue and
    # record-a-void.
    openv = _spillover_open(cfg)
    blocking = [r for r in openv if _spillover_blocks(r, scope)]
    reported = [r for r in openv if r not in blocking]
    inherited = [r for r in openv if scope and r.get("source") != scope]
    if blocking:
        names = ", ".join(r["id"] for r in blocking)
        detail = "\n".join(f"  {r['id']} [{r.get('severity')}]: {r.get('description', '')[:90]} (src {r.get('source')})"
                           for r in blocking)
        label = f"spillover[{scope}]" if scope else "spillover"
        print(f"[RED] {label}: {len(blocking)} open item(s) this work must answer for: {names}")
        failures.append((label, f"{len(blocking)} open spillover item(s):\n{detail}\n"
                                f"Resolve via `prd_runner.py spillover resolve <id> "
                                f"--resolution-ref <closed-issue>` or `--resolution-commit <merged-sha>`."))
    if reported:
        # Reported, never silent. `--severity` DEFAULTS to minor, so a defaulted
        # item is indistinguishable from one assessed as minor -- the label says
        # "untriaged" rather than laundering "nobody looked" as "we judged it
        # small". This is how 533 of them accumulated unnoticed.
        ids = ", ".join(r["id"] for r in reported[:10])
        more = f" (+{len(reported) - 10} more)" if len(reported) > 10 else ""
        print(f"[REPORT] spillover: {len(reported)} open minor-or-untriaged "
              f"item(s), not blocking: {ids}{more}")
        print("  Triage with `prd_runner.py spillover triage`; raise one with "
              "`spillover add --severity major|blocker`.")
    # The census prints on EVERY run, red or green, passing or failing. An
    # inherited backlog that stops being PRINTED is functionally deleted for an
    # operator with ADHD, so the number leaving the blocking set must never mean
    # the number leaving the screen. `spillover triage` is the lens on it.
    census = f"[census] spillover: {len(openv)} open total"
    if inherited:
        sev = [r for r in inherited if _is_blocking_severity(r.get("severity"))]
        census += (f"; {len(inherited)} inherited from other work (not attributable "
                   f"to {scope})")
        if sev:
            # The number that must never go quiet. These stopped BLOCKING; they
            # did not stop existing, and a green run that omits them is the
            # silent drop ASK-526 refused to trade away.
            census += (f", of which {len(sev)} at blocking severity still open "
                       f"and now non-blocking here")
    print(census)
    if failures:
        for gid, tail in failures:
            sys.stderr.write(f"GATE RED: {gid}\n{tail}\n")
        return 1
    if not records and registered_total:
        # AN EMPTY EXECUTED SET IS NOT A PASS. Scar 2026-08-24 (ASK-1038): this line
        # said "all 0 regression gates green" against a 47-gate registry, and the
        # sentence was TRUE -- vacuously, because the closeout registrar wrote every
        # gate as historical-receipt, the one lifecycle filtered out just above.
        # Exit 0 was read as "the gates are green" for 29 days while nothing ran.
        print(f"[WARN] gates: {registered_total} gate(s) registered, NONE "
              f"executable -- 0 have lifecycle 'regression', so no regression "
              f"check ran. Exit 0 below covers the spillover verdict ONLY.")
    print(f"all {len(records)} regression gates green "
          f"({registered_total} registered); "
          f"{len(blocking)} blocking spillover item(s)")
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
    # choices, so the CLI refuses an unrecognized severity at the door rather
    # than storing it and letting the gate mis-bucket it (Codex, PR #110 r2).
    sp_add.add_argument("--severity", default="minor",
                        choices=SPILLOVER_KNOWN_SEVERITIES)
    # A DoR AT FILE TIME for anything the gate blocks on. See `_spillover_autopromote`.
    sp_add.add_argument("--dor", help="Definition of Ready, inline")
    sp_add.add_argument("--dor-file", dest="dor_file",
                        help="Definition of Ready, from a file")
    sp_add.add_argument("--title", help="issue title used when auto-promoting")
    sp_add.add_argument("--no-promote", dest="no_promote", action="store_true",
                        help="record only; skip the automatic Linear issue")
    sp_add.add_argument("--owner", default=None,
                        help=f"who owns it (default {DEFAULT_SPILLOVER_OWNER}); "
                             "never blank, see RULE-2026-08-24-B")
    sp_own = spill_sub.add_parser(
        "own", help="set the owner on one item or backfill every open item")
    sp_own.add_argument("id", nargs="?")
    sp_own.add_argument("--owner", default=None,
                        help=f"default {DEFAULT_SPILLOVER_OWNER}")
    sp_own.add_argument("--all-open", dest="all_open", action="store_true",
                        help="backfill every open item")
    sp_list = spill_sub.add_parser("list")
    sp_list.add_argument("--open", dest="open_only", action="store_true", help="only open items")
    sp_list.add_argument("--json", dest="as_json", action="store_true")
    sp_recl = spill_sub.add_parser(
        "reclassify", help="correct an item's severity via a new append-only event")
    sp_recl.add_argument("id")
    sp_recl.add_argument("--severity", required=True)
    sp_recl.add_argument("--reason", required=True,
                         help="why the severity is wrong; recorded on the event")

    spill_sub.add_parser(
        "needs-dor", help="open blocking items with no Linear issue yet (Sana's queue)")
    spill_sub.add_parser("check")
    spill_sub.add_parser("triage", help="read-only: open items grouped by severity and by source")
    sp_ack = spill_sub.add_parser(
        "ack", help="record that an issue named this item and did NOT fix it "
                    "(status unchanged; clears only that issue's closeout block)")
    sp_ack.add_argument("id")
    sp_ack.add_argument("--issue", required=True,
                        help="the issue id whose closeout this acknowledgement clears")
    sp_ack.add_argument("--reason", required=True,
                        help="why this issue did not fix it")

    sp_audit = spill_sub.add_parser(
        "promoted-audit",
        help="re-check every promoted row against the tracker; resolve the ones "
             "whose issue actually closed (sp-0d76a138)")
    sp_audit.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="report only; write nothing")
    sp_res = spill_sub.add_parser("resolve")
    sp_res.add_argument("id")
    sp_res.add_argument("--resolution-ref", dest="resolution_ref",
                        help="closed issue that fixed it: a local .prd-os issue-id, "
                             "or a Linear identifier (ASK-204) verified against Linear")
    sp_res.add_argument("--evidence",
                        help="auditable note recorded alongside a VERIFIED resolution "
                             "(e.g. 'PR #19 / 990d7c1'); never a substitute for closure")
    sp_res.add_argument("--resolution-commit", dest="resolution_commit",
                        help="sha of a MERGED commit whose message names this item id")
    sp_res.add_argument("--resolution-proof", dest="resolution_proof",
                        help="a command that PASSES here and FAILS at --broken-at; "
                             "the exit for an item fixed by a commit that never "
                             "named it (sp-1dfc48a8)")
    sp_res.add_argument("--broken-at", dest="broken_at",
                        help="pre-fix sha the proof command must FAIL at")
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
