#!/usr/bin/env python3
"""voice_suppressions: the ONE reader of an instance's voice-suppressions.json (K7).

prd-voicegate-skeleton-2026-11-09, spec vg-k7-suppression-file (ASK-4257).

WHY ONE READER: before K7 the only way to suppress a voice lint was an in-file marker
(`voice-lint-skip`, `voiceloop-band-lint-skip`): no owner, no reason, no expiry, and
nothing ever counted them. The lints call `check()` and never parse the file
themselves, so the row contract lives in one place and a census test
(test_voice_suppressions.py) fails on any script that names a marker without
loading this module.

WHY IT NEVER RAISES: voice-lint.py is a blocking PostToolUse gate shipped to every
instance. An uncaught exception exits 1, and Claude Code treats exit 1 as
non-blocking, so one bad row would fail the gate OPEN for every draft. A bad file or
row therefore suppresses nothing and comes back as a note naming the file.

THE SWITCH: an instance that HAS the file (present, even if unreadable) no longer
honours in-file markers. Breaking the file must not bring the old bypass back.
Without the file every lint behaves exactly as before K7 and this module says nothing.

Discovery (PRD "Shared discovery rule"): root is $CLAUDE_PROJECT_DIR, else the git
toplevel of the draft; the content dir comes from evidence_ledger.instance_root; the
file is <root>/<q_dir>/config/voice-suppressions.json. No env var names the file:
hooks and launchd jobs see different environments.
"""
from __future__ import annotations

import importlib.util
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

FILE_NAME = "voice-suppressions.json"

# Who may own a voice exception. Closed on purpose: an owner is who answers for the
# row when it expires, so it must be an agent the fleet can route to. The founder is
# not on it: no row may make him the next actor (RULE 2026-11-07, no-idle-escalate).
OWNERS = frozenset({"sana", "cole", "sal", "amber", "ryan"})

MAX_DAYS = 30
# A hook runs on every draft write with a 5 s budget (voice-substance-lint). A file
# this size is already far past any real use; past it we refuse rather than parse.
MAX_BYTES = 256 * 1024
MAX_REPORTED = 5

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_GLOB_CHARS = frozenset("*?[]{}")


class Decision:
    """present: the instance has the file (in-file markers are off).
    skip: a valid, live row names this draft. notes: every line the lint must print."""

    def __init__(self, present=False, skip=False, notes=None, source=None):
        self.present = present
        self.skip = skip
        self.notes = list(notes or [])
        self.source = source

    def marker_ignored(self, marker):
        where = self.source or FILE_NAME
        return (f"in-file marker <!-- {marker} --> ignored: this instance keeps voice "
                f"suppressions in {where}; add a row there (path, reason, owner, "
                "created, expires).")


