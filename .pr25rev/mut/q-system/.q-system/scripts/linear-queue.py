#!/usr/bin/env python3
"""Capture half of the Linear queue/drain split. Runs anywhere, needs nothing.

Pairs with linear-sync.py (the planner) and the reproducer
q-system/.q-system/scripts/test/test-linear-queue.sh.

WHY THIS EXISTS (ASK-113): there is no Linear API key in ~/.config/kipi/ and no
LINEAR_* env var, so Linear is reachable only through the MCP server, which is
available to the agent and NOT to a bash script such as kipi-new-instance.sh. The
mechanism is therefore split at the credential boundary:

    bash appends here  ->  agent drains it  ->  Linear

Capture is the deterministic guarantee: appending a line to a local file has no
network dependency, so a build or a `kipi new` cannot silently fail to record
itself. The Linear write happens later, where credentials exist.

APPEND-ONLY, SINGLE WRITER. The file is a log of two operations, `add` and
`drain`; pending state is DERIVED (adds minus drains) rather than stored. Nothing
ever rewrites the file, so a crash mid-write costs at most one trailing line and a
concurrent reader never sees a truncated queue.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_sync():
    """Reuse linear-sync.py's key derivation instead of copying it.

    Two independent slugify implementations WILL drift, and the drift would show
    up as duplicate Linear issues, which an agent cannot delete. One source; the
    test suite pins both ends (test-linear-queue.sh case 9).
    """
    spec = importlib.util.spec_from_file_location(
        "linear_sync", os.path.join(HERE, "linear-sync.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sync = _load_sync()
make_key = _sync.make_key


def queue_path() -> str:
    """Repo root, not q-system/. `kipi update` runs rsync --delete over an
    instance's q-system/ subtree, which would clobber a queue living there
    (RULE-2026-06-30-A, enforced by instance-automation-guard.py)."""
    override = os.environ.get("KIPI_LINEAR_QUEUE")
    if override:
        return override
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if top.returncode == 0 and top.stdout.strip():
            return os.path.join(top.stdout.strip(), ".linear-queue.jsonl")
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(os.getcwd(), ".linear-queue.jsonl")


def read_ops() -> list:
    """A malformed line is skipped, never fatal. This file is appended to by
    unattended jobs; one bad line must not take out the founder's next command."""
    path = queue_path()
    ops = []
    if not os.path.exists(path):
        return ops
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and rec.get("key"):
                    ops.append(rec)
    except OSError:
        return []
    return ops


def append_op(rec: dict) -> bool:
    """The ONLY writer.

    Returns False on a write failure but the CALLER still exits 0. Deliberate
    tradeoff: this runs inside `kipi new` and inside build paths, and a founder's
    command must not die because a queue file was unwritable. The failure is loud
    on stderr rather than silent, so it is noticed without being blocking.
    """
    path = queue_path()
    rec["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        print(f"WARN: could not write the Linear queue at {path}: {exc}", file=sys.stderr)
        print("WARN: this capture was LOST. Open the issue by hand.", file=sys.stderr)
        return False


def pending_items() -> list:
    """Derived state: every `add` whose key has never been `drain`ed.

    Draining is permanent on purpose. A re-capture of an already-drained key must
    NOT resurrect it, or a second `kipi new` on the same repo would queue a second
    Linear project, and an agent cannot delete a Linear project.
    """
    drained = {op["key"] for op in read_ops() if op.get("op") == "drain"}
    out, seen = [], set()
    for op in read_ops():
        if op.get("op") != "add":
            continue
        key = op["key"]
        if key in drained or key in seen:
            continue
        seen.add(key)
        out.append(op)
    return out


def cmd_add(args) -> int:
    key = args.key or make_key(args.repo, args.title)
    drained = {op["key"] for op in read_ops() if op.get("op") == "drain"}
    if key in drained:
        print(f"already drained, skipping: {key}")
        return 0
    if any(item["key"] == key for item in pending_items()):
        print(f"already queued: {key}")
        return 0
    append_op({
        "op": "add", "key": key, "repo": args.repo, "kind": args.kind,
        "title": args.title, "note": args.note or "",
        "state": args.state, "source": args.source or "manual",
    })
    print(f"queued {args.kind}: {key}")
    return 0


def cmd_pending(args) -> int:
    items = pending_items()
    if args.json:
        json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0
    if not items:
        print(f"Linear queue is empty ({queue_path()})")
        return 0
    print(f"{len(items)} pending item(s) in {queue_path()}:\n")
    for item in items:
        print(f"  [{item['kind']:7}] {item['key']}")
        print(f"            {item['title']}")
        if item.get("note"):
            print(f"            note: {item['note']}")
    print("\nDrain with the /linear-drain command (needs the Linear MCP server).")
    return 0


def cmd_mark_drained(args) -> int:
    drained = {op["key"] for op in read_ops() if op.get("op") == "drain"}
    if args.key in drained:
        print(f"already drained: {args.key}")
        return 0
    append_op({"op": "drain", "key": args.key, "identifier": args.identifier})
    print(f"drained {args.key} -> {args.identifier}")
    return 0


def cmd_key(args) -> int:
    print(make_key(args.repo, args.title))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Queue Linear work for a later agent drain.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="capture an intent (never touches the network)")
    p.add_argument("--repo", required=True)
    p.add_argument("--kind", required=True, choices=["issue", "project"])
    p.add_argument("--title", required=True)
    p.add_argument("--key", help="override the derived dedup key")
    p.add_argument("--note", help="free text carried into the Linear description")
    p.add_argument("--state", default="Todo", help="target Linear state")
    p.add_argument("--source", help="what captured this (kipi-new, manual, hook)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("pending", help="items not yet created in Linear")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("mark-drained", help="record that Linear now has this")
    p.add_argument("--key", required=True)
    p.add_argument("--identifier", required=True, help="e.g. ASK-137")
    p.set_defaults(func=cmd_mark_drained)

    p = sub.add_parser("key", help="print the dedup key for a repo/title pair")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.set_defaults(func=cmd_key)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
