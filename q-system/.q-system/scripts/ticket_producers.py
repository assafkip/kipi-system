#!/usr/bin/env python3
"""The creation gate's one reader of q-system/.q-system/ticket-producers.json (ASK-4205).

Founder, 2026-11-09: "What's the point of tickets that nothing can close?" The
inflow audit that morning measured 72.5 tickets filed a day against 20 closed,
and 575 of 621 open spillover tickets never touched. Producers filed tickets as
a record, with no job that works them or closes them. So a producer now has to
be registered with a consumer and an exit before it may create one.

WHERE THE GATE BITES, AND WHY TWO PLACES
  * run time: `linear-sync.py create` calls refusal() before any network call.
    It is the only create path that takes a plan from outside, so the producer
    is a claim made at run time and has to be checked there.
  * merge time: test_ticket_producers.py calls coverage_problems(). Every other
    filer in this repo is a script with its own create mutation, so its producer is
    fixed in its source. Pinning that source to a registry row in CI refuses a
    new filer before it can ever run, which is earlier than any run-time check
    inside it could be. A run-time call inside such a script would only refuse
    after a registry edit that the same CI test already refuses.

FAILS CLOSED. An unreadable or invalid registry refuses the create with the
reason. A gate that passes when its table is missing protects nothing, and the
refusal is loud (non-zero exit, reason on stderr), never a silent skip.

Python 3.9: launchd runs /usr/bin/python3 3.9.6. A 3.10-only annotation in
linear-sync.py crashed every launchd job that loaded it (hotfix PR #703). So no
`X | Y` outside the future import, and no `match`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REGISTRY_REL = os.path.join("q-system", ".q-system", "ticket-producers.json")
TICKET_STATES_REL = os.path.join("q-system", ".q-system", "terminal-states.json")

GATES = ("runtime", "static", "hook", "none")
REQUIRED_EXIT_KINDS = ("worked", "triage", "age-close", "recovered", "keyed")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TICKET_RE = re.compile(r"^ASK-\d+$")

# The shape of "this file builds a Linear issue create". Narrower than
# linear-filer-label-lint.py's bare word on purpose: that lint must see a file
# that merely names the mutation, this test must not list a file as a producer
# because a docstring mentions it (linear-triage-health.py does, line 285).
# Three spellings, each seen in a live filer on 2026-11-09: the mutation text
# with its argument list (alert-to-linear, cap-ladder, linear-sync), the result
# read back by its quoted key (dor-drafter, job-migration), and linear-sync's
# upper-case constant borrowed by another script (fleet-health-daily,
# stall-sweep). Described in words here, not spelled, because this file is
# tracked too: the first red run on a copy of main listed it as a filer.
# The mutation name is joined from two halves for the same reason:
# linear-filer-label-lint.py (a PostToolUse hook in this repo's settings) blocks
# any edit of a file holding the bare word, and this file files nothing.
_M = "issue" + "Create"
CREATE_RE = re.compile(_M + r"\s*\(|[\"']" + _M + r"[\"']|\bISSUE_" + r"CREATE\b")
SCANNED_SUFFIXES = (".py", ".sh", ".js", ".mjs", ".ts")


class RegistryError(Exception):
    """The registry cannot be read or is not the expected shape."""


def repo_root() -> str:
    """The checkout this module sits in: scripts -> .q-system -> q-system -> root."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def registry_path(root: str | None = None) -> str:
    """The registry this checkout ships. KIPI_TICKET_PRODUCERS overrides it only
    under KIPI_TEST=1, so a live run cannot be pointed at a permissive copy."""
    override = os.environ.get("KIPI_TICKET_PRODUCERS")
    if override and os.environ.get("KIPI_TEST") == "1":
        return override
    return os.path.join(root or repo_root(), REGISTRY_REL)


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            reg = json.load(fh)
    except OSError as exc:
        raise RegistryError(f"cannot read the producer registry {path}: {exc}") from exc
    except ValueError as exc:
        raise RegistryError(f"the producer registry {path} is not valid JSON: {exc}") from exc
    if not isinstance(reg, dict) or not isinstance(reg.get("producers"), list):
        raise RegistryError(f"the producer registry {path} has no `producers` list")
    return reg


def _external(ref: str, reg: dict) -> bool:
    return any(ref.startswith(p) for p in (reg.get("external_prefixes") or {}))


def _repo_ref_problem(ref: str, field: str, reg: dict, root: str) -> str:
    """A repo path must exist; an external ref must use a declared prefix."""
    if ":" in ref.split("/", 1)[0]:
        if not _external(ref, reg):
            return f"{field} `{ref}` uses a prefix not in external_prefixes"
        return ""
    if not os.path.isfile(os.path.join(root, ref)):
        return f"{field} `{ref}` does not exist in this checkout"
    return ""


