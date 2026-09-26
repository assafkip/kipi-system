#!/usr/bin/env python3
"""The ONE reader of instance-registry.json for Linear-project reachability (ASK-1951).

WHY THIS FILE EXISTS
--------------------
`linear-worker.sh` resolved two facts from the registry inside a `python3 -`
heredoc: this repo's board name, and the set of board names whose checkout is on
this machine. ASK-1951 needs a THIRD consumer -- a check that fails when an
owner:sana issue sits on a project no checkout backs -- and the only honest way
to add it is to read the same derivation, not to retype it.

Retyping is the failure this file refuses. A copied list agrees on the day it is
written, which is what makes it look safe, and it keeps agreeing until the real
value moves; then the copy goes on asserting the old contract and PASSES
(lessons/derive-a-value-from-its-owner-never-restate-it-in-a-test). ASK-729
already recorded that the project-name derivation was duplicated between the
worker and spillover-promote.py. This is that one read, now importable.

THE ALIAS IS A FIELD, NOT A GUESS (ASK-840). A row's `name` was once read as if
it WERE the Linear project name. Nothing required those namespaces to agree and
measured against the live board they do not, so `linear_project` states the
mapping and `name` is only the fallback.

THE SKELETON ROW IS A CHECKOUT TOO (ASK-1951). The heredoc iterated
`reg["instances"]` only. `skeleton` is a SIBLING key, so the skeleton's own board
project -- `kipi-system`, which holds more dispatchable issues than any other --
resolved to no checkout at all. Measured against the live board 2026-09-26: 124
of the 137 issues this resolver called unreachable were `kipi-system`, whose
checkout is on disk and is the very repo the worker runs in. Reporting a present
checkout as absent is the same defect ASK-1951 is about, pointed the other way,
and it would have made the new check red forever on its own skeleton.

registry_ok travels separately and is NOT the same as an empty list. An
unreadable registry means reachability is UNKNOWN; reporting unknown as
unreachable fires a false alarm on every project at once.
"""
from __future__ import annotations

import json
import os


def linear_project(entry: dict) -> str:
    """The name this row carries ON THE BOARD. Explicit field first, name second."""
    if not isinstance(entry, dict):
        return ""
    return (entry.get("linear_project") or entry.get("name") or "").strip()


def _rows(reg):
    """Every registry row that can back a checkout, skeleton included.

    The skeleton is a single object under its own key, not a member of
    `instances`; yielding it here is what keeps `kipi-system` from resolving to
    nothing. `standalone` and `eliminated` are deliberately NOT yielded: a
    standalone repo carries no q-system and is not a dispatch target, and an
    eliminated row names a path that is gone by definition.
    """
    if isinstance(reg, dict):
        skel_row = reg.get("skeleton")
        if isinstance(skel_row, dict):
            yield skel_row
        entries = reg.get("instances", [])
    else:
        entries = reg
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict):
                yield e


def registry_facts(registry_path: str, target_repo: str | None = None) -> dict:
    """Read the registry once and answer both reachability questions.

    Returns ``{"name", "local_repos", "ok", "skeleton_project"}``.

    * ``name`` -- the board project of the row whose path IS ``target_repo``, or
      "" when no row matches. The caller decides the fallback; deriving one here
      would hide "no row claims this checkout" behind a basename guess.
    * ``local_repos`` -- one row per board project whose directory exists here,
      sorted, carrying the path and the pinned dispatch remote. The remote
      travels WITH the row because repo-preflight needs it and re-reading the
      registry to find it is the second reader ASK-729 refused to add.
    * ``ok`` -- False when the registry could not be read or parsed. Callers MUST
      treat False as UNKNOWN, never as unreachable.
    * ``skeleton_project`` -- who owns the project-unset population (ASK-839).
    """
    ok = True
    try:
        with open(registry_path) as fh:
            reg = json.load(fh)
    except Exception:
        reg, ok = [], False

    skel = os.path.realpath(target_repo) if target_repo else None
    name = ""
    local = []
    for e in _rows(reg):
        path = e.get("path")
        if not path:
            continue
        proj = linear_project(e)
        if skel and not name and os.path.realpath(path) == skel:
            name = proj
        if proj and os.path.isdir(path):
            dispatch = e.get("dispatch") if isinstance(e.get("dispatch"), dict) else {}
            local.append({"project": proj, "path": path,
                          "remote": dispatch.get("expected_remote") or ""})
    local.sort(key=lambda r: r["project"])

    skel_row = reg.get("skeleton") if isinstance(reg, dict) else None
    return {
        "name": name,
        "local_repos": local,
        "ok": ok,
        "skeleton_project": linear_project(skel_row) if isinstance(skel_row, dict) else "",
    }


def local_by_project(facts: dict) -> dict:
    """Board project -> its local row, from the facts a single read produced."""
    return {r["project"]: r for r in facts.get("local_repos") or [] if r.get("project")}


def default_registry_path() -> str:
    """The skeleton's registry, which is the only copy that exists.

    The path being looked UP is the target; the registry doing the looking up is
    always the skeleton. An instance carries no instance-registry.json, so
    reading it relative to an instance would fall through to unreadable and
    report UNKNOWN -- which is why `ok` is carried at all.
    """
    env = os.environ.get("KIPI_SKEL")
    if env:
        return os.path.join(env, "instance-registry.json")
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.realpath(os.path.join(here, "..", "..", "..", "instance-registry.json"))
