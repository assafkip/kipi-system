#!/usr/bin/env python3
"""Deterministic PRD -> issue-spec decomposition for the prd-os plugin.

Reads an approved PRD, locates the fenced JSON block under the `## Issues`
heading, and writes one issue spec per entry using `templates/issue.md`.

Design constraints:
  - No LLM. The PRD author (or a reviewed Codex pass) writes the JSON manifest
    inside the PRD; this script only materializes it.
  - PRD status MUST be `approved`. Any other status is rejected with exit 2.
  - Refuses to clobber existing issue files. A rerun is idempotent only when
    every entry already exists with byte-identical content; otherwise the
    rerun stops and reports the collision.
  - Required keys per manifest entry: id, title, allowed_files (non-empty
    list), required_checks (non-empty list). Optional: priority (default
    `p1`), disallowed_files, required_reviews, acceptance.
  - `required_checks` is enforced here — not in the issue runner — because
    the runner's stop-gate only checks three receipt timestamps (verified,
    reviewed, findings_triaged). Those receipts are meaningless unless the
    spec documents what must be verified. Allowing an empty (or missing)
    `required_checks` list lets an issue be "verified" against nothing,
    which silently bypasses the verification gate. Catching it here stops
    empty-check specs before they land on disk.

Invocation:
  python3 prd_split.py [--repo-root <path>] [--prd-id <id>] [--dry-run]

If --prd-id is omitted, the currently-active PRD (from the PRD runner's
state file) is used. --dry-run prints the planned writes without touching
disk.

Exit codes:
  0  success (or dry-run with no errors)
  2  any validation or state error

This script is intentionally independent of the issue runner. It never
mutates issue-runner state; a split PRD produces specs that the issue
runner will then `load` one at a time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ConfigError, load as load_config  # noqa: E402


TEMPLATE_RELPATH = Path(__file__).resolve().parent.parent / "templates" / "issue.md"
ISSUE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
REQUIRED_KEYS = ("id", "title", "allowed_files", "required_checks")
REQUIRED_NONEMPTY_LIST_KEYS = ("allowed_files", "required_checks")
OPTIONAL_LIST_KEYS = ("disallowed_files", "required_reviews")
DEFAULT_PRIORITY = "p1"


# ---------------------------------------------------------------------------
# PRD parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict, int]:
    """Return (frontmatter_dict, body_start_offset)."""
    if not text.startswith("---"):
        raise ValueError("PRD missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("PRD frontmatter not closed with ---")
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
    # end marker is "\n---"; body starts after the next newline following that.
    body_start = end + len("\n---")
    nl = text.find("\n", body_start)
    body_start = nl + 1 if nl != -1 else len(text)
    return result, body_start


def _extract_issues_block(body: str) -> str:
    """Return the fenced JSON block under the `## Issues` heading.

    Accepts either ```json ...``` or ``` ... ``` (first fenced block after
    the Issues heading). Raises ValueError when the heading or block is
    missing.
    """
    m = re.search(r"(?m)^##\s+Issues\s*$", body)
    if not m:
        raise ValueError("PRD is missing a `## Issues` section")
    rest = body[m.end():]
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", rest, flags=re.DOTALL)
    if not fence:
        raise ValueError("no fenced code block found under `## Issues`")
    return fence.group(1)


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def _validate_entry(entry: object, index: int) -> dict:
    if not isinstance(entry, dict):
        raise ValueError(f"entry #{index}: must be a JSON object")
    for key in REQUIRED_KEYS:
        if key not in entry:
            raise ValueError(f"entry #{index}: missing required key {key!r}")
    issue_id = entry["id"]
    if not isinstance(issue_id, str) or not ISSUE_ID_RE.match(issue_id):
        raise ValueError(
            f"entry #{index}: id must match {ISSUE_ID_RE.pattern!r}; got {issue_id!r}"
        )
    title = entry["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"entry #{index}: title must be a non-empty string")
    for key in REQUIRED_NONEMPTY_LIST_KEYS:
        v = entry[key]
        if not isinstance(v, list) or not v:
            raise ValueError(
                f"entry #{index}: {key} must be a non-empty list "
                "(empty list would silently bypass the verification gate)"
            )
        if not all(isinstance(x, str) and x for x in v):
            raise ValueError(
                f"entry #{index}: {key} entries must be non-empty strings"
            )
    for key in OPTIONAL_LIST_KEYS:
        if key in entry:
            v = entry[key]
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise ValueError(
                    f"entry #{index}: {key} must be a list of non-empty strings"
                )
    priority = entry.get("priority", DEFAULT_PRIORITY)
    if not isinstance(priority, str) or not priority:
        raise ValueError(f"entry #{index}: priority must be a non-empty string")
    acceptance = entry.get("acceptance", "")
    if not isinstance(acceptance, str):
        raise ValueError(f"entry #{index}: acceptance must be a string")
    return {
        "id": issue_id,
        "title": title.strip(),
        "priority": priority,
        "allowed_files": list(entry["allowed_files"]),
        "disallowed_files": list(entry.get("disallowed_files", [])),
        "required_checks": list(entry["required_checks"]),
        "required_reviews": list(entry.get("required_reviews", [])),
        "acceptance": acceptance,
    }


def _validate_manifest(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"issues manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("issues manifest must be a JSON array")
    seen_ids: set[str] = set()
    entries: list[dict] = []
    for i, item in enumerate(data):
        entry = _validate_entry(item, i)
        if entry["id"] in seen_ids:
            raise ValueError(f"duplicate issue id within manifest: {entry['id']!r}")
        seen_ids.add(entry["id"])
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Issue spec rendering
# ---------------------------------------------------------------------------


def _yaml_list(values: list[str]) -> str:
    """Render a YAML list suitable for the template placeholder.

    Empty list -> ` []` (inline). Non-empty -> newline + two-space indented
    `  - value` lines. The template places this immediately after the key's
    colon, so the leading newline/space is part of the rendered block.
    """
    if not values:
        return " []"
    return "\n" + "\n".join(f"  - {v}" for v in values)


def _render_spec(entry: dict, parent_prd_id: str, parent_prd_relpath: str) -> str:
    template = TEMPLATE_RELPATH.read_text()
    return (
        template.replace("{{id}}", entry["id"])
        .replace("{{title}}", entry["title"])
        .replace("{{priority}}", entry["priority"])
        .replace("{{parent_prd}}", parent_prd_id)
        .replace("{{parent_prd_path}}", parent_prd_relpath)
        .replace("{{allowed_files_yaml}}", _yaml_list(entry["allowed_files"]))
        .replace("{{disallowed_files_yaml}}", _yaml_list(entry["disallowed_files"]))
        .replace("{{required_checks_yaml}}", _yaml_list(entry["required_checks"]))
        .replace("{{required_reviews_yaml}}", _yaml_list(entry["required_reviews"]))
        .replace("{{acceptance}}", entry["acceptance"] or "<!-- fill in -->")
    )


# ---------------------------------------------------------------------------
# PRD resolution
# ---------------------------------------------------------------------------


def _resolve_prd_path(cfg: Config, prd_id: Optional[str]) -> tuple[str, Path]:
    if prd_id:
        path = cfg.prds_dir / f"{prd_id}.md"
        if not path.is_file():
            raise ValueError(f"PRD spec not found: {path}")
        return prd_id, path
    # Fall back to active PRD state.
    state_path = cfg.active_prd_state_path
    if not state_path.is_file():
        raise ValueError(
            "no --prd-id given and no active PRD state. Load or create a PRD first."
        )
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{state_path}: invalid JSON ({exc})") from exc
    active_id = state.get("prd_id")
    spec_path_rel = state.get("spec_path")
    if not active_id or not spec_path_rel:
        raise ValueError("active PRD state is empty; pass --prd-id explicitly")
    path = cfg.repo_root / spec_path_rel
    if not path.is_file():
        raise ValueError(f"active PRD spec missing on disk: {path}")
    return active_id, path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="override repo root discovery")
    parser.add_argument("--prd-id", help="PRD id; defaults to active PRD state")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and print planned writes; do not touch disk"
    )
    args = parser.parse_args(argv)

    try:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        cfg = load_config(repo_root, strict=True)
    except ConfigError as exc:
        sys.stderr.write(f"prd-os config error: {exc}\n")
        return 2

    try:
        prd_id, prd_path = _resolve_prd_path(cfg, args.prd_id)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    text = prd_path.read_text()
    try:
        fm, body_start = _parse_frontmatter(text)
    except ValueError as exc:
        sys.stderr.write(f"{prd_path}: {exc}\n")
        return 2
    status = fm.get("status")
    if status != "approved":
        sys.stderr.write(
            f"refusing to split PRD with status={status!r}. "
            "Only approved PRDs may be split.\n"
        )
        return 2
    parent_prd_id = fm.get("id", prd_id)

    try:
        raw_manifest = _extract_issues_block(text[body_start:])
        entries = _validate_manifest(raw_manifest)
    except ValueError as exc:
        sys.stderr.write(f"{prd_path}: {exc}\n")
        return 2
    if not entries:
        sys.stderr.write(f"{prd_path}: issues manifest is empty; nothing to split\n")
        return 2

    try:
        parent_prd_relpath = str(prd_path.resolve().relative_to(cfg.repo_root))
    except ValueError:
        parent_prd_relpath = str(prd_path)

    planned: list[tuple[Path, str]] = []
    collisions: list[str] = []
    for entry in entries:
        target = cfg.issues_dir / f"{entry['id']}.md"
        rendered = _render_spec(entry, parent_prd_id, parent_prd_relpath)
        if target.exists():
            existing = target.read_text()
            if existing != rendered:
                collisions.append(str(target))
                continue
            # byte-identical: idempotent re-run, skip
            continue
        planned.append((target, rendered))

    if collisions:
        sys.stderr.write(
            "refusing to clobber existing issue spec(s):\n  - "
            + "\n  - ".join(collisions)
            + "\n"
        )
        return 2

    if args.dry_run:
        print(json.dumps(
            {
                "prd_id": parent_prd_id,
                "would_create": [str(p) for p, _ in planned],
                "skipped_existing_identical": [
                    str(cfg.issues_dir / f"{e['id']}.md")
                    for e in entries
                    if (cfg.issues_dir / f"{e['id']}.md").exists()
                ],
            },
            indent=2,
        ))
        return 0

    cfg.issues_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for target, rendered in planned:
        target.write_text(rendered)
        created.append(str(target.relative_to(cfg.repo_root)) if target.is_absolute() else str(target))
    print(json.dumps({"prd_id": parent_prd_id, "created": created}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