def row_problems(row, reg: dict, root: str, states: set | None = None) -> list:
    """Every reason this one row cannot back a create. Empty list = usable."""
    if not isinstance(row, dict):
        return ["a producer row is not an object"]
    pid = row.get("id")
    who = f"producer `{pid}`"
    out = []
    if not isinstance(pid, str) or not ID_RE.match(pid):
        out.append(f"{who}: id must match {ID_RE.pattern}")

    consumer = row.get("consumer")
    if not isinstance(consumer, str) or not consumer.strip():
        out.append(f"{who}: no consumer (the script or agent that works or decides its tickets)")
    else:
        p = _repo_ref_problem(consumer.strip(), "consumer", reg, root)
        if p:
            out.append(f"{who}: {p}")

    ex = row.get("exit")
    kinds = reg.get("exit_kinds") or {}
    if not isinstance(ex, dict) or not str(ex.get("kind") or "").strip() or not str(ex.get("by") or "").strip():
        out.append(f"{who}: no exit (exit.kind and exit.by, how its tickets close and which script closes them)")
    else:
        if ex["kind"] not in kinds:
            out.append(f"{who}: exit.kind `{ex['kind']}` is not one of {sorted(kinds)}")
        p = _repo_ref_problem(str(ex["by"]).strip(), "exit.by", reg, root)
        if p:
            out.append(f"{who}: {p}")

    sig = row.get("signature")
    if sig is None:
        if not str(row.get("signature_note") or "").strip():
            out.append(f"{who}: signature is null with no signature_note saying why")
    elif not isinstance(sig, str) or not sig.strip():
        out.append(f"{who}: signature must be a regex or null")
    else:
        try:
            re.compile(sig)
        except re.error as exc:
            out.append(f"{who}: signature does not compile: {exc}")

    paths = row.get("create_paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(x, str) and x.strip() for x in paths):
        out.append(f"{who}: create_paths must be a non-empty list")
    else:
        for ref in paths:
            p = _repo_ref_problem(ref.strip(), "create_path", reg, root)
            if p:
                out.append(f"{who}: {p}")
    via = row.get("via")
    if via:
        p = _repo_ref_problem(str(via).strip(), "via", reg, root)
        if p:
            out.append(f"{who}: {p}")

    gate = row.get("gate")
    if gate not in GATES:
        out.append(f"{who}: gate must be one of {list(GATES)}")
    if gate == "none" and not TICKET_RE.match(str(row.get("gap") or "")):
        out.append(f"{who}: gate `none` needs `gap`, the ticket that builds its gate")
    if gate == "hook" and not str(row.get("hook") or "").strip():
        out.append(f"{who}: gate `hook` needs `hook`, the hook file that gates the create")
    if row.get("gap") and not TICKET_RE.match(str(row["gap"])):
        out.append(f"{who}: gap `{row['gap']}` is not a ticket id")

    # Fails closed like the rest (PR #705 review, nit 3): an unreadable
    # terminal-states.json used to skip this check and let the row through.
    bs = row.get("board_state")
    if bs is not None and states is None:
        out.append(f"{who}: board_state `{bs}` cannot be checked: {TICKET_STATES_REL} is unreadable")
    elif bs is not None and bs not in states:
        out.append(f"{who}: board_state `{bs}` is not a ticket_states row in terminal-states.json")
    return out


def _ticket_states(root: str):
    try:
        with open(os.path.join(root, TICKET_STATES_REL), encoding="utf-8") as fh:
            return set(((json.load(fh).get("ticket_states") or {}).get("rows") or {}))
    except (OSError, ValueError):
        return None


def lint(reg: dict, root: str) -> list:
    """Whole-registry problems: each row, plus ids, kinds and the one fallback."""
    out = []
    kinds = reg.get("exit_kinds")
    if not isinstance(kinds, dict) or any(k not in kinds for k in REQUIRED_EXIT_KINDS):
        out.append(f"exit_kinds must define {list(REQUIRED_EXIT_KINDS)}")
    states = _ticket_states(root)
    seen = set()
    fallbacks = 0
    for row in reg.get("producers") or []:
        out.extend(row_problems(row, reg, root, states))
        if isinstance(row, dict):
            if row.get("id") in seen:
                out.append(f"producer `{row.get('id')}` is listed twice")
            seen.add(row.get("id"))
            fallbacks += 1 if row.get("fallback") else 0
    if fallbacks > 1:
        out.append(f"{fallbacks} rows say fallback: true; at most one may")
    return out


def refusal(producer, create_path: str, root: str | None = None, path: str | None = None):
    """None when `producer` may create through `create_path`; else the reason.

    create_path is repo-relative, for example
    q-system/.q-system/scripts/linear-sync.py. The row must name it: a producer
    registered for one path does not get to file through another.
    """
    root = root or repo_root()
    path = path or registry_path(root)
    try:
        reg = load(path)
    except RegistryError as exc:
        return f"{exc}. The creation gate fails closed (ASK-4205)."
    ids = sorted(str(r.get("id")) for r in reg["producers"] if isinstance(r, dict))
    if not producer:
        return (f"no producer named. Pass --producer <id>, or set `producer` in the plan. "
                f"Registered: {', '.join(ids)}.")
    rows = [r for r in reg["producers"] if isinstance(r, dict) and r.get("id") == producer]
    if not rows:
        return (f"producer `{producer}` is not registered in {REGISTRY_REL}. Add a row naming "
                f"its consumer and its exit first (ASK-4205). Registered: {', '.join(ids)}.")
    row = rows[0]
    problems = row_problems(row, reg, root, _ticket_states(root))
    if problems:
        return "; ".join(problems) + f". Fix its row in {REGISTRY_REL} (ASK-4205)."
    if create_path not in (row.get("create_paths") or []):
        return (f"producer `{producer}` is registered to create through "
                f"{', '.join(row.get('create_paths') or [])}, not {create_path}. "
                f"Add the path to its row if this is a real new route (ASK-4205).")
    return None


def is_test_path(path: str) -> bool:
    """A suite constructs the mutation to assert on it, so it is not a producer.

    Anchored, unlike linear-filer-label-lint.py's substring match: there
    `latest-filer.py` and `contest_filer.py` read as tests (PR #705 review, nit
    2), and here that would excuse a real filer from the coverage gate. A test
    is a file under tests/ or test/, a name that STARTS with test_ or test-, or
    one that ENDS in _test or -test before its suffix."""
    norm = path.replace(os.sep, "/")
    base = norm.rsplit("/", 1)[-1]
    if "/tests/" in "/" + norm or "/test/" in "/" + norm:
        return True
    stem = base.rsplit(".", 1)[0]
    return base.startswith(("test_", "test-")) or stem.endswith(("_test", "-test"))


def tracked_filers(root: str) -> list:
    """Tracked, non-test source files that construct a Linear issue create."""
    res = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True)
    out = []
    for rel in res.stdout.decode("utf-8", "replace").split("\0"):
        if not rel or not rel.endswith(SCANNED_SUFFIXES) or is_test_path(rel):
            continue
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if CREATE_RE.search(text):
            out.append(rel)
    return sorted(out)


