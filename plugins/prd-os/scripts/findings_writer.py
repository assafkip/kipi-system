#!/usr/bin/env python3
"""Deterministic findings writer for the prd-os plugin.

Single point where findings records are validated, ID-assigned, timestamped,
and appended to `<findings_dir>/<prd-id>-findings.jsonl`. Claude Code
slash commands (`/prd-review`, `/prd-triage`) delegate to this script.

Why this lives in Python (not in a command prompt):
  - Raw Codex output is free-form. The schema contract in
    `schemas/findings.schema.json` cannot be guaranteed by asking an LLM
    to follow it. Claude must translate Codex's output into the writer's
    narrow input shape (`{severity, body}`). The writer re-validates on
    every call and rejects anything that drifts.
  - IDs must be monotonic across invocations. Only deterministic code can
    guarantee that.
  - Disposition changes must enforce the rationale rule (rejected/deferred
    require explanation) and set `resolved_at` atomically with the
    disposition field. LLM-mediated edits cannot hold that invariant.

Subcommands:

  add <prd-id> --source <codex-review|codex-adversarial|manual>
      Reads a JSON array on stdin. Each item must be an object with
      {severity, body}. Appends one validated JSONL record per item.
      IDs increment from the current max id in the file (finding-1,
      finding-2, ...). When source is `codex-review` or `codex-adversarial`
      the PRD frontmatter is stamped with `codex_reviewed_at` as a side
      effect — the approval gate requires that stamp before advancing.

  record-review <prd-id> --source <codex-review|codex-adversarial>
      Stamp the PRD frontmatter `codex_reviewed_at` without writing any
      findings. Use this when a Codex pass returned zero findings; the
      stamp is still needed for approval.

  list <prd-id> [--only-pending]
      Prints the findings file as a JSON array on stdout. Exits 2 on any
      invalid line so triage never operates on a corrupted stream.

  set-disposition <prd-id> <finding-id> <disposition> [--rationale <text>]
      Rewrites the file with one record updated. `rejected` and `deferred`
      require --rationale (schema rule). Sets `resolved_at` when leaving
      `pending`; clears it when returning to `pending`.

Exit codes:
  0  success
  2  validation error, schema violation, missing record, or file problem
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ConfigError, load as load_config  # noqa: E402


SEVERITIES = ("blocker", "major", "minor", "nit")
SOURCES = ("codex-review", "codex-adversarial", "manual")
CODEX_SOURCES = ("codex-review", "codex-adversarial")
DISPOSITIONS = ("pending", "accepted", "rejected", "deferred")
REQUIRES_RATIONALE = ("rejected", "deferred")
ID_RE = re.compile(r"^finding-([0-9]+)$")
REVIEWED_AT_RE = re.compile(r"(?m)^codex_reviewed_at:\s*.*$")
RECORD_FIELDS = (
    "id",
    "prd_id",
    "source",
    "severity",
    "disposition",
    "body",
    "created_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _findings_path(cfg: Config, prd_id: str) -> Path:
    return cfg.findings_dir / f"{prd_id}-findings.jsonl"


def _prd_spec_path(cfg: Config, prd_id: str) -> Path:
    return cfg.prds_dir / f"{prd_id}.md"


def _compute_stamped_spec(text: str, timestamp: str) -> str:
    """Return new PRD spec text with `codex_reviewed_at` set to `timestamp`.

    Pure function. Raises ValueError for malformed frontmatter so callers
    can pre-validate before touching any other file. Keeping this stateless
    is how `cmd_add` stays atomic: it can decide whether the stamp will
    succeed before writing findings to disk.
    """
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("frontmatter not closed with ---")
    header = text[: end + 1]
    rest = text[end + 1 :]
    stamp_line = f"codex_reviewed_at: {timestamp}"
    if REVIEWED_AT_RE.search(header):
        header = REVIEWED_AT_RE.sub(stamp_line, header, count=1)
    else:
        header = header.rstrip("\n") + "\n" + stamp_line + "\n"
    return header + rest


def _stamp_prd_reviewed(cfg: Config, prd_id: str, source: str) -> None:
    """Record `codex_reviewed_at` on the PRD's frontmatter.

    Thin wrapper for the record-review path, where atomicity is trivial
    (only one file touched). `cmd_add` does NOT use this helper — it
    interleaves findings and stamp writes with rollback, using
    `_compute_stamped_spec` directly.
    """
    spec_path = _prd_spec_path(cfg, prd_id)
    if not spec_path.is_file():
        raise FileNotFoundError(f"PRD spec not found: {spec_path}")
    try:
        new_text = _compute_stamped_spec(spec_path.read_text(), _now_iso())
    except ValueError as exc:
        raise ValueError(f"{spec_path}: {exc}") from exc
    spec_path.write_text(new_text)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def _load_findings(path: Path) -> list[dict]:
    """Parse existing JSONL. Missing file -> []. Invalid line -> ValueError."""
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
                raise ValueError(f"{path}:{lineno}: record must be a JSON object")
            out.append(rec)
    return out


def _write_all(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_record(rec: dict, where: str) -> None:
    for field in RECORD_FIELDS:
        if field not in rec:
            raise ValueError(f"{where}: missing required field {field!r}")
    if not isinstance(rec["id"], str) or not ID_RE.match(rec["id"]):
        raise ValueError(
            f"{where}: id must match finding-N pattern; got {rec['id']!r}"
        )
    if rec["source"] not in SOURCES:
        raise ValueError(
            f"{where}: source must be one of {SOURCES}; got {rec['source']!r}"
        )
    if rec["severity"] not in SEVERITIES:
        raise ValueError(
            f"{where}: severity must be one of {SEVERITIES}; got {rec['severity']!r}"
        )
    if rec["disposition"] not in DISPOSITIONS:
        raise ValueError(
            f"{where}: disposition must be one of {DISPOSITIONS}; got {rec['disposition']!r}"
        )
    if not isinstance(rec["body"], str) or not rec["body"].strip():
        raise ValueError(f"{where}: body must be a non-empty string")
    if rec["disposition"] in REQUIRES_RATIONALE:
        rationale = rec.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(
                f"{where}: disposition={rec['disposition']!r} requires a "
                "non-empty rationale"
            )


def _next_id_number(existing: list[dict]) -> int:
    max_n = 0
    for rec in existing:
        m = ID_RE.match(str(rec.get("id", "")))
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_add(cfg: Config, args: argparse.Namespace) -> int:
    if args.source not in SOURCES:
        sys.stderr.write(f"--source must be one of {SOURCES}; got {args.source!r}\n")
        return 2
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"stdin is not valid JSON: {exc}\n")
        return 2
    if not isinstance(raw, list):
        sys.stderr.write(
            "stdin must be a JSON array of {severity, body} objects\n"
        )
        return 2
    if not raw:
        sys.stderr.write("stdin array is empty; nothing to add\n")
        return 2
    path = _findings_path(cfg, args.prd_id)
    try:
        existing = _load_findings(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    next_num = _next_id_number(existing)
    new_records: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            sys.stderr.write(f"input #{i}: must be a JSON object\n")
            return 2
        severity = item.get("severity")
        body = item.get("body")
        # Only accept the narrow input shape. Reject unknown keys so drifted
        # Codex output that happens to parse as JSON can't sneak fields in.
        unknown = set(item) - {"severity", "body"}
        if unknown:
            sys.stderr.write(
                f"input #{i}: unexpected keys {sorted(unknown)}; "
                "writer input must be exactly {severity, body}\n"
            )
            return 2
        if severity not in SEVERITIES:
            sys.stderr.write(
                f"input #{i}: severity must be one of {SEVERITIES}; got {severity!r}\n"
            )
            return 2
        if not isinstance(body, str) or not body.strip():
            sys.stderr.write(f"input #{i}: body must be a non-empty string\n")
            return 2
        rec = {
            "id": f"finding-{next_num}",
            "prd_id": args.prd_id,
            "source": args.source,
            "severity": severity,
            "disposition": "pending",
            "body": body.strip(),
            "created_at": _now_iso(),
        }
        try:
            _validate_record(rec, f"input #{i}")
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        new_records.append(rec)
        next_num += 1
    # Pre-validate the stamp path BEFORE writing findings. Computing the new
    # spec content is pure — if the spec is missing or the frontmatter is
    # malformed we refuse before any file changes. This is what keeps the
    # operation atomic: no scenario produces findings without the stamp.
    new_spec_text: str | None = None
    spec_path: Path | None = None
    if args.source in CODEX_SOURCES:
        spec_path = _prd_spec_path(cfg, args.prd_id)
        if not spec_path.is_file():
            sys.stderr.write(
                f"PRD spec not found: {spec_path}. Codex-sourced findings "
                "must have a PRD to stamp; refusing before any write.\n"
            )
            return 2
        try:
            new_spec_text = _compute_stamped_spec(spec_path.read_text(), _now_iso())
        except ValueError as exc:
            sys.stderr.write(f"{spec_path}: {exc}\n")
            return 2

    # Snapshot findings pre-state so we can roll back if the stamp write
    # fails AFTER the findings write succeeds (disk full mid-write, perms
    # changed between read and write, etc).
    pre_findings_bytes: bytes | None = path.read_bytes() if path.is_file() else None
    try:
        _write_all(path, existing + new_records)
    except OSError as exc:
        sys.stderr.write(f"failed to write findings: {exc}\n")
        return 2

    stamped = False
    if new_spec_text is not None and spec_path is not None:
        try:
            spec_path.write_text(new_spec_text)
            stamped = True
        except OSError as exc:
            # Roll the findings file back to pre-state so the caller never
            # sees orphaned records without a stamp.
            try:
                if pre_findings_bytes is None:
                    path.unlink()
                else:
                    path.write_bytes(pre_findings_bytes)
            except OSError as rollback_exc:
                sys.stderr.write(
                    f"stamp write failed ({exc}) and rollback ALSO failed "
                    f"({rollback_exc}). Findings file may be in a partial "
                    "state; inspect manually before re-running.\n"
                )
                return 2
            sys.stderr.write(
                f"stamp write failed, findings rolled back: {exc}\n"
            )
            return 2

    print(
        json.dumps(
            {
                "prd_id": args.prd_id,
                "added": [r["id"] for r in new_records],
                "path": str(path),
                "codex_reviewed_stamped": stamped,
            },
            indent=2,
        )
    )
    return 0


def cmd_record_review(cfg: Config, args: argparse.Namespace) -> int:
    """Stamp the PRD frontmatter `codex_reviewed_at` without writing findings.

    Used by /prd-review when Codex runs clean (no findings). Otherwise `add`
    with a codex source stamps automatically as a side-effect. The approval
    gate in prd_runner requires this stamp before advancing to `approved`.
    """
    if args.source not in CODEX_SOURCES:
        sys.stderr.write(
            f"--source must be one of {CODEX_SOURCES}; got {args.source!r}. "
            "record-review is for documenting a real Codex pass only.\n"
        )
        return 2
    try:
        _stamp_prd_reviewed(cfg, args.prd_id, args.source)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    print(
        json.dumps(
            {
                "prd_id": args.prd_id,
                "codex_reviewed_stamped": True,
                "source": args.source,
            },
            indent=2,
        )
    )
    return 0


def cmd_list(cfg: Config, args: argparse.Namespace) -> int:
    path = _findings_path(cfg, args.prd_id)
    try:
        recs = _load_findings(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if args.only_pending:
        recs = [r for r in recs if r.get("disposition") == "pending"]
    print(json.dumps(recs, indent=2))
    return 0


def cmd_set_disposition(cfg: Config, args: argparse.Namespace) -> int:
    if args.disposition not in DISPOSITIONS:
        sys.stderr.write(
            f"disposition must be one of {DISPOSITIONS}; got {args.disposition!r}\n"
        )
        return 2
    if args.disposition in REQUIRES_RATIONALE and not (args.rationale or "").strip():
        sys.stderr.write(
            f"disposition={args.disposition!r} requires --rationale\n"
        )
        return 2
    path = _findings_path(cfg, args.prd_id)
    try:
        recs = _load_findings(path)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    target = None
    for rec in recs:
        if rec.get("id") == args.finding_id:
            target = rec
            break
    if target is None:
        sys.stderr.write(f"finding not found: {args.finding_id}\n")
        return 2
    target["disposition"] = args.disposition
    if args.rationale and args.rationale.strip():
        target["rationale"] = args.rationale.strip()
    elif args.disposition == "pending":
        target.pop("rationale", None)
    if args.disposition == "pending":
        target.pop("resolved_at", None)
    else:
        target["resolved_at"] = _now_iso()
    try:
        _validate_record(target, f"{path}:{args.finding_id}")
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    _write_all(path, recs)
    print(
        json.dumps(
            {
                "prd_id": args.prd_id,
                "updated": args.finding_id,
                "disposition": args.disposition,
            },
            indent=2,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="override repo root discovery")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("prd_id")
    p_add.add_argument("--source", required=True)
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list")
    p_list.add_argument("prd_id")
    p_list.add_argument("--only-pending", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set-disposition")
    p_set.add_argument("prd_id")
    p_set.add_argument("finding_id")
    p_set.add_argument("disposition")
    p_set.add_argument("--rationale", default="")
    p_set.set_defaults(func=cmd_set_disposition)

    p_rec = sub.add_parser("record-review")
    p_rec.add_argument("prd_id")
    p_rec.add_argument("--source", required=True)
    p_rec.set_defaults(func=cmd_record_review)

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
