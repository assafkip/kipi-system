#!/usr/bin/env python3
"""system_manifest: declare what a data path is MADE OF, so coverage is computable.

WHY (RCA rca-conclusions-before-evidence-2026-07-28, contributing factor): "No
manifest exists declaring which workflows constitute a data path, so 'have I read all
of this subsystem' is not a computable question today." Two of five workflows in a
chain were read and conclusions were issued about the chain. The grounding guard was
silent because each individual file HAD been opened -- its docstring names this exact
seam. A manifest turns the seam into set arithmetic.

This module owns the manifest; `code_claim_grounding_guard.py` is its consumer.

HONEST BOUNDARY: this proves every declared member appeared somewhere in session
evidence. It does not prove the member was read carefully, nor that the manifest lists
every real member -- a manifest that omits a workflow will happily certify a claim
about a chain you have not fully seen. Keeping the manifest true is a human job; this
file only makes the arithmetic honest once it is.

Layout: `<instance-root>/canonical/system-manifest.json`

  {"version": 1,
   "subsystems": [
     {"id": "groupme-to-sheet",
      "name": "GroupMe order intake to Google Sheet",
      "aliases": ["the ingest chain"],
      "members": [{"ref": "Prodigy Gold - Parse LLM", "kind": "n8n-workflow"}]}]}

CLI:
  python3 system_manifest.py check              # exit 2 if the manifest is malformed
  python3 system_manifest.py list
  python3 system_manifest.py members <id>
  python3 system_manifest.py mentions <file>    # which subsystems this text names

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from evidence_ledger import instance_root  # one path resolver, not two

MANIFEST_NAME = "system-manifest.json"


def manifest_path(repo=None) -> Path:
    return instance_root(repo) / "canonical" / MANIFEST_NAME


MANIFEST_OK = "ok"
MANIFEST_ABSENT = "absent"
MANIFEST_UNREADABLE = "unreadable"


def health(repo=None) -> tuple[str, str]:
    """(status, human detail). The runtime-path answer to "can coverage be computed?"

    WHY THIS EXISTS SEPARATELY FROM `load()` (ASK-533). `load()` returns {} for BOTH
    "no manifest" and "manifest I could not parse", so its callers cannot tell a
    correct no-op from a broken one. `check()` already distinguishes them correctly --
    but nothing on the runtime path calls `check()`; the Stop hook only ever reaches
    `load()`. So the gate was weakest on exactly the corrupted evidence that should
    alarm it, which is the finding this closes.

    ABSENT IS NOT A PROBLEM AND MUST NOT BE REPORTED AS ONE. Most instances declare no
    data path; no-op is their correct steady state, and it is where every instance
    starts. Only PRESENT-BUT-UNREADABLE is the defect. Conflating the two would turn a
    Stop hook that fires every turn into a fleet-wide wedge, so the distinction here is
    load-bearing rather than cosmetic.

    Deliberately returns a status instead of raising: the caller is an unattended hook
    whose job is to keep running, and an exception would just get swallowed by another
    broad `except` somewhere up the stack, which is how this defect happened.
    """
    path = manifest_path(repo)
    if not path.exists():
        return (MANIFEST_ABSENT, "")
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return (MANIFEST_UNREADABLE, f"{path}: not valid JSON ({exc})")
    if not isinstance(obj, dict):
        return (MANIFEST_UNREADABLE,
                f"{path}: top level must be an object, got {type(obj).__name__}")
    # STRUCTURAL VALIDITY IS `check()`'s JOB, AND ONLY `check()`'s (Codex round 1 on
    # PR #132, MAJOR). The first cut of this function validated only the top level, so
    # `{"subsystems": "not-a-list"}` -- valid JSON, and a dict -- reported `ok` while
    # `subsystems()` returned [] and coverage silently did nothing. That is the same
    # fail-open this issue exists to close, one level deeper, reintroduced by the fix.
    #
    # Two functions answering "is this manifest usable?" with different rules is how
    # they drift apart; `check()` is the authority and this delegates to it rather than
    # restating a subset. Cost is one extra parse on a path that runs once per turn.
    problems = check(repo)
    if problems:
        head = "; ".join(problems[:5])
        more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
        return (MANIFEST_UNREADABLE, f"{path}: {head}{more}")
    return (MANIFEST_OK, "")


def load(repo=None) -> dict:
    """The manifest, or {} when absent or unreadable. Absence is never an error --
    most instances have no declared data path, and the gate must no-op for them.

    NOTE (ASK-533): this deliberately still swallows. Callers that need to tell absent
    from unreadable ask `health()`; changing this return contract would alter every
    read path at once on a hook that runs every turn."""
    path = manifest_path(repo)
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def subsystems(repo=None) -> list[dict]:
    subs = load(repo).get("subsystems", [])
    return [s for s in subs if isinstance(s, dict)]


def check(repo=None) -> list[str]:
    """Structural problems that would make coverage arithmetic lie."""
    path = manifest_path(repo)
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return [f"{MANIFEST_NAME} is not valid JSON ({exc})"]
    if not isinstance(obj, dict):
        return [f"{MANIFEST_NAME} top level must be an object"]

    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_labels: dict[str, str] = {}  # lowercase label -> owning subsystem id

    for i, sub in enumerate(obj.get("subsystems", [])):
        where = f"subsystems[{i}]"
        if not isinstance(sub, dict):
            problems.append(f"{where}: not an object")
            continue
        sid = str(sub.get("id", "")).strip()
        if not sid:
            problems.append(f"{where}: missing `id`")
            continue
        where = f"subsystem `{sid}`"
        if sid in seen_ids:
            problems.append(f"{where}: duplicate subsystem id")
        seen_ids.add(sid)
        if not str(sub.get("name", "")).strip():
            problems.append(f"{where}: missing `name`")

        members = sub.get("members", [])
        if not isinstance(members, list) or not members:
            # A memberless subsystem makes "did I read all of it" vacuously true,
            # which is worse than having no manifest at all.
            problems.append(f"{where}: has no members; coverage would be vacuous")
        else:
            seen_refs = set()
            for j, mem in enumerate(members):
                if not isinstance(mem, dict):
                    problems.append(f"{where}: members[{j}] is not an object")
                    continue
                ref = str(mem.get("ref", "")).strip()
                if not ref:
                    problems.append(f"{where}: members[{j}] missing `ref`")
                    continue
                if ref.lower() in seen_refs:
                    problems.append(f"{where}: duplicate member ref `{ref}`")
                seen_refs.add(ref.lower())

        for label in _labels(sub):
            owner = seen_labels.get(label)
            if owner and owner != sid:
                problems.append(
                    f"{where}: label `{label}` also names subsystem `{owner}`; "
                    "an ambiguous alias makes `mentions` unresolvable")
            seen_labels.setdefault(label, sid)

    return problems


def _labels(sub: dict) -> list[str]:
    """Every string this subsystem answers to, lowercased: id, name, aliases."""
    out = [str(sub.get("id", "")), str(sub.get("name", ""))]
    aliases = sub.get("aliases", [])
    if isinstance(aliases, list):
        out.extend(str(a) for a in aliases)
    return [s.strip().lower() for s in out if str(s).strip()]


def mentions(repo, text: str) -> list[str]:
    """Subsystem ids named anywhere in `text`, by id, name, or alias.

    Word-bounded so `parse` does not match inside `parser`, but a multi-word alias
    still matches as a phrase -- prose names a subsystem in words, not in ids. That is
    how every reversal in the source RCA was phrased.
    """
    if not text:
        return []
    hay = text.lower()
    hits = []
    for sub in subsystems(repo):
        sid = str(sub.get("id", "")).strip()
        if not sid:
            continue
        for label in _labels(sub):
            if re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", hay):
                hits.append(sid)
                break
    return sorted(set(hits))


def members(repo, subsystem_id: str) -> list[str]:
    for sub in subsystems(repo):
        if str(sub.get("id", "")).strip() == subsystem_id:
            return [str(m.get("ref", "")).strip()
                    for m in sub.get("members", [])
                    if isinstance(m, dict) and str(m.get("ref", "")).strip()]
    return []


def missing_members(repo, subsystem_id: str, evidence_blob: str) -> list[str]:
    """Declared members that appear NOWHERE in the session's evidence.

    Substring match, case-insensitive: a member ref is an n8n workflow name or a file
    path, and evidence carries it verbatim inside tool inputs and results.
    """
    hay = (evidence_blob or "").lower()
    return [ref for ref in members(repo, subsystem_id) if ref.lower() not in hay]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("list")
    m = sub.add_parser("members"); m.add_argument("subsystem_id")
    x = sub.add_parser("mentions"); x.add_argument("path")

    args = ap.parse_args(argv)
    repo = args.repo

    if args.cmd == "check":
        problems = check(repo)
        if problems:
            sys.stderr.write("system_manifest check FAILED:\n" +
                             "\n".join(f"  - {p}" for p in problems) + "\n")
            return 2
        subs = subsystems(repo)
        if not subs:
            print(f"system_manifest check OK (no {MANIFEST_NAME}; gate no-ops)")
        else:
            print(f"system_manifest check OK ({len(subs)} subsystems)")
        return 0

    if args.cmd == "list":
        for s in subsystems(repo):
            names = ", ".join(str(a) for a in s.get("aliases", []) or [])
            print(f"{s.get('id')}  ({len(s.get('members', []))} members)")
            print(f"    name   : {s.get('name')}")
            if names:
                print(f"    aliases: {names}")
        return 0

    if args.cmd == "members":
        for ref in members(repo, args.subsystem_id):
            print(ref)
        return 0

    if args.cmd == "mentions":
        text = Path(args.path).read_text(encoding="utf-8", errors="ignore")
        for sid in mentions(repo, text):
            print(sid)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
