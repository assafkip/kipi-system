#!/usr/bin/env python3
"""Portable DSSE issue-runner for the prd-os plugin.

Loads issue specs, enforces scope, records receipts, gates stop.
Path resolution is config-driven (see `config.py`) so the same runner works
against any repo layout as long as `.prd-os/config.json` names the issues
directory and state directory.

Subcommands:
  load <issue-id>          Load spec, write active-issue state, print JSON summary
  status                   Print active issue + receipt state
  scope <path>             Exit 0 if path is in allowed_files (or carve-out), exit 2 otherwise
  gate                     Exit 0 if stop is allowed, exit 2 if gate blocks
  mark <receipt>           Set a receipt timestamp (verified|reviewed|findings_triaged)
  approve                  Flip spec status open -> in-progress; reset stale receipts
  close                    Verify all receipts; flip status=closed; clear active state
  clear                    Clear active state (for abandoned work)

Invocation:
  python3 plugins/prd-os/scripts/issue_runner.py <subcommand> [...]

The contract mirrors the pre-plugin runner at
q-ktlyst/.q-system/scripts/issue-runner.py. Exit codes, stderr messages, and
stdout JSON are preserved so existing commands and hooks see the same
behavior during the parallel-install period.
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

# Make sibling `config.py` importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ConfigError, load as load_config  # noqa: E402
from concurrency import ConcurrencyError, assert_no_active_prd  # noqa: E402


RECEIPT_FIELDS = ("verified", "reviewed", "findings_triaged")


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


def _load_spec(cfg: Config, issue_id: str) -> tuple[Path, dict, str]:
    candidates = [
        cfg.issues_dir / f"{issue_id}.md",
        cfg.issues_dir / issue_id,
    ]
    for path in candidates:
        if path.is_file():
            text = path.read_text()
            return path, _parse_frontmatter(text), text
    raise FileNotFoundError(
        f"issue spec not found for id={issue_id!r} under {cfg.issues_dir}"
    )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _empty_state() -> dict:
    return {
        "issue_id": None,
        "loaded_at": None,
        "spec_path": None,
        "receipts": {k: None for k in RECEIPT_FIELDS},
    }


def _read_state(cfg: Config) -> dict:
    path = cfg.active_issue_state_path
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return _empty_state()


def _write_state(cfg: Config, state: dict) -> None:
    path = cfg.active_issue_state_path
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


def cmd_load(cfg: Config, args: argparse.Namespace) -> int:
    try:
        assert_no_active_prd(
            cfg.active_prd_state_path, action=f"load issue {args.issue_id!r}"
        )
    except ConcurrencyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    path, fm, _ = _load_spec(cfg, args.issue_id)
    state = {
        "issue_id": fm.get("id", args.issue_id),
        "loaded_at": _now_iso(),
        "spec_path": _relpath(cfg, path),
        "receipts": {k: None for k in RECEIPT_FIELDS},
    }
    _write_state(cfg, state)
    print(
        json.dumps(
            {
                "loaded": state["issue_id"],
                "spec_path": state["spec_path"],
                "title": fm.get("title", ""),
                "priority": fm.get("priority", ""),
                "allowed_files": fm.get("allowed_files", []),
                "required_checks": fm.get("required_checks", []),
                "required_reviews": fm.get("required_reviews", []),
            },
            indent=2,
        )
    )
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    print(json.dumps(_read_state(cfg), indent=2))
    return 0


def _workflow_control_plane_paths(cfg: Config, state: dict) -> set[str]:
    """Paths Claude may edit even when allowed_files is empty or non-matching.

    Always includes the active spec file (widening scope mid-issue requires
    editing it) plus any repo-specified control_plane_files from config.

    The active-issue state file is intentionally NOT here: it holds issue_id
    and receipt timestamps that drive both the scope hook and the stop-gate.
    Letting Claude Edit it would allow synthetic receipts or silent
    deactivation, i.e. a full gate bypass. The runner writes state via
    write_text from Python, which never passes through the Edit/Write tool
    scope check, so the runner's own path stays intact without being listed
    here.
    """
    paths: set[str] = set()
    spec = state.get("spec_path")
    if spec:
        paths.add(_normalize_str(spec))
    for p in cfg.control_plane_files:
        paths.add(_normalize_str(p))
    return paths


def cmd_scope(cfg: Config, args: argparse.Namespace) -> int:
    state = _read_state(cfg)
    issue_id = state.get("issue_id")
    if not issue_id:
        return 0
    target_rel = _normalize_path(cfg, args.path)
    if target_rel in _workflow_control_plane_paths(cfg, state):
        return 0
    try:
        _, fm, _ = _load_spec(cfg, issue_id)
    except FileNotFoundError as exc:
        sys.stderr.write(f"DSSE scope error: {exc}\n")
        return 2
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


def cmd_gate(cfg: Config, args: argparse.Namespace) -> int:
    if os.environ.get("ISSUE_GATE_OFF") == "1":
        return 0
    state = _read_state(cfg)
    issue_id = state.get("issue_id")
    if not issue_id:
        return 0
    try:
        _, fm, _ = _load_spec(cfg, issue_id)
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
    return 0


def cmd_mark(cfg: Config, args: argparse.Namespace) -> int:
    if args.receipt not in RECEIPT_FIELDS:
        sys.stderr.write(f"unknown receipt: {args.receipt}\n")
        return 2
    state = _read_state(cfg)
    if not state.get("issue_id"):
        sys.stderr.write("no active issue\n")
        return 2
    state["receipts"][args.receipt] = _now_iso()
    _write_state(cfg, state)
    print(
        json.dumps(
            {"marked": args.receipt, "at": state["receipts"][args.receipt]}
        )
    )
    return 0


def cmd_approve(cfg: Config, args: argparse.Namespace) -> int:
    state = _read_state(cfg)
    issue_id = state.get("issue_id")
    if not issue_id:
        sys.stderr.write("no active issue\n")
        return 2
    path, fm, text = _load_spec(cfg, issue_id)
    current = (fm.get("status") or "").strip()
    if current == "in-progress":
        print(
            json.dumps(
                {"approved": issue_id, "status": "in-progress", "note": "already"}
            )
        )
        return 0
    if current != "open":
        sys.stderr.write(
            f"cannot approve {issue_id}: status is {current!r}, expected 'open'\n"
        )
        return 2
    new_text = re.sub(r"(?m)^status:\s*.+$", "status: in-progress", text, count=1)
    path.write_text(new_text)
    state["receipts"] = {k: None for k in RECEIPT_FIELDS}
    _write_state(cfg, state)
    print(json.dumps({"approved": issue_id, "status": "in-progress"}))
    return 0


def cmd_close(cfg: Config, args: argparse.Namespace) -> int:
    state = _read_state(cfg)
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
    path, fm, text = _load_spec(cfg, issue_id)
    new_text = re.sub(r"(?m)^status:\s*.+$", "status: closed", text, count=1)
    path.write_text(new_text)
    _write_state(cfg, _empty_state())
    print(json.dumps({"closed": issue_id, "spec": _relpath(cfg, path)}))
    return 0


def cmd_clear(cfg: Config, args: argparse.Namespace) -> int:
    _write_state(cfg, _empty_state())
    print("cleared")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_str(target: str) -> str:
    # Normalize a pre-relative string as stored in state/config. No resolution.
    return str(Path(target))


def _normalize_path(cfg: Config, target: str) -> str:
    p = Path(target)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(cfg.repo_root))
        except ValueError:
            return str(p)
    return str(p)


def _match(pattern: str, path: str) -> bool:
    if pattern.endswith("/**"):
        return path == pattern[:-3].rstrip("/") or fnmatch.fnmatch(
            path, pattern + "/*"
        )
    if "**" in pattern:
        regex = (
            "^"
            + re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            + "$"
        )
        return re.match(regex, path) is not None
    return fnmatch.fnmatch(path, pattern)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        help="override repo root (default: CLAUDE_PROJECT_DIR or walk-up discovery)",
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

    sub.add_parser("approve").set_defaults(func=cmd_approve)
    sub.add_parser("close").set_defaults(func=cmd_close)
    sub.add_parser("clear").set_defaults(func=cmd_clear)

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
