#!/usr/bin/env python3
"""Portable DSSE issue-runner for the kipi-dsse plugin.

Loads issue specs, enforces scope, records receipts, gates stop. Repo root is
resolved via CLAUDE_PROJECT_DIR (set by Claude Code when hooks/commands run)
with a CWD walk-up fallback for tests and direct invocation. Issues, findings,
and state directories are read from `.prd-os/config.json` when present; when
absent, defaults are used that work for any generic instance.

Subcommands:
  load <issue-id>          Load spec, write active-issue state, print JSON summary
  status                   Print active issue + receipt state
  scope <path>             Exit 0 if path is in allowed_files (or carve-out), exit 2 otherwise
  gate                     Exit 0 if stop is allowed, exit 2 if gate blocks
  mark <receipt>           REFUSES (exit 2). A receipt is written only by the code
                           that computed it; the error names the verb to run.
  verify                   Run every required_check from the snapshot, store the
                           evidence, write the `verified` receipt if all pass
  triage                   Recompute in-scope pending/invalid findings, write the
                           `findings_triaged` receipt only when both are zero
  approve                  Flip spec status open -> in-progress; reset stale receipts
  amend --reason STR       Re-snapshot spec scope, clear verified+reviewed receipts, log amendment
  close                    Verify all receipts; flip status=closed; flush amendments to spec footer; clear state
  clear                    Clear active state (for abandoned work)
  allowed-files            Print snapshotted allowed_files as JSON array
  record-review <kind>     CLAIM a review slot (standard|adversarial) under cap.
                           Writes no receipt: the review has not run yet.
  complete-review <kind> --verdict STR --evidence-file PATH
                           Record a FINISHED review: hashes the reviewer's own
                           output, seals it to the issue, and writes `reviewed`
                           once EVERY kind has landed. Refuses without a slot,
                           without an artifact, or on an empty one.

Behavior contract mirrors the pre-plugin runner at
q-ktlyst/.q-system/scripts/issue-runner.py, with ONE deliberate break (ASK-402):
`mark` used to stamp any receipt and exit 0, so a receipt could be asserted by
code that had computed nothing. It now refuses. Every other subcommand keeps its
exit codes, stderr messages, and stdout JSON.

A caller still on `mark` is BROKEN, not degraded, and that is the point -- the
refusal names its replacement verb. `test_command_files_do_not_call_refused_verbs`
in test_computed_receipts.py holds the shipped command markdown to the same line.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from concurrency import ConcurrencyError, assert_no_active_prd  # noqa: E402


RECEIPT_FIELDS = ("verified", "reviewed", "findings_triaged")
REVIEW_KINDS = ("standard", "adversarial")
REVIEW_CAP_DEFAULTS = {"standard": 2, "adversarial": 1}
REVIEW_CAP_OVERRIDE_ENV = "ISSUE_ALLOW_REVIEW_REPEAT"

CONFIG_RELPATH = ".prd-os/config.json"
DEFAULT_ISSUES_DIR = ".prd-os/issues"
DEFAULT_FINDINGS_SUBDIR = "findings"
DEFAULT_STATE_DIR = ".claude/state"
DEFAULT_RECEIPTS_PATH = ".prd-os/receipts.jsonl"


# ---------------------------------------------------------------------------
# Repo root + config resolution
# ---------------------------------------------------------------------------


def _resolve_repo_root(cli_override: str | None) -> Path:
    """Locate the host repo. Priority: --repo-root, CLAUDE_PROJECT_DIR, CWD walk-up."""
    if cli_override:
        return Path(cli_override).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidate = Path(env).resolve()
        if candidate.is_dir():
            return candidate
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / CONFIG_RELPATH).is_file():
            return candidate
    return start


class Paths:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        cfg = self._load_config(repo_root)
        self.issues_dir = repo_root / cfg.get("issues_dir", DEFAULT_ISSUES_DIR)
        findings_override = cfg.get("findings_dir")
        if findings_override:
            # When a shared findings_dir is configured (e.g. `.prd-os/findings`
            # that also holds PRD findings), keep issue findings under an
            # `/issue/` subdir so the two types don't collide.
            self.findings_dir = repo_root / findings_override / "issue"
        else:
            self.findings_dir = self.issues_dir / DEFAULT_FINDINGS_SUBDIR
        state_dir = repo_root / cfg.get("state_dir", DEFAULT_STATE_DIR)
        self.state_path = state_dir / "active-issue.json"
        self.active_prd_state_path = state_dir / "active-prd.json"
        self.receipts_path = repo_root / cfg.get("receipts_path", DEFAULT_RECEIPTS_PATH)

    @staticmethod
    def _load_config(repo_root: Path) -> dict:
        path = repo_root / CONFIG_RELPATH
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Spec parsing (minimal YAML frontmatter — no external deps)
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        raise ValueError("spec missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("spec frontmatter not closed with ---")
    block = text[3:end].strip("\n")
    return _parse_yaml_block(block)


# Marker contract: issue specs must be generated by prd_split.py. The
# marker's position (first non-empty line after frontmatter) and format
# are enforced here; see prd-os/scripts/prd_split.py for the emitter.
MARKER_RE = re.compile(
    r"<!--\s+generated-by:\s+prd_split\.py\s+"
    r"prd=(?P<prd>\S+)\s+finding=(?P<finding>\S+)\s+at=(?P<at>\S+)\s+-->"
)


def _require_marker(text: str) -> str | None:
    """Return None if the spec carries a conforming marker, else an error string."""
    if not text.startswith("---"):
        return "issue spec rejected: missing frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return "issue spec rejected: frontmatter not closed"
    body = text[end + len("\n---"):]
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if MARKER_RE.fullmatch(stripped):
            return None
        return (
            "issue spec rejected: marker not generated by prd_split.py. "
            "Delete the spec and re-run /prd-split to regenerate it."
        )
    return (
        "issue spec rejected: empty body; expected generated-by marker "
        "from prd_split.py"
    )


def _parse_yaml_block(block: str) -> dict:
    result: dict = {}
    current_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - "):
            if current_key is None:
                raise ValueError("list item without key: " + raw)
            result.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" not in line:
            raise ValueError("cannot parse line: " + raw)
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            result[key] = []
            current_key = key
        elif value == "[]":
            result[key] = []
            current_key = None
        else:
            result[key] = value
            current_key = None
    return result


def _decode_bypass_check(value: str) -> str:
    """Turn a frontmatter bypass_check scalar into an sh-VALID shell command.

    prd_split serializes bypass_check via json.dumps (prd_split.py), so the
    stored value is a JSON flow scalar. Decode it SYMMETRICALLY with json.loads
    so nested double quotes (\\") unescape into a real command. The old code
    stripped ONE outer pair WITHOUT unescaping, leaving literal backslashes
    that died with "syntax error near unexpected token" under /bin/sh whenever
    a bypass_check used nested " (sp-8e9a12b8, 2026-06-28).

    Single-quoted / bare values (hand-authored, or a command ending in a
    legitimate 'quoted arg') are NOT JSON; strip one balanced single-quote pair
    only, preserving inner/trailing quotes (sp gate-truncation, 2026-06-23).
    """
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            return json.loads(value)
        except ValueError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] and value[0] == "'":
        return value[1:-1]
    return value


def _load_spec(paths: Paths, issue_id: str) -> tuple[Path, dict, str]:
    candidates = [
        paths.issues_dir / f"{issue_id}.md",
        paths.issues_dir / issue_id,
    ]
    for path in candidates:
        if path.is_file():
            text = path.read_text()
            return path, _parse_frontmatter(text), text
    raise FileNotFoundError(f"issue spec not found for id={issue_id!r}")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _read_state(paths: Paths) -> dict:
    if not paths.state_path.exists():
        return _empty_state()
    try:
        return _migrate_state(json.loads(paths.state_path.read_text()))
    except json.JSONDecodeError:
        return _empty_state()


def _findings_path(paths: Paths, issue_id: str) -> Path:
    return paths.findings_dir / f"{issue_id}-findings.jsonl"


def _count_in_scope_pending(paths: Paths, issue_id: str) -> tuple[int, list[str]]:
    path = _findings_path(paths, issue_id)
    if not path.is_file():
        return 0, []
    pending = 0
    bad: list[str] = []
    with path.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                bad.append(f"{path.name}:{lineno}: invalid JSON ({exc})")
                continue
            if not isinstance(rec, dict):
                bad.append(f"{path.name}:{lineno}: not an object")
                continue
            if rec.get("out_of_scope"):
                continue
            disp = rec.get("disposition")
            if disp == "pending":
                pending += 1
            elif disp in ("rejected", "deferred"):
                rationale = rec.get("rationale")
                if not isinstance(rationale, str) or not rationale.strip():
                    bad.append(
                        f"{rec.get('id', '?')}: disposition={disp!r} missing rationale"
                    )
    return pending, bad


def _empty_state() -> dict:
    return {
        "issue_id": None,
        "loaded_at": None,
        "spec_path": None,
        "receipts": {k: None for k in RECEIPT_FIELDS},
        "review_rounds": {k: 0 for k in REVIEW_KINDS},
        "allowed_files_snapshot": [],
        "required_checks_snapshot": [],
        "disallowed_files_snapshot": [],
        "amendments": [],
    }


def _migrate_state(state: dict) -> dict:
    if "review_rounds" not in state:
        state["review_rounds"] = {k: 0 for k in REVIEW_KINDS}
    else:
        for k in REVIEW_KINDS:
            state["review_rounds"].setdefault(k, 0)
    state.setdefault("allowed_files_snapshot", [])
    state.setdefault("required_checks_snapshot", [])
    state.setdefault("disallowed_files_snapshot", [])
    state.setdefault("amendments", [])
    return state


def _write_state(paths: Paths, state: dict) -> None:
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text(json.dumps(state, indent=2) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head_sha(repo_root: Path) -> str | None:
    """Return the current HEAD sha, or None if the tree has no commit yet."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _extract_marker_fields(text: str) -> dict[str, str] | None:
    """Return {prd_id, finding_id, at} from the spec's generated-by marker."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    body = text[end + len("\n---"):]
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = MARKER_RE.fullmatch(stripped)
        if m is None:
            return None
        return {
            "prd_id": m.group("prd"),
            "finding_id": m.group("finding"),
            "marker_at": m.group("at"),
        }
    return None


def _append_receipt(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _validate_deliverables_count(fm: dict) -> int | None:
    """Deliverable-count lock (prd-fable-discipline-2026-07-04): None when the
    spec has no `deliverables_count` (every pre-lock spec closes under the old
    rules, check skipped entirely); the int when present. A malformed value
    (non-integer, < 1) raises at LOAD so the defect surfaces at issue-start,
    never as a surprise refusal at closeout."""
    if "deliverables_count" not in fm:
        return None
    raw = fm.get("deliverables_count")
    # present-but-empty (`deliverables_count:`) and quoted values are
    # malformed, not absent: only an ABSENT key opts a spec out of the lock,
    # and the schema says bare integer (a quoted "2" is a string)
    text = str(raw).strip() if not isinstance(raw, list) else ""
    if not text.isdigit() or int(text) < 1:
        raise ValueError(
            f"deliverables_count must be a bare integer >= 1, got {raw!r}. "
            "Fix the spec before /issue-start."
        )
    return int(text)


def _count_checked_deliverables(text: str) -> tuple[int, int]:
    """(checked, listed) checkbox lines in the FIRST '## Deliverables'
    section, top-level boxes only. One section, column-0 boxes: an indented
    nested subtask or a second injected Deliverables section must not be able
    to satisfy the locked count (codex major, dsse-deliverable-count-lock).
    (0, 0) when the section is absent."""
    in_section = False
    section_seen = False
    checked = listed = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            if stripped.lower() == "## deliverables" and not section_seen:
                in_section = True
                section_seen = True
            continue
        if not in_section:
            continue
        if line != stripped:
            continue  # indented = nested subtask, not a deliverable
        if stripped.startswith("- [x]") or stripped.startswith("- [X]"):
            checked += 1
            listed += 1
        elif stripped.startswith("- [ ]"):
            listed += 1
    return checked, listed


def cmd_load(paths: Paths, args: argparse.Namespace) -> int:
    # Cross-runner concurrency: refuse to load an issue while a non-archived PRD
    # is active. Symmetric with prd-os's prd_runner, which refuses to start a
    # PRD while an issue is active. Reads active-prd.json directly.
    try:
        assert_no_active_prd(
            paths.active_prd_state_path, action=f"load issue {args.issue_id!r}"
        )
    except ConcurrencyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    path, fm, text = _load_spec(paths, args.issue_id)
    err = _require_marker(text)
    if err is not None:
        sys.stderr.write(err + "\n")
        return 2
    allowed = fm.get("allowed_files", []) or []
    checks = fm.get("required_checks", []) or []
    disallowed = fm.get("disallowed_files", []) or []
    reviews = fm.get("required_reviews", [])
    try:
        deliverables_count = _validate_deliverables_count(fm)
    except ValueError as exc:
        sys.stderr.write(f"cannot load {args.issue_id}: {exc}\n")
        return 2
    state = {
        "issue_id": fm.get("id", args.issue_id),
        "loaded_at": _now_iso(),
        "spec_path": str(path.relative_to(paths.repo_root)),
        "receipts": {k: None for k in RECEIPT_FIELDS},
        "review_rounds": {k: 0 for k in REVIEW_KINDS},
        "allowed_files_snapshot": list(allowed),
        "required_checks_snapshot": list(checks),
        "disallowed_files_snapshot": list(disallowed),
        "deliverables_count_snapshot": deliverables_count,
        "amendments": [],
    }
    _write_state(paths, state)
    print(json.dumps({
        "loaded": state["issue_id"],
        "spec_path": state["spec_path"],
        "title": fm.get("title", ""),
        "priority": fm.get("priority", ""),
        "allowed_files": allowed,
        "required_checks": checks,
        "required_reviews": reviews,
    }, indent=2))
    return 0


def cmd_status(paths: Paths, args: argparse.Namespace) -> int:
    state = _read_state(paths)
    print(json.dumps(state, indent=2))
    return 0


def _workflow_control_plane_paths(state: dict) -> set[str]:
    """Paths the DSSE workflow itself needs Claude to Edit while an issue is loaded.

    Only the active issue's own spec file. The state file is intentionally NOT
    here: it holds receipts and would allow synthetic receipts or silent
    deactivation if editable. The runner writes state via write_text from
    Python, which never passes through the Edit/Write tool scope check.
    """
    paths: set[str] = set()
    spec = state.get("spec_path")
    if spec:
        paths.add(_normalize_path(spec, None))
    return paths


def cmd_scope(paths: Paths, args: argparse.Namespace) -> int:
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        return 0
    target_rel = _normalize_path(args.path, paths.repo_root)
    if target_rel in _workflow_control_plane_paths(state):
        return 0
    _, fm, _ = _load_spec(paths, issue_id)
    allowed = fm.get("allowed_files", []) or []
    disallowed = fm.get("disallowed_files", []) or []
    if any(_match(pat, target_rel) for pat in disallowed):
        sys.stderr.write(
            f"DSSE scope deny: {target_rel} matched disallowed in {issue_id}\n"
        )
        return 2
    if not allowed:
        sys.stderr.write(
            "DSSE scope block: "
            f"allowed_files is empty for {issue_id} — no edits permitted "
            "outside the active spec (control-plane carve-out). "
            f"Widen allowed_files in {state.get('spec_path')} first, "
            "or set ISSUE_GATE_OFF=1.\n"
        )
        return 2
    if any(_match(pat, target_rel) for pat in allowed):
        return 0
    sys.stderr.write(
        "DSSE scope block: "
        f"{target_rel} is not in allowed_files for {issue_id}. "
        f"Update {state.get('spec_path')} first or set ISSUE_GATE_OFF=1.\n"
    )
    return 2


def _record_gate_bypass(paths: Paths, env_name: str) -> None:
    """Every override leaves a countable row (the linear-bypass pattern).

    ISSUE_GATE_OFF is agent-settable, which breaks the fleet's own "an agent
    cannot set it for itself" principle. A process cannot make its own env
    un-settable, so the honest fallback is to make each use visible rather
    than silent.
    """
    try:
        state = _read_state(paths)
        ledger = paths.repo_root / ".prd-os/gate-bypasses.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "env": env_name,
                "issue_id": state.get("issue_id"),
                "at": _now_iso(),
            }, sort_keys=True) + "\n")
    except OSError as exc:  # never let bookkeeping break the gate itself
        sys.stderr.write(f"warning: could not record gate bypass: {exc}\n")


def cmd_gate(paths: Paths, args: argparse.Namespace) -> int:
    if os.environ.get("ISSUE_GATE_OFF") == "1":
        _record_gate_bypass(paths, "ISSUE_GATE_OFF")
        return 0
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        return 0
    try:
        _, fm, _ = _load_spec(paths, issue_id)
    except FileNotFoundError:
        return 0
    status = (fm.get("status") or "").strip()
    if status in ("open", "closed"):
        return 0
    receipts = state.get("receipts", {})
    missing = [k for k in RECEIPT_FIELDS if not receipts.get(k)]
    if missing:
        sys.stderr.write(
            "DSSE stop gate: active issue "
            f"{issue_id} has missing receipts: {', '.join(missing)}. "
            "Run /issue-verify, /issue-review, /issue-closeout. "
            "Override with ISSUE_GATE_OFF=1.\n"
        )
        return 2
    pending, bad = _count_in_scope_pending(paths, issue_id)
    if pending or bad:
        msgs = []
        if pending:
            msgs.append(f"{pending} in-scope finding(s) still pending")
        if bad:
            msgs.append(f"{len(bad)} finding(s) with invalid disposition: {bad[:3]}")
        sys.stderr.write(
            "DSSE stop gate: active issue "
            f"{issue_id} cannot close: {'; '.join(msgs)}. "
            "Run /issue-closeout to triage. Override with ISSUE_GATE_OFF=1.\n"
        )
        return 2
    return 0


COMPUTING_VERB = {
    "verified": "verify",
    "findings_triaged": "triage",
    "reviewed": "complete-review <kind> --verdict <v> --evidence-file <path>",
}


def _write_receipt(paths: Paths, state: dict, field: str, extra: dict | None = None) -> str:
    """The ONLY writer of a receipt. Callers must have computed the fact first.

    Private on purpose: every caller lives in this module, immediately after
    the code that produced the evidence. There is no CLI verb that reaches it
    without doing the work.
    """
    stamp = _now_iso()
    state["receipts"][field] = stamp
    if extra:
        state.update(extra)
    _write_state(paths, state)
    return stamp


def cmd_mark(paths: Paths, args: argparse.Namespace) -> int:
    """Refuse. Kept as a subcommand so old callers get a teaching error.

    THE CLASS (founder, 2026-08-05): code that RECORDS a claim it never
    COMPUTED. Proven against the shipped runner in a virgin repo -- `mark
    verified`, `mark reviewed`, `mark findings_triaged` each exited 0 with zero
    work done, and the resulting receipts were byte-identical to honest ones.
    A receipt that can be asserted is not a receipt.

    Deleting the subcommand outright would surface as "invalid choice", which
    teaches nothing; this names the verb that computes each field.
    """
    if args.receipt not in RECEIPT_FIELDS:
        sys.stderr.write(f"unknown receipt: {args.receipt}\n")
        return 2
    verb = COMPUTING_VERB[args.receipt]
    sys.stderr.write(
        f"refusing to mark {args.receipt!r}: a receipt is written only by the "
        f"code that computed it.\n"
        f"Run `issue_runner.py {verb}` -- it does the work and records the "
        f"evidence in the same step.\n"
    )
    return 2


def _evidence_seal(issue_id: str, evidence: list) -> str:
    """A hash binding the `verified` receipt to the evidence that produced it.

    The write path was made honest first (`mark` refuses; verify/triage/
    record-review compute). The STORE stayed plain mutable JSON, so a receipt
    could still be typed straight into `.claude/state/active-issue.json` and
    read back as genuine -- proven 2026-08-05. issue_runner already excluded
    that file from agent-EDITABLE paths for exactly this reason, but the scope
    hook only matches Edit|Write|NotebookEdit, so a Bash heredoc writes it
    unimpeded.

    Seals the CONTENT, not the presence: command, returncode and output hash of
    every check, plus the issue id so a seal cannot be lifted between issues.
    Not a secret-keyed MAC -- anyone who can run this module can recompute it.
    It raises forgery from "edit one field" to "recompute the seal too", and
    pairs with the append-only judgment ledger for the tamper-evident story.
    """
    payload = json.dumps(
        {"issue_id": issue_id,
         "evidence": [{"command": e.get("command"),
                       "returncode": e.get("returncode"),
                       "output_sha256": e.get("output_sha256")}
                      for e in evidence]},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _review_seal(issue_id: str, completions: dict) -> str:
    """Bind the `reviewed` receipt to the reviewer ARTIFACTS that produced it.

    Same construction as `_evidence_seal`, for the same reason. `verified` was
    made honest by hashing what the checks actually emitted; `reviewed` kept
    taking the caller's word (`--verdict "APPROVE"`, checked only for
    non-emptiness) and Codex minted a receipt from a fabricated string on PR
    #110 round 6.

    WHAT THIS DOES AND DOES NOT CLAIM -- read before trusting it. It does NOT
    prove a reviewer ran: `complete-review` shares a trust boundary with the
    agent that invokes it, so anyone who can write the artifact can write a
    fake one. Nothing at this layer can close that, and the PRD side does not
    either (`findings_writer.cmd_record_review` restricts --source to an enum
    and then stamps `codex_reviewed_at` with nothing verifying a run).

    What it DOES do is make the receipt a function of a durable artifact
    instead of a typed string, which converts the failure modes that actually
    occur -- an interrupted review, a partial workflow, a mistaken invocation,
    an agent summarising from memory -- from "green receipt" into "no receipt".
    Forgery stops being a typo away and becomes a deliberate act that leaves a
    file behind. That is the same bar `verified` clears, stated honestly.
    """
    payload = json.dumps(
        {"issue_id": issue_id,
         "completions": [{"kind": k,
                          "artifact_sha256": c.get("artifact_sha256"),
                          "artifact_bytes": c.get("artifact_bytes"),
                          "verdict": c.get("verdict")}
                         for k, c in sorted(completions.items())]},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cmd_verify(paths: Paths, args: argparse.Namespace) -> int:
    """Run every required_check, record rc + output hash, write the receipt.

    The snapshot (taken at load) is the source, not the live spec: a spec
    edited mid-issue must not silently change what "verified" attested to.
    Evidence is recorded whether the run passes or fails -- a red run that
    stores nothing teaches nothing on the next read.
    """
    state = _read_state(paths)
    if not state.get("issue_id"):
        sys.stderr.write("no active issue\n")
        return 2
    checks = state.get("required_checks_snapshot") or []
    evidence = []
    for command in checks:
        result = subprocess.run(command, shell=True, cwd=paths.repo_root,
                                capture_output=True, text=True)
        blob = (result.stdout or "") + (result.stderr or "")
        evidence.append({
            "command": command,
            "returncode": result.returncode,
            "output_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
            "ran_at": _now_iso(),
        })
    failed = [e for e in evidence if e["returncode"] != 0]
    state["verified_evidence"] = evidence
    if failed:
        _write_state(paths, state)  # keep the evidence; withhold the receipt
        for e in failed:
            sys.stderr.write(f"check FAILED (rc={e['returncode']}): {e['command']}\n")
        sys.stderr.write(
            f"{len(failed)} of {len(evidence)} required_check(s) failed; "
            "no verified receipt written.\n")
        return 2
    if not checks:
        # An empty check list cannot attest to anything. Refusing keeps the
        # receipt meaning "the checks ran and passed" rather than "there were
        # none", which is the same hand-wave in a different shape.
        sys.stderr.write(
            "no required_checks in the spec snapshot; nothing to verify. "
            "Add a check to the issue spec, or amend the spec if it is wrong.\n")
        return 2
    state["verified_seal"] = _evidence_seal(state["issue_id"], evidence)
    stamp = _write_receipt(paths, state, "verified")
    print(json.dumps({"verified": state["issue_id"], "at": stamp,
                      "checks_run": len(evidence),
                      # issue-verify.md tells the agent to list the checks that
                      # ran. It could not: only a count was emitted (Codex r7,
                      # minor). The doc and the output are now one fact.
                      "checks": [e["command"] for e in evidence]}))
    return 0


def cmd_triage(paths: Paths, args: argparse.Namespace) -> int:
    """Compute triage completeness from the findings ledger, then write.

    `_count_in_scope_pending` already existed and was already used as a
    close-time gate -- the computation was there while the receipt stayed
    hand-stamped. Same function, now the writer.
    """
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        sys.stderr.write("no active issue\n")
        return 2
    pending, bad = _count_in_scope_pending(paths, issue_id)
    if pending or bad:
        msgs = []
        if pending:
            msgs.append(f"{pending} in-scope finding(s) still pending")
        if bad:
            msgs.append(f"{len(bad)} finding(s) with invalid disposition: {bad[:3]}")
        sys.stderr.write(
            f"cannot record findings_triaged for {issue_id}: {'; '.join(msgs)}.\n")
        return 2
    stamp = _write_receipt(paths, state, "findings_triaged")
    print(json.dumps({"findings_triaged": issue_id, "at": stamp}))
    return 0


def cmd_approve(paths: Paths, args: argparse.Namespace) -> int:
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        sys.stderr.write("no active issue\n")
        return 2
    path, fm, text = _load_spec(paths, issue_id)
    current = (fm.get("status") or "").strip()
    if current == "in-progress":
        print(json.dumps({"approved": issue_id, "status": "in-progress", "note": "already"}))
        return 0
    if current != "open":
        sys.stderr.write(
            f"cannot approve {issue_id}: status is {current!r}, expected 'open'\n"
        )
        return 2
    try:
        approved_count = _validate_deliverables_count(fm)
    except ValueError as exc:
        # validate before the status flip: a failed approve must not leave the
        # spec mutated to in-progress with a stale deliverables snapshot
        sys.stderr.write(f"cannot approve: {exc}\n")
        return 2
    new_text = re.sub(r"(?m)^status:\s*.+$", "status: in-progress", text, count=1)
    path.write_text(new_text)
    state["receipts"] = {k: None for k in RECEIPT_FIELDS}
    state["review_rounds"] = {k: 0 for k in REVIEW_KINDS}
    state["allowed_files_snapshot"] = list(fm.get("allowed_files", []) or [])
    state["required_checks_snapshot"] = list(fm.get("required_checks", []) or [])
    state["disallowed_files_snapshot"] = list(fm.get("disallowed_files", []) or [])
    state["deliverables_count_snapshot"] = approved_count
    state.setdefault("amendments", [])
    _write_state(paths, state)
    print(json.dumps({"approved": issue_id, "status": "in-progress"}))
    return 0


def cmd_amend(paths: Paths, args: argparse.Namespace) -> int:
    reason = (args.reason or "").strip()
    if not reason:
        sys.stderr.write("amend requires a non-empty --reason\n")
        return 2
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        sys.stderr.write("no active issue\n")
        return 2
    _, fm, _ = _load_spec(paths, issue_id)
    old_snapshot = {
        "allowed_files": list(state.get("allowed_files_snapshot", []) or []),
        "required_checks": list(state.get("required_checks_snapshot", []) or []),
        "disallowed_files": list(state.get("disallowed_files_snapshot", []) or []),
        "deliverables_count": state.get("deliverables_count_snapshot"),
    }
    try:
        amended_count = _validate_deliverables_count(fm)
    except ValueError as exc:
        sys.stderr.write(f"cannot amend: {exc}\n")
        return 2
    new_snapshot = {
        "allowed_files": list(fm.get("allowed_files", []) or []),
        "required_checks": list(fm.get("required_checks", []) or []),
        "disallowed_files": list(fm.get("disallowed_files", []) or []),
        "deliverables_count": amended_count,
    }
    state["allowed_files_snapshot"] = new_snapshot["allowed_files"]
    state["required_checks_snapshot"] = new_snapshot["required_checks"]
    state["disallowed_files_snapshot"] = new_snapshot["disallowed_files"]
    state["deliverables_count_snapshot"] = amended_count
    receipts = state.setdefault("receipts", {k: None for k in RECEIPT_FIELDS})
    receipts["verified"] = None
    receipts["reviewed"] = None
    # The per-kind completions are WHY `reviewed` can be rewritten, so clearing
    # the receipt without clearing them is not a reset. Codex round 4, with a
    # repro: after an amend, `complete-review standard` alone saw adversarial
    # still "completed" from the pre-amend scope and re-earned the receipt --
    # a two-review receipt for one review, against the NEW scope.
    state["review_completions"] = {}
    entry = {
        "timestamp": _now_iso(),
        "reason": reason,
        "old_snapshot": old_snapshot,
        "new_snapshot": new_snapshot,
    }
    state.setdefault("amendments", []).append(entry)
    _write_state(paths, state)
    print(json.dumps({
        "amended": issue_id,
        "at": entry["timestamp"],
        "reason": reason,
        "cleared_receipts": ["verified", "reviewed"],
        "amendment_count": len(state["amendments"]),
    }, indent=2))
    return 0


def cmd_close(paths: Paths, args: argparse.Namespace) -> int:
    state = _read_state(paths)
    issue_id = state.get("issue_id")
    if not issue_id:
        sys.stderr.write("no active issue\n")
        return 2
    missing = [k for k in RECEIPT_FIELDS if not state["receipts"].get(k)]
    if missing:
        sys.stderr.write(
            f"cannot close {issue_id}: missing receipts {', '.join(missing)}\n"
        )
        return 2
    pending, bad = _count_in_scope_pending(paths, issue_id)
    if pending or bad:
        msgs = []
        if pending:
            msgs.append(f"{pending} in-scope finding(s) still pending")
        if bad:
            msgs.append(f"invalid disposition records: {bad[:3]}")
        sys.stderr.write(
            f"cannot close {issue_id}: {'; '.join(msgs)}\n"
        )
        return 2
    path, fm, text = _load_spec(paths, issue_id)
    sha = _git_head_sha(paths.repo_root)
    if not sha:
        sys.stderr.write(
            f"cannot close {issue_id}: no git commit sha for working tree. "
            "Commit your work first so the receipt can pin to HEAD.\n"
        )
        return 2
    marker = _extract_marker_fields(text)
    if marker is None:
        sys.stderr.write(
            f"cannot close {issue_id}: spec is missing a prd_split.py "
            "generated-by marker. Regenerate the spec via /prd-split.\n"
        )
        return 2
    # Spine contract enforcement (prd-os-spine-native), BEFORE the status
    # flip so a failure leaves the issue open:
    #   deletes — every regex proven GONE from tracked source (the deletion
    #             rule is machinery now, not commit discipline)
    #   bypass_check — auto-registered into the permanent gate registry; an
    #             append failure aborts close.
    contract_err = _enforce_spine_contract(paths, fm, marker, issue_id)
    if contract_err:
        sys.stderr.write(contract_err)
        return 2

    # Wiring contract (RCA 2026-06-24): a closeout gate verified "tests pass in
    # this tree", never "the work is actually committed". A created-but-unstaged
    # file passed every gate and vanished on a fresh checkout. This blocks close
    # until every allowed_file that exists on disk is git-tracked in its own repo
    # (nested repos resolve via the file's directory).
    wiring_err = _enforce_wiring_contract(paths, fm, issue_id)
    if wiring_err:
        sys.stderr.write(wiring_err)
        return 2

    # Deliverable-count lock: the count was snapshotted at load/approve, so a
    # mid-issue spec edit cannot shrink the promise; only an explicit
    # founder-gated amend re-snapshots it. Absent snapshot = pre-lock spec,
    # old rules, no check.
    locked_count = state.get("deliverables_count_snapshot")
    if locked_count is not None:
        checked, listed = _count_checked_deliverables(text)
        if checked != locked_count:
            sys.stderr.write(
                f"cannot close {issue_id}: deliverables lock — the spec "
                f"promises {locked_count} deliverable(s), {checked} checked "
                f"under '## Deliverables' ({listed} listed). Check off what "
                "shipped, or amend the spec via /issue-amend (founder-gated).\n"
            )
            return 2

    # The `verified` receipt must still match the evidence that produced it.
    # Without this, close trusts a field anyone with filesystem access can type.
    if state["receipts"].get("verified"):
        expected = _evidence_seal(issue_id, state.get("verified_evidence") or [])
        if state.get("verified_seal") != expected:
            sys.stderr.write(
                f"cannot close {issue_id}: the verified receipt does not match "
                "its evidence.\n"
                "Either the receipt was written without running the checks, or "
                "the recorded\nevidence was edited afterwards. Re-run "
                "`issue_runner.py verify`.\n")
            return 2

    # Same bar as `verified` above: the receipt must still match the artifacts
    # that produced it, and every review kind must be present. Without this,
    # close trusts a field anyone with filesystem access can type.
    if state["receipts"].get("reviewed"):
        completions = state.get("review_completions") or {}
        missing = [k for k in REVIEW_KINDS if k not in completions]
        if missing:
            sys.stderr.write(
                f"cannot close {issue_id}: the reviewed receipt is set but "
                f"{missing} never completed.\n")
            return 2
        # REREAD the artifacts. The seal proves the stored RECORD is
        # self-consistent; it says nothing about the file still being there.
        # Codex round 7, with a repro: delete the artifact after
        # complete-review and close still passed, because both sides of the
        # comparison came from the same cached metadata. Sealing a hash you
        # never recompute is a checksum of your own memory.
        for kind, c in sorted(completions.items()):
            raw = c.get("artifact_path")
            if not raw:
                sys.stderr.write(
                    f"cannot close {issue_id}: the {kind} completion records no "
                    "artifact path.\n")
                return 2
            art = Path(raw)
            if not art.is_absolute():
                art = paths.repo_root / art
            if not art.is_file():
                sys.stderr.write(
                    f"cannot close {issue_id}: the {kind} reviewer artifact is "
                    f"gone: {art}\n"
                    "The receipt attests to a file that no longer exists. "
                    "Re-run the review.\n")
                return 2
            blob = art.read_bytes()
            if not blob.strip():
                sys.stderr.write(
                    f"cannot close {issue_id}: the {kind} reviewer artifact is "
                    f"now empty: {art}\n")
                return 2
            # sha256 alone. A byte-count comparison here is subsumed by the
            # hash -- no tamper can change the length without changing the
            # digest -- so it is a branch no test can isolate, and an
            # unkillable branch is one nobody can prove works. The count stays
            # in the SEAL payload, where it is data rather than a check.
            if hashlib.sha256(blob).hexdigest() != c.get("artifact_sha256"):
                sys.stderr.write(
                    f"cannot close {issue_id}: the {kind} reviewer artifact "
                    f"changed after it was recorded: {art}\n"
                    "Re-run `issue_runner.py complete-review "
                    f"{kind}` against the current output.\n")
                return 2

        if state.get("reviewed_seal") != _review_seal(issue_id, completions):
            sys.stderr.write(
                f"cannot close {issue_id}: the reviewed receipt does not match "
                "its reviewer artifacts.\n"
                "Either the receipt was written without a review, or the "
                "recorded evidence was\nedited afterwards. Re-run "
                "`issue_runner.py complete-review <kind>`.\n")
            return 2

    closed_at = _now_iso()
    receipt = {
        "issue_id": issue_id,
        "prd_id": marker["prd_id"],
        "finding_id": marker["finding_id"],
        "closed_at": closed_at,
        "verified_at": state["receipts"].get("verified"),
        "reviewed_at": state["receipts"].get("reviewed"),
        "findings_triaged_at": state["receipts"].get("findings_triaged"),
        "commit_sha": sha,
    }
    _append_receipt(paths.receipts_path, receipt)
    new_text = re.sub(
        r"(?m)^status:\s*.+$", "status: closed", text, count=1
    )
    amendments = state.get("amendments") or []
    if amendments:
        new_text = _append_amendments_footer(new_text, amendments)
    path.write_text(new_text)
    _write_state(paths, _empty_state())
    print(json.dumps({
        "closed": issue_id,
        "spec": str(path.relative_to(paths.repo_root)),
        "amendments_flushed": len(amendments),
        "commit_sha": sha,
        "receipt": str(paths.receipts_path.relative_to(paths.repo_root)),
    }))
    return 0


def _file_is_git_tracked(abspath) -> bool:
    """True iff abspath is tracked in whatever git repo contains it. Runs git
    from the file's own directory so a NESTED repo (a project repo inside the
    instance) resolves to its own index, not the outer one."""
    import subprocess as _subprocess
    try:
        result = _subprocess.run(
            ["git", "-C", str(abspath.parent), "ls-files", "--error-unmatch",
             str(abspath)],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def _enforce_wiring_contract(paths, fm: dict, issue_id: str) -> str:
    """Block close when an allowed_file that EXISTS on disk is not git-tracked.

    Catches the create-but-never-stage miss: a new source/test file passes a
    working-tree gate (it is there, tests pass) but was never committed, so it
    vanishes on a fresh checkout and its standing gate cannot run. Only the
    issue's own declared files are checked, so there are no false positives from
    unrelated untracked files."""
    allowed = fm.get("allowed_files") or []
    untracked = []
    for rel in allowed:
        abspath = paths.repo_root / rel
        if abspath.exists() and not _file_is_git_tracked(abspath):
            untracked.append(rel)
    if not untracked:
        return ""
    lines = [
        f"cannot close {issue_id}: wiring contract failed — "
        f"{len(untracked)} allowed_file(s) exist on disk but are NOT git-tracked "
        "(created but never committed; they would vanish on a fresh checkout and "
        "their gate could not run):",
    ]
    lines += [f"    - {u}" for u in untracked]
    lines.append("  Fix: commit them (git add <file>), then re-run close.")
    return "\n".join(lines) + "\n"


_DELETES_EXCLUDE = ("tests/", ".prd-os/", "docs/", "q-system/output/")


def _enforce_spine_contract(paths, fm: dict, marker: dict, issue_id: str) -> str:
    """Returns an error string (close aborts) or '' (close proceeds)."""
    import subprocess as _subprocess
    deletes = fm.get("deletes") or []
    if isinstance(deletes, str):
        deletes = [deletes]
    if deletes:
        # The deletion rule targets the COMMITTED tree (untracked files are
        # not shipped); the type list covers every text-source family so a
        # bypass cannot hide in JS/CSS/config (codex finding).
        tracked = _subprocess.run(
            ["git", "ls-files", "*.py", "*.html", "*.js", "*.ts", "*.css",
             "*.sh", "*.yaml", "*.yml", "*.md", "*.json"],
            cwd=paths.repo_root, capture_output=True, text=True).stdout.splitlines()
        tracked = [f for f in tracked
                   if not any(part in f for part in _DELETES_EXCLUDE)]
        import re as _re
        for pattern in deletes:
            rx = _re.compile(pattern)
            for rel in tracked:
                try:
                    content = (paths.repo_root / rel).read_text(errors="ignore")
                except OSError:
                    continue
                if rx.search(content):
                    return (f"cannot close {issue_id}: deletes pattern "
                            f"{pattern!r} still present in {rel} — the old "
                            "path must be GONE, not shadowed.\n")
    bypass_check = _decode_bypass_check(fm.get("bypass_check") or "")
    if bypass_check:
        # RUN it before recording it. Registration alone wrote a permanently
        # red standing gate into a registry that only grows and has no
        # hand-clear (sp-50db1764): measured across 64 open issue specs, 2 of
        # the 6 reachable bypass_checks exited 5 (pytest collected nothing).
        # A green that was never executed is not evidence of anything.
        import subprocess as _subprocess_run
        try:
            result = _subprocess_run.run(
                bypass_check, shell=True, cwd=paths.repo_root,
                capture_output=True, text=True, timeout=900)
        except _subprocess_run.TimeoutExpired:
            return (f"cannot close {issue_id}: bypass_check exceeded 900s "
                    "without exiting — nothing registered.\n")
        if result.returncode == 5:
            tail = "\n".join(
                (result.stdout + result.stderr).strip().splitlines()[-5:])
            return (f"cannot close {issue_id}: bypass_check exited 5 "
                    "(pytest collected NOTHING — a zero-selection gate can "
                    f"never go green):\n{tail}\n")
        if result.returncode != 0:
            tail = "\n".join(
                (result.stdout + result.stderr).strip().splitlines()[-5:])
            return (f"cannot close {issue_id}: bypass_check exited "
                    f"{result.returncode}:\n{tail}\n")
        try:
            sys.path.insert(0, str(paths.repo_root / "plugins" / "prd-os" / "scripts"))
            import prd_runner as _prd_runner
            from config import load as _load_config
            cfg = _load_config(paths.repo_root)
            # LIFECYCLE IS EXPLICIT, NEVER DEFAULTED. Scar 2026-08-24 (ASK-1038):
            # this call omitted `lifecycle=`, so it took LEGACY_GATE_LIFECYCLE,
            # which is "historical-receipt" -- the one value `gates run` filters
            # OUT before executing. The only producer of gates was writing the
            # one lifecycle the only consumer refuses to run, so `gates run`
            # printed "all 0 regression gates green" against a 47-gate registry
            # and had executed nothing since 2026-07-26. 47 closeouts registered
            # a permanent proof; all 47 were inert from the moment they landed.
            #
            # A bypass_check IS a permanent regression proof -- that is what the
            # registry section header calls it -- so `regression` is the correct
            # value and it is passed here rather than relied on as a default.
            # "legacy" in the constant's name reads as "applies to old rows" to
            # every reviewer, which is exactly why nobody caught it for 29 days.
            out = _prd_runner.gate_register(
                cfg, prd_id=marker["prd_id"], issue_id=issue_id,
                command=bypass_check, lifecycle="regression")
        except Exception as exc:
            return (f"cannot close {issue_id}: bypass_check gate registration "
                    f"failed ({exc}) — the permanent registry must record it "
                    "before close.\n")
        sys.stderr.write(f"gate registered: {out['gate_id']}\n")
    return ""


def _render_amendment_entries(amendments: list) -> str:
    lines: list[str] = []
    for entry in amendments:
        lines.append("")
        lines.append(f"### {entry.get('timestamp', '')}")
        lines.append(f"Reason: {entry.get('reason', '').strip()}")
        lines.append("")
        lines.append("Before:")
        old = entry.get("old_snapshot", {}) or {}
        lines.append(f"- allowed_files: {old.get('allowed_files', [])}")
        lines.append(f"- required_checks: {old.get('required_checks', [])}")
        lines.append(f"- disallowed_files: {old.get('disallowed_files', [])}")
        lines.append("")
        lines.append("After:")
        new = entry.get("new_snapshot", {}) or {}
        lines.append(f"- allowed_files: {new.get('allowed_files', [])}")
        lines.append(f"- required_checks: {new.get('required_checks', [])}")
        lines.append(f"- disallowed_files: {new.get('disallowed_files', [])}")
    return "\n".join(lines) + "\n"


def _append_amendments_footer(text: str, amendments: list) -> str:
    """Append unflushed amendment entries under an '## Amendments' section.

    If the section already exists (spec closed once, reopened, amended, closed
    again — unusual but possible), new entries append below without duplicating
    the header.
    """
    entries = _render_amendment_entries(amendments)
    separator = "" if text.endswith("\n") else "\n"
    if "## Amendments" in text:
        return text + separator + entries
    return text + separator + "\n## Amendments\n" + entries


def cmd_clear(paths: Paths, args: argparse.Namespace) -> int:
    _write_state(paths, _empty_state())
    print("cleared")
    return 0


def cmd_allowed_files(paths: Paths, args: argparse.Namespace) -> int:
    state = _read_state(paths)
    if not state.get("issue_id"):
        sys.stderr.write("no active issue\n")
        return 2
    print(json.dumps(state.get("allowed_files_snapshot", [])))
    return 0


def cmd_record_review(paths: Paths, args: argparse.Namespace) -> int:
    if args.kind not in REVIEW_KINDS:
        sys.stderr.write(f"kind must be one of {REVIEW_KINDS}; got {args.kind!r}\n")
        return 2
    state = _read_state(paths)
    if not state.get("issue_id"):
        sys.stderr.write("no active issue\n")
        return 2
    rounds = state.setdefault("review_rounds", {k: 0 for k in REVIEW_KINDS})
    current = rounds.get(args.kind, 0)
    cap = REVIEW_CAP_DEFAULTS[args.kind]
    override = os.environ.get(REVIEW_CAP_OVERRIDE_ENV) == "1"
    if current >= cap and not override:
        sys.stderr.write(
            f"review cap reached for {args.kind}: {current}/{cap}. "
            f"Findings beyond this round should auto-defer. "
            f"Override with {REVIEW_CAP_OVERRIDE_ENV}=1 if you really want another round.\n"
        )
        return 2
    rounds[args.kind] = current + 1
    # CLAIMS THE SLOT. Deliberately does NOT write the `reviewed` receipt.
    #
    # It did, for one commit, and Codex caught it with a reproducer (PR #110
    # round 2): /issue-review claims the slot BEFORE the reviewer runs, so the
    # receipt landed on a review that had not happened yet. An interrupted or
    # errored review then left a valid-looking `reviewed` receipt and close
    # accepted it. That is the exact class this file exists to kill -- a receipt
    # written by code that computed nothing -- reintroduced by the fix for it.
    #
    # Claiming a slot and completing a review are two facts. `complete-review`
    # writes the receipt, and only after a verdict is durably recorded.
    _write_state(paths, state)
    print(json.dumps({
        "kind": args.kind,
        "round": rounds[args.kind],
        "cap": cap,
        "capped": rounds[args.kind] >= cap,
    }))
    return 0


def cmd_complete_review(paths: Paths, args: argparse.Namespace) -> int:
    """Record that a review actually finished, then write the `reviewed` receipt.

    The receipt is a function of a durably-stored verdict, never of intent to
    review. Refuses if no slot was claimed for this kind, so the completion can
    never precede the round it belongs to.
    """
    if args.kind not in REVIEW_KINDS:
        sys.stderr.write(f"kind must be one of {REVIEW_KINDS}; got {args.kind!r}\n")
        return 2
    state = _read_state(paths)
    if not state.get("issue_id"):
        sys.stderr.write("no active issue\n")
        return 2
    claimed = (state.get("review_rounds") or {}).get(args.kind, 0)
    if not claimed:
        sys.stderr.write(
            f"no {args.kind} review round was claimed; run "
            f"`record-review {args.kind}` before the reviewer, and "
            f"`complete-review {args.kind}` after it returns.\n")
        return 2
    if not (args.verdict or "").strip():
        sys.stderr.write("--verdict must be a non-empty verdict from the reviewer\n")
        return 2
    # The artifact is the evidence. A verdict typed without one is a claim.
    artifact = Path(args.evidence_file)
    if not artifact.is_absolute():
        artifact = paths.repo_root / artifact
    if not artifact.is_file():
        sys.stderr.write(
            f"--evidence-file does not exist: {artifact}\n"
            "The reviewer's own output IS the evidence. Write it to a file and "
            "pass that path;\na clean pass records an explicit "
            "'ran, found nothing' artifact rather than an absence.\n")
        return 2
    blob = artifact.read_bytes()
    if not blob.strip():
        sys.stderr.write(f"--evidence-file is empty: {artifact}\n")
        return 2
    completions = state.setdefault("review_completions", {})
    completions[args.kind] = {
        "verdict": args.verdict,
        "round": claimed,
        "completed_at": _now_iso(),
        "artifact_path": str(artifact),
        "artifact_sha256": hashlib.sha256(blob).hexdigest(),
        "artifact_bytes": len(blob),
    }
    # The receipt attests that THE REVIEW happened, and /issue-review requires
    # two kinds. Writing it after the first completion let `close` report
    # reviewed work while the adversarial pass had never run -- Codex caught
    # exactly that, twice (PR #110 rounds 2 and 3). One completion is not the
    # review; it is half of it.
    missing = [k for k in REVIEW_KINDS if k not in completions]
    if missing:
        _write_state(paths, state)
        print(json.dumps({"recorded": args.kind, "verdict": args.verdict,
                          "awaiting": missing, "reviewed": None}))
        return 0
    state["reviewed_seal"] = _review_seal(state["issue_id"], completions)
    stamp = _write_receipt(paths, state, "reviewed")
    print(json.dumps({"reviewed": state["issue_id"], "kind": args.kind,
                      "verdict": args.verdict, "at": stamp}))
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_path(target: str, repo_root: Path | None) -> str:
    """Resolve target to a repo-relative path, collapsing '..' segments.

    Inputs that escape the repo root are returned as absolute filesystem
    paths so they cannot accidentally fnmatch any repo-rooted allowed_files
    glob. Falls back to the raw input when repo_root is unknown (used by
    control-plane-paths resolution where the spec path is already relative).
    """
    p = Path(target)
    if repo_root is None:
        return target
    if not p.is_absolute():
        p = repo_root / p
    resolved = p.resolve()
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def _match(pattern: str, path: str) -> bool:
    if "**" in pattern:
        regex = "^" + re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
        return re.match(regex, path) is not None
    return fnmatch.fnmatch(path, pattern)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        help="override repo root (default: CLAUDE_PROJECT_DIR or walk-up)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_load = sub.add_parser("load")
    p_load.add_argument("issue_id")
    p_load.set_defaults(func=cmd_load)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p_scope = sub.add_parser("scope")
    p_scope.add_argument("path")
    p_scope.set_defaults(func=cmd_scope)

    sub.add_parser("gate").set_defaults(func=cmd_gate)

    p_mark = sub.add_parser("mark")
    p_mark.add_argument("receipt")
    p_mark.set_defaults(func=cmd_mark)

    sub.add_parser("verify").set_defaults(func=cmd_verify)
    sub.add_parser("triage").set_defaults(func=cmd_triage)

    sub.add_parser("approve").set_defaults(func=cmd_approve)

    p_amend = sub.add_parser("amend")
    p_amend.add_argument("--reason", required=True, help="why the spec is being amended")
    p_amend.set_defaults(func=cmd_amend)

    sub.add_parser("close").set_defaults(func=cmd_close)
    sub.add_parser("clear").set_defaults(func=cmd_clear)
    sub.add_parser("allowed-files").set_defaults(func=cmd_allowed_files)

    p_complete = sub.add_parser("complete-review")
    p_complete.add_argument("kind")
    p_complete.add_argument("--verdict", required=True,
                            help="the reviewer's verdict, sealed with the artifact")
    p_complete.add_argument("--evidence-file", required=True,
                            help="path to the reviewer's OWN output; hashed and "
                                 "sealed into the receipt")
    p_complete.set_defaults(func=cmd_complete_review)

    p_record = sub.add_parser("record-review")
    p_record.add_argument("kind", help="standard|adversarial")
    p_record.set_defaults(func=cmd_record_review)

    args = parser.parse_args(argv)
    paths = Paths(_resolve_repo_root(args.repo_root))
    return args.func(paths, args)


if __name__ == "__main__":
    sys.exit(main())
