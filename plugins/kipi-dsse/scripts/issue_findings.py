#!/usr/bin/env python3
"""DSSE issue per-finding writer for the kipi-dsse plugin.

Mirrors the prd-os findings_writer pattern. Codex review can produce many
findings on a single issue; the gate must terminate without forcing every
finding to be patched. This writer persists each finding with an explicit
disposition (pending|accepted|rejected|deferred). The DSSE issue-runner gate
accepts deferred and rejected findings (with rationale) and only blocks on
pending in-scope findings.

Repo root resolves via CLAUDE_PROJECT_DIR, then CWD walk-up. Findings dir
reads from `.prd-os/config.json` when present. Default storage is under the
host instance's issues dir: `<issues_dir>/findings/<issue-id>-findings.jsonl`.
When `findings_dir` is configured (shared with PRD findings), issue findings
go under `<findings_dir>/issue/`.

Subcommands:

  add <issue-id> --source <codex-review|codex-adversarial|manual> [--allowed-files-json '<json>']
      Reads a JSON array on stdin. Each item: {severity, body, affected_path}.
      Validates affected_path against allowed_files (when supplied) and stamps
      out_of_scope=true for paths outside the list. Records get sequential
      finding-N ids and disposition=pending.

  list <issue-id> [--only-pending] [--only-in-scope]
      Prints the findings file as a JSON array.

  set-disposition <issue-id> <finding-id> <disposition> [--rationale <text>] [--followup-issue-id <id>]
      Updates one record. rejected and deferred require --rationale. Stamps
      resolved_at when leaving pending; clears it when returning.

  count <issue-id> [--in-scope-pending]
      Prints counts. With --in-scope-pending, prints just the count of in-scope
      pending findings (the gate-blocking number).

Exit codes:
  0  success
  2  validation error, schema violation, missing record
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

CONFIG_RELPATH = ".prd-os/config.json"
DEFAULT_ISSUES_DIR = "issues"
DEFAULT_FINDINGS_SUBDIR = "findings"

SEVERITIES = ("blocker", "major", "minor", "nit")
# The issue-level twin of prd-os's REVIEWER_SOURCES. Widened 2026-07-26 for the
# same reason: Codex is out of credits until 2026-08-24 and the reviewer is a
# Claude senior-staff-engineer subagent, so accepting only codex-* forced that
# reviewer to either stamp a false provenance record or record nothing. Fixing
# this only at the PRD level left the issue path still lying.
SOURCES = (
    "codex-review",
    "codex-adversarial",
    "claude-review",
    "claude-adversarial",
    "manual",
)
DISPOSITIONS = ("pending", "accepted", "rejected", "deferred")
REQUIRES_RATIONALE = ("rejected", "deferred")
# Dispositions that CLOSE a defer-* spillover item. `pending` is deliberately
# absent and that absence is the whole point: see _sync_spillover_for_finding.
DECIDED_DISPOSITIONS = ("accepted", "rejected")

# ISSUE severity -> SPILLOVER LEDGER severity. Two vocabularies, edited in two
# plugins by two different changes, and `nit` was legal on this side and unknown
# on the ledger's for as long as both existed.
#
# prd_runner._is_blocking_severity treats an UNKNOWN severity as BLOCKING, which
# is correct and deliberate (ASK-402: `--severity critical` used to read as minor
# and green the gate). Handing it `nit` therefore inverted the intent completely
# -- deferring the single most trivial finding a reviewer can file turned the
# standing gate RED, fleet-wide, until a human hand-resolved the row. The gate
# got louder the less the finding mattered.
#
# Fixed by translating at the boundary, not by widening the ledger's allowlist:
# `nit` is this plugin's word and the ledger should not have to learn it.
# `.get(sev, sev)` on purpose -- an unmapped value passes through unchanged and
# the ledger then treats it as BLOCKING, which is the right direction for
# something nobody has classified.
#
# BE PRECISE ABOUT REACH: `_validate` rejects any severity outside SEVERITIES
# before a record can reach here, so with all four currently mapped this
# fallback is UNREACHABLE from the CLI and equivalent to defaulting to "minor".
# It is a belt for a hand-edited findings file and for the window after a new
# severity is added. The real guard is
# test_every_issue_severity_maps_into_the_ledger_vocabulary, which fails the
# moment a severity is added here without a translation. Adversarial review
# showed a mutant changing this fallback survives the suite -- correctly, since
# nothing can reach it.
LEDGER_SEVERITY = {
    "blocker": "blocker",
    "major": "major",
    "minor": "minor",
    "nit": "minor",
}
ID_RE = re.compile(r"^finding-([0-9]+)$")
RECORD_FIELDS = (
    "id",
    "issue_id",
    "source",
    "severity",
    "disposition",
    "body",
    "affected_path",
    "out_of_scope",
    "created_at",
)


def _resolve_repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists() or (candidate / CONFIG_RELPATH).is_file():
            return candidate
    return cwd


def _load_config(repo_root: Path) -> dict:
    path = repo_root / CONFIG_RELPATH
    if not path.is_file():
        return {}
    try:
        with path.open() as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _findings_dir(repo_root: Path) -> Path:
    cfg = _load_config(repo_root)
    findings_override = cfg.get("findings_dir")
    if findings_override:
        return repo_root / findings_override / "issue"
    issues_dir = cfg.get("issues_dir", DEFAULT_ISSUES_DIR)
    return repo_root / issues_dir / DEFAULT_FINDINGS_SUBDIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _findings_path(repo_root: Path, issue_id: str) -> Path:
    return _findings_dir(repo_root) / f"{issue_id}-findings.jsonl"


def _load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    with path.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{lineno}: not an object")
            out.append(rec)
    return out


@contextlib.contextmanager
def _findings_lock(path: Path):
    """Serialize read-modify-REWRITE of ONE issue's findings file across processes.

    `_write_all` opens "w", so it truncates. Every mutating command here is
    `_load` -> mutate -> `_write_all`, which was unlocked, and the findings file
    is the record of what was decided. Measured on 6 concurrent dispositions of
    6 DIFFERENT findings, 15 trials:
        5 trials LOST AN UPDATE -- the command exited 0 and printed its success
          JSON while the disposition was not on disk, because a concurrent
          writer rewrote the whole file from a pre-state it had already read.
        3 trials hit "finding not found" (exit 2) -- a read landed inside
          another process's truncate and saw an empty file.
    A silently-dropped triage decision is the exact failure this whole change
    exists to prevent, and it was in the file the fan-out was protecting.

    Found by the concurrency test written for the SPILLOVER lock: that lock does
    not cover this, because `_write_all` runs BEFORE the fan-out and on a
    different file. Two writers to one file is a corruption waiting for a race,
    and there were two files.

    LOCK ORDER IS ALWAYS findings-then-spillover. The fan-out takes
    `_spillover_lock` INSIDE this one; nothing takes them in the other order, so
    there is no cycle to deadlock on.

    DEGRADES, NEVER REFUSES, matching prd_runner._spillover_lock verbatim in
    intent: taking the lock has to CREATE a file, so it needs write permission
    on the DIRECTORY, while rewriting the existing findings file needs it only
    on the FILE. Read-only sandboxes are real here. A lock we cannot take
    degrades loudly to the behaviour that shipped for months.
    """
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
            f"WARNING: could not lock the findings file ({exc}); proceeding "
            "UNLOCKED.\nA concurrent set-disposition can report success while "
            "its change is overwritten by another process's stale copy.\n")
        yield
        return
    try:
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _write_all(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _validate(rec: dict, where: str) -> None:
    for field in RECORD_FIELDS:
        if field not in rec:
            raise ValueError(f"{where}: missing field {field!r}")
    if not isinstance(rec["id"], str) or not ID_RE.match(rec["id"]):
        raise ValueError(f"{where}: id must match finding-N; got {rec['id']!r}")
    if rec["source"] not in SOURCES:
        raise ValueError(f"{where}: source must be in {SOURCES}; got {rec['source']!r}")
    if rec["severity"] not in SEVERITIES:
        raise ValueError(f"{where}: severity must be in {SEVERITIES}; got {rec['severity']!r}")
    if rec["disposition"] not in DISPOSITIONS:
        raise ValueError(f"{where}: disposition must be in {DISPOSITIONS}; got {rec['disposition']!r}")
    if not isinstance(rec["body"], str) or not rec["body"].strip():
        raise ValueError(f"{where}: body must be a non-empty string")
    if not isinstance(rec["affected_path"], str) or not rec["affected_path"].strip():
        raise ValueError(f"{where}: affected_path must be a non-empty string")
    if not isinstance(rec["out_of_scope"], bool):
        raise ValueError(f"{where}: out_of_scope must be bool")
    if rec["disposition"] in REQUIRES_RATIONALE:
        rationale = rec.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(
                f"{where}: disposition={rec['disposition']!r} requires non-empty rationale"
            )


def _next_id(existing: list[dict]) -> int:
    max_n = 0
    for rec in existing:
        m = ID_RE.match(str(rec.get("id", "")))
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1


def _path_in_allowed(target: str, allowed: list[str]) -> bool:
    if not allowed:
        return False
    for pat in allowed:
        if pat.endswith("/**"):
            base = pat[:-3].rstrip("/")
            if target == base or target.startswith(base + "/"):
                return True
            continue
        if "**" in pat:
            regex = "^" + re.escape(pat).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
            if re.match(regex, target):
                return True
            continue
        if fnmatch.fnmatch(target, pat):
            return True
    return False


def cmd_add(args: argparse.Namespace) -> int:
    if args.source not in SOURCES:
        sys.stderr.write(f"--source must be in {SOURCES}; got {args.source!r}\n")
        return 2
    allowed: list[str] = []
    if args.allowed_files_json:
        try:
            allowed = json.loads(args.allowed_files_json)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"--allowed-files-json invalid: {exc}\n")
            return 2
        if not isinstance(allowed, list):
            sys.stderr.write("--allowed-files-json must decode to a list\n")
            return 2
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"stdin not valid JSON: {exc}\n")
        return 2
    if not isinstance(raw, list):
        sys.stderr.write("stdin must be a JSON array of {severity, body, affected_path}\n")
        return 2
    if not raw:
        sys.stderr.write("stdin array empty; nothing to add\n")
        return 2
    repo_root = _resolve_repo_root()
    path = _findings_path(repo_root, args.issue_id)
    # `add` is the SAME read-modify-rewrite, so it needs the same lock or the
    # chokepoint is only half a chokepoint: `add` racing `set-disposition` loses
    # a record just as readily as two dispositions racing each other. It also
    # derives finding ids from what it read (`_next_id`), so an unlocked add
    # racing another add mints the SAME id twice.
    with _findings_lock(path):
        return _add_locked(args, allowed, raw, path)


def _add_locked(args: argparse.Namespace, allowed: list, raw: list, path: Path) -> int:
    try:
        existing = _load(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    next_num = _next_id(existing)
    new_records: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            sys.stderr.write(f"input #{i}: must be an object\n")
            return 2
        unknown = set(item) - {"severity", "body", "affected_path"}
        if unknown:
            sys.stderr.write(
                f"input #{i}: unexpected keys {sorted(unknown)}; "
                "writer input must be exactly {severity, body, affected_path}\n"
            )
            return 2
        severity = item.get("severity")
        body = item.get("body")
        affected = item.get("affected_path")
        if severity not in SEVERITIES:
            sys.stderr.write(f"input #{i}: severity must be in {SEVERITIES}; got {severity!r}\n")
            return 2
        if not isinstance(body, str) or not body.strip():
            sys.stderr.write(f"input #{i}: body must be non-empty string\n")
            return 2
        if not isinstance(affected, str) or not affected.strip():
            sys.stderr.write(f"input #{i}: affected_path must be non-empty string\n")
            return 2
        out_of_scope = bool(allowed) and not _path_in_allowed(affected.strip(), allowed)
        rec = {
            "id": f"finding-{next_num}",
            "issue_id": args.issue_id,
            "source": args.source,
            "severity": severity,
            "disposition": "pending",
            "body": body.strip(),
            "affected_path": affected.strip(),
            "out_of_scope": out_of_scope,
            "created_at": _now_iso(),
        }
        try:
            _validate(rec, f"input #{i}")
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        new_records.append(rec)
        next_num += 1
    _write_all(path, existing + new_records)
    print(json.dumps({
        "added": len(new_records),
        "ids": [r["id"] for r in new_records],
        "out_of_scope_count": sum(1 for r in new_records if r["out_of_scope"]),
    }))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root()
    path = _findings_path(repo_root, args.issue_id)
    try:
        records = _load(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if args.only_pending:
        records = [r for r in records if r.get("disposition") == "pending"]
    if args.only_in_scope:
        records = [r for r in records if not r.get("out_of_scope", False)]
    print(json.dumps(records, indent=2, sort_keys=True))
    return 0


def cmd_set_disposition(args: argparse.Namespace) -> int:
    if args.disposition not in DISPOSITIONS:
        sys.stderr.write(f"disposition must be in {DISPOSITIONS}\n")
        return 2
    if args.disposition in REQUIRES_RATIONALE and not (args.rationale and args.rationale.strip()):
        sys.stderr.write(f"disposition={args.disposition!r} requires --rationale\n")
        return 2
    repo_root = _resolve_repo_root()
    path = _findings_path(repo_root, args.issue_id)
    # The lock spans the READ, the REWRITE and the fan-out. A lock around the
    # write alone still lets a stale in-memory copy be formed first, which is
    # the same reasoning prd_runner._spillover_lock records for reclassify.
    with _findings_lock(path):
        return _set_disposition_locked(args, repo_root, path)


def _set_disposition_locked(args: argparse.Namespace, repo_root: Path, path: Path) -> int:
    try:
        records = _load(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    found = False
    target_record: dict = {}
    for rec in records:
        if rec.get("id") == args.finding_id:
            found = True
            target_record = rec
            old = rec.get("disposition")
            rec["disposition"] = args.disposition
            if args.disposition in REQUIRES_RATIONALE:
                rec["rationale"] = args.rationale.strip()
            elif args.disposition == "accepted":
                rec.pop("rationale", None)
            if args.followup_issue_id:
                rec["followup_issue_id"] = args.followup_issue_id.strip()
            if args.disposition == "pending":
                rec.pop("resolved_at", None)
            elif old == "pending" or "resolved_at" not in rec:
                rec["resolved_at"] = _now_iso()
            try:
                _validate(rec, f"finding {args.finding_id}")
            except ValueError as exc:
                sys.stderr.write(f"{exc}\n")
                return 2
            break
    if not found:
        sys.stderr.write(f"finding {args.finding_id!r} not found in {path}\n")
        return 2
    pre_findings_bytes = path.read_bytes() if path.is_file() else None
    _write_all(path, records)
    # DEFERRING IS NOT A TERMINAL STATE (sp-5bcfbfe8). Mirrors
    # prd-os findings_writer._sync_spillover_for_finding, which has done this
    # for PRD findings all along. This side had no equivalent, so a deferred
    # ISSUE finding was a rationale and then nothing -- exactly the silent drop
    # no-orphan-findings.md forbids.
    #
    # Measured 2026-08-06 while closing scs-validated-event-fold: three findings
    # deferred, then the ledger folded for that issue's ids -> []. Two of the
    # three happened to have been captured by hand beforehand; the third had
    # nothing and would have vanished behind a rationale nobody re-reads.
    #
    # The rule text said this backstop was automatic and named findings_writer,
    # so it was TRUE and still misleading -- a correct statement about one of
    # two systems, read as a guarantee about both. Fixed here rather than by
    # qualifying the sentence: a rule that must be read carefully to avoid a
    # wrong conclusion will produce wrong conclusions.
    try:
        _sync_spillover_for_finding(repo_root, args.issue_id, target_record)
    except Exception as exc:  # noqa: BLE001
        # BROADER than findings_writer's `except SpilloverLedgerError`, on
        # purpose. That one lets an ImportError escape as a traceback exiting 1
        # with NO rollback -- and ImportError is the live failure mode here,
        # because this fan-out reaches into a SIBLING PLUGIN's scripts by
        # sys.path. The `parents[1]` bug was exactly that. Every reachable
        # failure has the same correct response: un-commit and refuse.
        rolled_back = _rollback_findings(path, pre_findings_bytes)
        # REMEDIATION DEPENDS ON WHAT FAILED. A fixed "fix the ledger" line sent
        # the operator to a healthy file whenever the exception came from THIS
        # code (an ImportError from the sys.path reach into prd-os, a NameError),
        # and the traceback was swallowed, so the message was unactionable in
        # exactly the cases that need it most. Adversarial review, ASK-429.
        ledger_problem = type(exc).__name__ == "SpilloverLedgerError"
        sys.stderr.write(
            f"spillover fan-out FAILED for {args.finding_id} "
            f"[{type(exc).__name__}]: {exc}\n"
            + ("disposition rolled back; findings file unchanged.\n"
               if rolled_back else
               "WARNING: rollback ALSO failed. The finding may now read "
               f"{args.disposition!r} with no spillover item tracking it.\n")
            + ("Fix the ledger, then re-run this command.\n" if ledger_problem else
               "This is NOT a ledger-content problem: it came from the fan-out "
               "itself (import path, config, or a defect here). Traceback "
               "below.\n"))
        if not ledger_problem:
            traceback.print_exc()
        return 2
    print(json.dumps({"set": args.finding_id, "disposition": args.disposition}))
    return 0


def _sync_spillover_for_finding(repo_root: Path, issue_id: str, finding: dict) -> None:
    """Open a spillover item while a finding is deferred; close it once decided.

    RAISES ON FAILURE, and the caller rolls the findings file back.

    This used to catch `Exception`, print a WARNING and fall through, so
    `set-disposition ... deferred` against an unreadable ledger printed
    `{"set": "finding-1", "disposition": "deferred"}` and exited 0 -- a silent
    drop wearing a success record, which is the precise failure this fan-out
    exists to prevent. Nothing downstream reads stderr for a passing command.

    THE OLD DOCSTRING CITED findings_writer AS PRECEDENT FOR THAT, AND HAD IT
    BACKWARDS. `findings_writer.cmd_set_disposition` catches
    SpilloverLedgerError, restores the findings file to its pre-write bytes via
    `_rollback_findings`, and returns 2. It does not swallow. A wrong citation of
    a real function is worse than no citation: it reads as "this was considered",
    so the next reader checks the reasoning instead of the code.
    """
    # parents[2] is plugins/ : [0]=scripts, [1]=kipi-dsse, [2]=plugins.
    # parents[1] silently yielded "No module named 'config'". Under the old
    # broad except that was a WARNING and a green command; now it is exit 2,
    # which is what a disabled backstop should look like.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prd-os" / "scripts"))
    from config import load as load_config
    from prd_runner import _read_spillover, _spillover_append, _spillover_lock

    cfg = load_config(repo_root, strict=True)
    sid = f"defer-{issue_id}-{finding['id']}"
    disposition = finding.get("disposition")
    # READ AND APPEND UNDER ONE LOCK -- the same chokepoint prd_runner's
    # `resolve` and `reclassify` take, skipped here.
    #
    # "Under one lock" is CONDITIONAL, and the condition is real: taking the
    # lock has to CREATE a file, so it needs write permission on the DIRECTORY
    # while appending needs it only on the FILE. `_spillover_lock` therefore
    # DEGRADES to unlocked (loudly, on stderr) on a read-only `.prd-os`, which
    # prd_runner documents as a live environment here. In that case the race
    # below is back and the command still exits 0. Stated rather than implied,
    # because the unqualified version of this sentence was wrong.
    #
    # The idempotency check below is a read-then-append, so across PROCESSES
    # every concurrent caller read "no such item" and every one of them
    # appended. Measured on this fixture before the lock: 4 concurrent deferrals
    # of ONE finding produced 4 open rows, every trial. The existing idempotency
    # test only ever ran single-threaded, and re-deferral from a RETRYING AGENT
    # is exactly the concurrent case it was standing in for.
    #
    # Duplicates are not a correctness bug (the fold is last-write-wins). They
    # are unbounded growth in a ledger whose entire problem is that it grows,
    # and each duplicate needs its own resolve to leave.
    with _spillover_lock(cfg):
        existing = _read_spillover(cfg).get(sid)
        if disposition == "deferred":
            if existing and existing.get("status") == "open":
                return  # idempotent: re-deferring must not append a duplicate
            _spillover_append(cfg, {
                "id": sid, "source": issue_id, "finding_id": finding["id"],
                # WHOLE body, never a prefix (sp-9f11cf69): a 120-char cap on
                # the PRD side made every defer-* row end mid-sentence, and
                # nobody can triage what they cannot read.
                "description": f"deferred issue finding {finding['id']}: {finding.get('body', '')}",
                # Severity carries over TRANSLATED, or a major defect lands in
                # the gate's non-blocking bucket and a `nit` turns it red.
                "severity": LEDGER_SEVERITY.get(
                    finding.get("severity", "minor"), finding.get("severity", "minor")),
                "status": "open", "created_at": _now_iso(),
            })
        # `pending` is NOT here, and its absence is the fix. This branch used to
        # be a bare `elif existing...`, so it fired for every non-deferred value
        # -- including `pending`, the one disposition that needs no --rationale.
        # `set-disposition <iss> <finding> pending` was therefore a one-command,
        # unexplained THIRD way out of the ledger, which is exactly what
        # no-orphan-findings.md (the file this change edits) says does not exist.
        #
        # Undeciding is not resolving. Sharpest for an out-of-scope finding:
        # `count --in-scope-pending` skips it, so afterwards the finding blocked
        # nothing and the ledger held nothing.
        elif disposition in DECIDED_DISPOSITIONS and existing and existing.get("status") == "open":
            resolved = dict(existing)
            resolved.update(
                status="resolved",
                void_reason=f"finding re-dispositioned to {disposition}",
                resolved_at=_now_iso())
            _spillover_append(cfg, resolved)


def _rollback_findings(path: Path, pre_bytes: bytes | None) -> bool:
    """Restore the findings file to its pre-write bytes. Returns success.

    Same shape as findings_writer._rollback_findings, for the same reason: the
    fan-out runs after the disposition is committed, so a failure there has to
    un-commit it or the record claims a backstop that does not exist.
    """
    try:
        if pre_bytes is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(pre_bytes)
        return True
    except OSError:
        return False


def cmd_count(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root()
    path = _findings_path(repo_root, args.issue_id)
    try:
        records = _load(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if args.in_scope_pending:
        n = sum(
            1 for r in records
            if r.get("disposition") == "pending" and not r.get("out_of_scope", False)
        )
        print(n)
        return 0
    counts: dict[str, int] = {d: 0 for d in DISPOSITIONS}
    in_scope = 0
    out_scope = 0
    for r in records:
        d = r.get("disposition")
        if d in counts:
            counts[d] += 1
        if r.get("out_of_scope"):
            out_scope += 1
        else:
            in_scope += 1
    print(json.dumps({
        "total": len(records),
        "by_disposition": counts,
        "in_scope": in_scope,
        "out_of_scope": out_scope,
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("issue_id")
    p_add.add_argument("--source", required=True)
    p_add.add_argument("--allowed-files-json", default="")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list")
    p_list.add_argument("issue_id")
    p_list.add_argument("--only-pending", action="store_true")
    p_list.add_argument("--only-in-scope", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set-disposition")
    p_set.add_argument("issue_id")
    p_set.add_argument("finding_id")
    p_set.add_argument("disposition")
    p_set.add_argument("--rationale", default="")
    p_set.add_argument("--followup-issue-id", default="")
    p_set.set_defaults(func=cmd_set_disposition)

    p_count = sub.add_parser("count")
    p_count.add_argument("issue_id")
    p_count.add_argument("--in-scope-pending", action="store_true")
    p_count.set_defaults(func=cmd_count)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
