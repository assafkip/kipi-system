"""Every headless model call in the fleet is the metered wrapper or a NAMED exception.

why (ASK-2008, Step 2 of the ticket-flood plan). The per-bot usage ledger meters
what goes through `prompt_render.run_model`. A script that shells `claude -p`
on its own is invisible to it, so the Step 4 breaker (ASK-2010) cannot see what
it spends. This test is the measured blind spot: the inventory in
`q-system/.q-system/model-call-sites.json`, held against this tree AND every
registered instance checked out on this machine (the registry is the fleet's
own list of where its code runs; CI sees only this tree, the pre-push run here
sees the fleet).

THE LIST ONLY SHRINKS. A new direct call site fails until it goes through the
wrapper or gets a row (a review question, made in this file's diff). A row
whose file is here and no longer calls the model fails too, so the row leaves.
In an INSTANCE only its own paths are checked (everything outside `q-system/`
and `plugins/`), and those rows are stored as sha256(path)[:12]: the skeleton
sweep (validate-separation.py) refuses an instance's directory names in this
repo, which is right, and the failure message here prints the real path from
the tree being checked, so nothing is lost on the machine that matters: the shared trees are this skeleton's business and are checked
here, and an instance carrying an older copy of them is sync lag, which
`fleet-health-daily.py` already watches. Without that split a site wrapped in
the skeleton could never leave the list until every instance had synced (the
first cut of this test went red on 25 instances the moment revise.py was
wrapped). The detector and its blind spots are documented in
`plugins/kipi-core/voiceloop/call_sites.py`; this file owns only the inventory.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins" / "kipi-core"))
from voiceloop import call_sites as cs  # noqa: E402

SPEC_PATH = ROOT / "q-system" / ".q-system" / "model-call-sites.json"
SHARED_PREFIXES = ("q-system/", "plugins/")


def key(name: str) -> str:
    """An instance's section key. A hash, never the name: this repo is public
    and some instances are client engagements (the client-names commit hook
    refused the first cut of the JSON)."""
    return hashlib.sha256(name.encode()).hexdigest()[:12]


def spec() -> dict:
    return json.loads(SPEC_PATH.read_text())


def registered() -> list[tuple[str, Path]]:
    """(name, path) for every registry instance that is checked out here."""
    reg = json.loads((ROOT / "instance-registry.json").read_text())
    out = []
    for it in reg.get("instances", []):
        p = Path(it["path"])
        if it.get("has_git") and (p / ".git").exists():
            out.append((it["name"], p))
    return out


def local_only(sites: set) -> set:
    return {r for r in sites if not r.startswith(SHARED_PREFIXES)}


def instance_check(path: Path, rows: dict, wrappers) -> tuple[set, set]:
    """(new local sites, stale local rows), both as REAL paths, against hashed rows.

    A row whose hash matches no tracked file is an older copy of the tree and
    is neither new nor stale; one whose file is tracked but no longer calls
    the model is stale and has to leave.
    """
    sites = local_only(cs.call_sites(path) - set(wrappers))
    by_hash = {key(rel): rel for rel in cs.tracked(path) if not rel.startswith(SHARED_PREFIXES)}
    new = {s for s in sites if key(s) not in rows}
    stale = {by_hash[h] for h in rows if h in by_hash and by_hash[h] not in sites}
    return new, stale


def test_the_wrapper_is_a_call_site():
    # The detector must see the one site it exists to distinguish from the rest.
    assert set(spec()["wrapper"]) <= cs.call_sites(ROOT)


def test_this_tree_has_no_unlisted_model_call():
    s = spec()
    # shared rows propagate; skeleton rows are this repo's root files, which do
    # not (PR #413 round 1 minor 3: a root caller had nowhere to be listed).
    new, stale = cs.check(ROOT, {**s["shared"], **s.get("skeleton", {})}, s["wrapper"])
    assert not new, f"direct claude -p call with no row: {sorted(new)}"
    assert not stale, f"row whose file no longer calls the model (remove it): {sorted(stale)}"


@pytest.mark.parametrize("name,path", registered() or [("(no instances checked out here)", None)])
def test_each_registered_instance_has_no_unlisted_model_call(name, path):
    if path is None:
        pytest.skip("no registry instance is checked out on this machine (CI)")
    s = spec()
    new, stale = instance_check(path, s["instances"].get(key(name), {}), s["wrapper"])
    assert not new, f"{name}: direct claude -p call with no row: {sorted(new)}"
    assert not stale, f"{name}: row whose file no longer calls the model (remove it): {sorted(stale)}"


def test_every_instance_section_keys_a_registered_instance():
    reg_keys = {key(it["name"]) for it in json.loads((ROOT / "instance-registry.json").read_text())["instances"]}
    assert set(spec()["instances"]) <= reg_keys, "a section for an instance the registry does not know"


def test_shared_rows_live_in_the_shared_trees_and_instance_rows_outside_them():
    s = spec()
    for row in s["shared"]:
        assert row.startswith(SHARED_PREFIXES), row
    for row in s.get("skeleton", {}):
        assert not row.startswith(SHARED_PREFIXES), row
    for name, rows in s["instances"].items():
        for row in rows:
            assert re.fullmatch(r"[0-9a-f]{12}", row), (name, row)  # a hash, never a path


if __name__ == "__main__":
    # Print the candidate rows for every tree, in the JSON's shape, so a new row
    # is copied from here and never typed.
    s = spec()
    here = cs.call_sites(ROOT) - set(s["wrapper"])
    out = {"shared": sorted(r for r in here if r.startswith(SHARED_PREFIXES)),
           "skeleton": sorted(r for r in here if not r.startswith(SHARED_PREFIXES)),
           "instances": {}}
    for name, path in registered():
        local = sorted(r for r in cs.call_sites(path) - set(s["wrapper"])
                       if not r.startswith(SHARED_PREFIXES))
        if local:
            out["instances"][key(name)] = {key(r): r for r in local}
    print(json.dumps(out, indent=2))
