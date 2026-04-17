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

    if target == "approved":
        rc, err = _findings_gate(cfg, state)
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
    spec_path = cfg.repo_root / state["spec_path"]
    text = spec_path.read_text()
    new_text = re.sub(r"(?m)^status:\s*.+$", "status: archived", text, count=1)
    new_text = re.sub(
        r"(?m)^updated_at:\s*.+$", f"updated_at: {_now_iso()}", new_text, count=1
    )
    spec_path.write_text(new_text)
    archived_id = state["prd_id"]
    _write_state(cfg, _empty_state())
    print(json.dumps({"archived": archived_id}))
    return 0


def cmd_clear(cfg: Config, args: argparse.Namespace) -> int:
    _write_state(cfg, _empty_state())
    print("cleared")
    return 0


# ---------------------------------------------------------------------------
# Findings gate
# ---------------------------------------------------------------------------


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
# Entry
# ---------------------------------------------------------------------------


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
