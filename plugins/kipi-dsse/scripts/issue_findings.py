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
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

CONFIG_RELPATH = ".prd-os/config.json"
DEFAULT_ISSUES_DIR = "issues"
DEFAULT_FINDINGS_SUBDIR = "findings"

SEVERITIES = ("blocker", "major", "minor", "nit")
SOURCES = ("codex-review", "codex-adversarial", "manual")
DISPOSITIONS = ("pending", "accepted", "rejected", "deferred")
REQUIRES_RATIONALE = ("rejected", "deferred")
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
    try:
        records = _load(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    found = False
    for rec in records:
        if rec.get("id") == args.finding_id:
            found = True
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
    _write_all(path, records)
    print(json.dumps({"set": args.finding_id, "disposition": args.disposition}))
    return 0


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