def _short(value, limit=80):
    """repr bounded, so a hostile file cannot put megabytes into a hook's output."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _today():
    return datetime.now(timezone.utc).date()


def _parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _path_problem(path):
    if not isinstance(path, str) or not path.strip():
        return "path must be a non-empty string"
    if any(ord(c) < 32 for c in path) or len(path) > 512:
        return "path has control characters or is over 512 characters"
    if path.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", path):
        return "path is absolute; it must be relative to the instance root"
    if _GLOB_CHARS & set(path):
        return "path has glob characters; it must name one exact file"
    if ".." in path.split("/"):
        return "path has a '..' segment"
    if "\\" in path or posixpath.normpath(path) != path:
        return "path is not an exact repo-relative path (no ./, //, or trailing /)"
    return None


def row_problem(row, today):
    """Why a row is malformed, or None. Expiry is judged separately, by path."""
    if not isinstance(row, dict):
        return "row is not an object"
    problem = _path_problem(row.get("path"))
    if problem:
        return problem
    reason = row.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return "reason is missing or empty"
    owner = row.get("owner")
    # isinstance first: a list or object is unhashable and `in frozenset` raises,
    # which would void every valid row in the file (review finding-1).
    if not isinstance(owner, str) or owner not in OWNERS:
        return f"owner {_short(owner, 30)} is not one of {', '.join(sorted(OWNERS))}"
    created, expires = _parse_date(row.get("created")), _parse_date(row.get("expires"))
    if created is None or expires is None:
        return "created and expires must each be a date written YYYY-MM-DD"
    # A future `created` would let a row start its 30 days later and so outlive them.
    if created > today:
        return f"created {created} is after today {today}"
    if expires <= created:
        return f"expires {expires} is not after created {created}"
    if (expires - created).days > MAX_DAYS:
        return (f"expires {expires} is {(expires - created).days} days after created, "
                f"more than {MAX_DAYS}")
    return None


def evaluate(data, rel_paths, today, source):
    """(live row naming one of rel_paths or None, notes). Pure: no I/O, no clock."""
    if not isinstance(data, dict) or not isinstance(data.get("suppressions"), list):
        return None, [f"{source}: top level must be an object holding a \"suppressions\" "
                      "list; suppressing nothing."]
    notes, bad, expired, hit = [], 0, 0, None
    for index, row in enumerate(data["suppressions"]):
        problem = row_problem(row, today)
        if problem:
            bad += 1
            if bad <= MAX_REPORTED:
                path = row.get("path") if isinstance(row, dict) else row
                notes.append(f"{source}: row {index} ({_short(path, 60)}) suppresses "
                             f"nothing: {problem}.")
            continue
        if row["path"] not in rel_paths:
            continue
        expires = _parse_date(row["expires"])
        if today >= expires:
            expired += 1
            if expired <= MAX_REPORTED:
                notes.append(f"{source}: row {index} for {row['path']} expired on "
                             f"{expires} (today {today}); it no longer skips.")
        elif hit is None:
            hit = row
    if expired > MAX_REPORTED:
        notes.append(f"{source}: and {expired - MAX_REPORTED} more expired rows for "
                     "this path.")
    if bad > MAX_REPORTED:
        notes.append(f"{source}: and {bad - MAX_REPORTED} more invalid rows, each "
                     "suppressing nothing.")
    return hit, notes


def _instance_root_for(file_path):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(file_path).resolve().parent), "rev-parse",
             "--show-toplevel"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def _load_ledger():
    name = "_evidence_ledger_for_voice_suppressions"
    if name in sys.modules:
        return sys.modules[name]
    target = Path(__file__).resolve().parent / "evidence_ledger.py"
    spec = importlib.util.spec_from_file_location(name, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # its dataclasses look themselves up by module name
    spec.loader.exec_module(module)
    return module


def _rel_paths(file_path, root):
    """The draft relative to root, both as written and with symlinks resolved, so a
    /tmp versus /private/tmp spelling cannot make an exact row miss."""
    found = set()
    for fn in (os.path.abspath, os.path.realpath):
        try:
            rel = os.path.relpath(fn(file_path), fn(str(root)))
        except (OSError, ValueError):
            continue
        rel = rel.replace(os.sep, "/")
        if rel != ".." and not rel.startswith("../"):
            found.add(rel)
    return found


def _read(path, today, file_path, root):
    source = str(path)
    try:
        info = os.stat(path)
        # A FIFO reports size 0 and then blocks open() until the hook times out, and a
        # PostToolUse timeout is non-blocking: the gate would fail open (finding-4).
        if not stat.S_ISREG(info.st_mode):
            return Decision(True, False, [f"{source} is not a regular file; suppressing "
                                          "nothing."], source)
        size = info.st_size
        if size > MAX_BYTES:
            return Decision(True, False, [f"{source} is too large ({size} bytes, limit "
                                          f"{MAX_BYTES}); suppressing nothing."], source)
        with open(path, encoding="utf-8") as handle:
            data = json.loads(handle.read(MAX_BYTES + 1))
    # Exception, not (OSError, ValueError): deep nesting raises RecursionError.
    except Exception as exc:
        return Decision(True, False, [f"{source} unreadable ({type(exc).__name__}); "
                                      "suppressing nothing."], source)
    hit, notes = evaluate(data, _rel_paths(file_path, root), today, source)
    if hit is not None:
        notes.append(f"SUPPRESSED by {source}: {hit['path']} (owner {hit['owner']}, "
                     f"reason {_short(hit['reason'], 120)}, expires {hit['expires']}).")
    return Decision(True, hit is not None, notes, source)


def check(file_path):
    """The decision for one draft. Never raises."""
    try:
        root = _instance_root_for(file_path)
        if root is None:
            return Decision()
        # ASK-4277: a draft outside the root (sibling repo, or the temp file
        # voice-stop-gate lints) can never be named by a legal row, because '..' and
        # absolute paths are refused. Switching its marker off would leave it with no
        # way to be suppressed, so out of root the lints behave as before K7.
        if not _rel_paths(file_path, root):
            return Decision()
        try:
            q_dir = _load_ledger().instance_root(root, allow_unregistered=True)
        except Exception as exc:
            # The resolver refused (ambiguous q-* dirs, registry disagreement, no
            # canonical/). Only a file that exists somewhere makes that our business.
            present = [p / "config" / FILE_NAME for p in sorted(root.glob("q-*"))
                       if os.path.lexists(p / "config" / FILE_NAME)]
            if not present:
                return Decision()
            return Decision(True, False, [
                f"{FILE_NAME} NOT READ under {root}: {str(exc)[:300]}; suppressing "
                "nothing."], str(present[0]))
        path = q_dir / "config" / FILE_NAME
        if not os.path.lexists(path):
            return Decision()
        return _read(path, _today(), file_path, root)
    except Exception as exc:
        # A defect in this module must not reopen markers: fail closed, and say so.
        return Decision(True, False, [f"voice_suppressions.py failed "
                                      f"({type(exc).__name__}: {str(exc)[:200]}); "
                                      "suppressing nothing."])


def hook_context(lines):
    """The PostToolUse channel the agent reads on exit 0 (stderr is dropped there).
    Nested under hookSpecificOutput: a top-level additionalContext is ignored."""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": "\n".join(lines)}})