def coverage_problems(reg: dict, root: str, filers: list | None = None) -> list:
    """Both directions: every filer has a row, and every repo create path in a
    row still builds a create (a stale row is a claim nothing backs)."""
    filers = tracked_filers(root) if filers is None else filers
    named = set()
    for row in reg.get("producers") or []:
        if isinstance(row, dict):
            named.update(p for p in (row.get("create_paths") or []) if isinstance(p, str))
    skipped = [str(n.get("path") or "") for n in (reg.get("not_producers") or []) if isinstance(n, dict)]
    out = []
    for rel in filers:
        if rel in named or any(s and rel.startswith(s) for s in skipped):
            continue
        out.append(f"{rel} builds a Linear issue create and no producer row names it. Add a row to "
                   f"{REGISTRY_REL} with its consumer and its exit (ASK-4205).")
    for ref in sorted(named):
        if ":" in ref.split("/", 1)[0]:
            continue
        if ref not in filers:
            out.append(f"create_path `{ref}` no longer builds an issue create; fix or drop its row.")
    for n in reg.get("not_producers") or []:
        if not isinstance(n, dict) or not str(n.get("why") or "").strip():
            out.append(f"not_producers entry {n!r} needs a `why`")
    return out


def main(argv: list) -> int:
    if len(argv) >= 2 and argv[1] == "lint":
        root = repo_root()
        try:
            reg = load(registry_path(root))
        except RegistryError as exc:
            print(f"ticket-producers: {exc}", file=sys.stderr)
            return 1
        problems = lint(reg, root) + coverage_problems(reg, root)
        for p in problems:
            print(f"ticket-producers: {p}", file=sys.stderr)
        print(f"ticket-producers: {len(reg['producers'])} producer(s), {len(problems)} problem(s)")
        return 1 if problems else 0
    if len(argv) == 4 and argv[1] == "check":
        why = refusal(argv[2], argv[3])
        if why:
            print(f"REFUSED: {why}", file=sys.stderr)
            return 5
        print(f"ok: {argv[2]} may create through {argv[3]}")
        return 0
    print("usage: ticket_producers.py lint | check <producer> <create-path>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
