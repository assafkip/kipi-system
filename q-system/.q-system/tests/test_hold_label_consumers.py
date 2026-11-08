#!/usr/bin/env python3
"""Every hold label maps to an installed consumer (ASK-4011).

Founder, 2026-11-08: "We cannot have these things get stuck again on rules that
are not being enforced and then tickets don't get done because they're waiting for
someone that doesn't exist."

THE CENSUS IS TAKEN BY CODE. The labels come from linear-worker.sh ready() itself,
parsed with ast, never from a list typed here: a list typed here agrees on the day
it is written and then a new refusal lands beside it and passes. Each label must
have a row in hold-label-consumers.json, and each row must name:
  * an in-repo script whose source carries the label literal (it can select on it),
    run by a committed com.kipi template that is not retired and whose
    ProgramArguments reach the script, directly or through one `./kipi <verb>` hop;
  * or code in another repo, named with repo, file, marker, job and owner;
  * or a `missing` entry with the ticket that builds the consumer. That set may only
    shrink: MISSING_CEILING below, and origin/main's copy when git can read it.

RED FIRST. On main hold-label-consumers.json does not exist, so no label maps.
The negative self-tests run the same checker on fixture sources that add a
refusal, drop a consumer's literal, name an uninstalled job, and grow `missing`.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
REPO = QDIR.parents[1]
REGISTRY = QDIR / "hold-label-consumers.json"
WORKER = QDIR / "scripts" / "linear-worker.sh"
REGISTRY_REL = "q-system/.q-system/hold-label-consumers.json"

# The labels with no consumer at the time each was written down. Remove one when its
# consumer ships. Adding one here is a decision a reviewer sees, never a drift.
MISSING_CEILING = frozenset({"owner:assaf", "blocked:capability", "triage:held"})

# The labels allowed an `outside_consumer` row. This test cannot verify another repo's
# code, so five non-empty strings would otherwise turn a `missing` row green and read
# as the missing set shrinking (PR #666 review, minor). Adding a label here is an edit
# to this file, so the reviewer reads the claim next to the row that makes it.
# Empty since #663 (ASK-4031): ready() no longer refuses an expired park, so `parked`
# left the registry with it, and nothing else names an outside consumer.
OUTSIDE_ALLOWED = frozenset()


# --- the census ---------------------------------------------------------------

def ready_source(worker_text: str) -> str:
    """The python heredoc in linear-worker.sh that defines ready()."""
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY\n", worker_text, flags=re.S)
    hits = [b for b in blocks if "\ndef ready(" in b]
    assert len(hits) == 1, f"expected one heredoc defining ready(), found {len(hits)}"
    return hits[0]


def _str_constants(tree: ast.Module) -> dict:
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def _label_compares(node, consts: dict):
    """(label, polarity) for every `<str> in labels` / `<str> not in labels` under node."""
    for n in ast.walk(node):
        if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.comparators[0], ast.Name) and n.comparators[0].id == "labels"):
            continue
        left = n.left
        value = (left.value if isinstance(left, ast.Constant) and isinstance(left.value, str)
                 else consts.get(left.id) if isinstance(left, ast.Name) else None)
        if value is None:
            continue
        if isinstance(n.ops[0], ast.In):
            yield value, "present"
        elif isinstance(n.ops[0], ast.NotIn):
            yield value, "absent"


def refused_labels(src: str) -> dict:
    """label -> polarity, for every `if <cond>: return False` in ready() that reads a label.

    A condition that calls a module function (expired_park) is followed one level,
    because that is where the parked label lives.
    """
    tree = ast.parse(src)
    consts = _str_constants(tree)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    out = {}
    for stmt in funcs["ready"].body:
        if not (isinstance(stmt, ast.If) and stmt.body and isinstance(stmt.body[0], ast.Return)
                and isinstance(stmt.body[0].value, ast.Constant) and stmt.body[0].value.value is False):
            continue
        targets = [stmt.test]
        if isinstance(stmt.test, ast.Call) and isinstance(stmt.test.func, ast.Name) \
                and stmt.test.func.id in funcs:
            targets.append(funcs[stmt.test.func.id])
        for t in targets:
            for label, polarity in _label_compares(t, consts):
                out[label] = polarity
    return out


# --- the jobs the fleet installs -----------------------------------------------

def committed_templates(repo: pathlib.Path) -> dict:
    """label -> template text, from the same set install-plist.sh enumerates."""
    try:
        rels = subprocess.run(["git", "-C", str(repo), "ls-files", "--",
                               "*/com.kipi.*.plist", "com.kipi.*.plist"],
                              capture_output=True, text=True, check=True).stdout.split()
        paths = [repo / r for r in rels]
    except (OSError, subprocess.CalledProcessError):
        paths = list((repo / "q-system/.q-system/scripts").glob("com.kipi.*.plist"))
    return {p.stem: p.read_text() for p in paths if p.is_file()}


def kipi_case(kipi_text: str, verb: str) -> str:
    m = re.search(rf"^\s*{re.escape(verb)}\)\s*$(.*?)^\s*;;", kipi_text, flags=re.M | re.S)
    return m.group(1) if m else ""


# --- the checker ----------------------------------------------------------------

def problems(registry: dict, refused: dict, templates: dict, read, missing_ceiling,
             outside_allowed=OUTSIDE_ALLOWED) -> list:
    """Every reason the registry fails its contract. [] means it holds.

    `read(rel)` returns a repo file's text or None; injected so the self-tests can
    run the same checker over fixtures.
    """
    out = []
    rows = registry.get("labels") or {}
    lanes = registry.get("lane_holds") or {}
    want = set(refused) | set(lanes)
    for label in sorted(want - set(rows)):
        out.append(f"{label}: refused but has no row (nothing named takes it out)")
    for label in sorted(set(rows) - want):
        out.append(f"{label}: row for a label nothing refuses (stale)")
    for label, polarity in sorted(refused.items()):
        row = rows.get(label) or {}
        if row and row.get("refused_when") != polarity:
            out.append(f"{label}: ready() refuses it when {polarity}, row says {row.get('refused_when')}")
    for label, lane in sorted(lanes.items()):
        text = read(lane.get("path", "")) or ""
        if lane.get("marker", "\0") not in text or f'"{label}"' not in text:
            out.append(f"{label}: lane hold not found in {lane.get('path')}")

    missing = set()
    for label, row in sorted(rows.items()):
        kinds = [k for k in ("consumer", "outside_consumer", "missing") if k in row]
        if len(kinds) != 1:
            out.append(f"{label}: needs exactly one of consumer, outside_consumer, missing; has {kinds}")
            continue
        kind = kinds[0]
        if kind == "missing":
            missing.add(label)
            if not re.fullmatch(r"ASK-\d+", (row["missing"].get("ticket") or "")):
                out.append(f"{label}: missing row names no ticket")
            continue
        if kind == "outside_consumer":
            oc = row["outside_consumer"]
            empty = [f for f in ("repo", "path", "marker", "job", "owner") if not oc.get(f)]
            if empty:
                out.append(f"{label}: outside consumer lacks {empty}")
            if label not in outside_allowed:
                out.append(f"{label}: an outside consumer this test cannot verify; add it to "
                           f"OUTSIDE_ALLOWED in the same PR so the claim is reviewed")
            continue
        c = row["consumer"]
        if c.get("path") and c.get("path") == row.get("refused_by"):
            # PR #666 round 2: naming the script that refuses the label as its consumer
            # turned a missing row green with nothing built. The refuser is never the exit.
            out.append(f"{label}: consumer {c['path']} is the script that refuses it")
            continue
        src = read(c.get("path", ""))
        if src is None:
            out.append(f"{label}: consumer {c.get('path')} does not exist")
            continue
        if f'"{label}"' not in src:
            out.append(f"{label}: {c.get('path')} carries no \"{label}\" literal, so it cannot select on it")
        job = c.get("job", "")
        tmpl = templates.get(job)
        if tmpl is None:
            out.append(f"{label}: job {job} is not a committed com.kipi template")
            continue
        if "kipi-retired:" in tmpl:
            out.append(f"{label}: job {job} is retired")
        script = pathlib.Path(c["path"]).name
        verb = c.get("via")
        if verb:
            if f"kipi {verb}" not in tmpl or script not in kipi_case(read("kipi") or "", verb):
                out.append(f"{label}: {job} does not reach {script} through ./kipi {verb}")
        elif script not in tmpl:
            out.append(f"{label}: {job} ProgramArguments do not run {script}")
    for label in sorted(missing - set(missing_ceiling)):
        out.append(f"{label}: added to missing; the missing set may only shrink")
    return out


def _read_repo(rel: str):
    p = REPO / rel
    return p.read_text() if rel and p.is_file() else None


def _origin_missing():
    """The missing set on origin/main, or None when git cannot say."""
    try:
        text = subprocess.run(["git", "-C", str(REPO), "show", f"origin/main:{REGISTRY_REL}"],
                              capture_output=True, text=True, check=True).stdout
        rows = json.loads(text).get("labels") or {}
        return {k for k, v in rows.items() if "missing" in v}
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


# --- the real tree ----------------------------------------------------------------

def test_the_census_finds_the_labels_ready_refuses():
    refused = refused_labels(ready_source(WORKER.read_text()))
    # A floor, not the list: an empty census would pass every check below.
    assert {"needs-scope", "owner:sana"} <= set(refused), refused


def test_every_hold_label_maps_to_a_consumer():
    assert REGISTRY.exists(), f"{REGISTRY_REL} does not exist: no hold label maps to a consumer"
    registry = json.loads(REGISTRY.read_text())
    refused = refused_labels(ready_source(WORKER.read_text()))
    ceiling = MISSING_CEILING
    origin = _origin_missing()
    if origin is not None:
        ceiling = ceiling & origin
    assert problems(registry, refused, committed_templates(REPO), _read_repo, ceiling) == []


def test_the_registry_agrees_with_terminal_states():
    """Two registries name the same consumer job, or one of them is wrong."""
    registry = json.loads(REGISTRY.read_text())
    states = {r["id"]: r for r in json.loads((QDIR / "terminal-states.json").read_text())["states"]}
    for label, row in registry["labels"].items():
        sid = row.get("terminal_state")
        if not sid:
            continue
        lc = (states[sid].get("liveness_check") or {})
        assert lc.get("label") == row["consumer"]["job"], (label, sid, lc)


# --- the negative self-tests --------------------------------------------------

FIXTURE_READY = '''
PARK_LABEL = "parked"
def expired_park(i):
    labels = set()
    return PARK_LABEL in labels and True
def ready(i):
    labels = set()
    if "owner:sana" not in labels: return False
    if "needs-scope" in labels: return False
    if expired_park(i): return False
    return True
'''
FIXTURE_FILES = {
    "scripts/drafter.py": 'X = "needs-scope"\n',
    "scripts/sweep.py": 'X = "owner:sana"\n',
    "kipi": "  dor)\n    python3 scripts/drafter.py\n    ;;\n",
}
FIXTURE_TEMPLATES = {"com.kipi.dor": "<string>./kipi dor</string>",
                     "com.kipi.sweep": "<string>python3 scripts/sweep.py</string>"}


def fixture_registry():
    return {"labels": {
        "owner:sana": {"refused_when": "absent",
                       "consumer": {"path": "scripts/sweep.py", "job": "com.kipi.sweep"}},
        "needs-scope": {"refused_when": "present",
                        "consumer": {"path": "scripts/drafter.py", "job": "com.kipi.dor", "via": "dor"}},
        "parked": {"refused_when": "present",
                   "outside_consumer": {"repo": "r", "path": "p", "marker": "m", "job": "j", "owner": "o"}},
    }}


# The fixture keeps its own outside row (`parked`), so it carries its own allowlist and
# does not lean on the live one, which is empty since #663.
FIXTURE_OUTSIDE_ALLOWED = frozenset({"parked"})


def run_fixture(registry=None, src=FIXTURE_READY, templates=None, files=None, ceiling=frozenset()):
    return problems(registry or fixture_registry(), refused_labels(src),
                    FIXTURE_TEMPLATES if templates is None else templates,
                    (files or FIXTURE_FILES).get, ceiling, FIXTURE_OUTSIDE_ALLOWED)


def test_fixture_baseline_is_green():
    assert refused_labels(FIXTURE_READY) == {"owner:sana": "absent", "needs-scope": "present",
                                             "parked": "present"}
    assert run_fixture() == []


def test_a_new_refusal_with_no_row_goes_red():
    src = FIXTURE_READY.replace("    return True", '    if "hold:new" in labels: return False\n    return True')
    assert any("hold:new" in p and "no row" in p for p in run_fixture(src=src))


def test_a_consumer_without_the_label_literal_goes_red():
    files = dict(FIXTURE_FILES, **{"scripts/drafter.py": "X = 1\n"})
    assert any("needs-scope" in p and "literal" in p for p in run_fixture(files=files))


def test_an_uninstalled_job_goes_red():
    templates = {"com.kipi.sweep": FIXTURE_TEMPLATES["com.kipi.sweep"]}
    assert any("com.kipi.dor" in p for p in run_fixture(templates=templates))


def test_a_retired_job_goes_red():
    templates = dict(FIXTURE_TEMPLATES, **{"com.kipi.sweep": "kipi-retired: 2026 python3 scripts/sweep.py"})
    assert any("retired" in p for p in run_fixture(templates=templates))


def test_a_job_that_does_not_run_the_consumer_goes_red():
    templates = dict(FIXTURE_TEMPLATES, **{"com.kipi.sweep": "<string>python3 other.py</string>"})
    assert any("do not run sweep.py" in p for p in run_fixture(templates=templates))


def test_a_via_hop_that_does_not_reach_the_consumer_goes_red():
    files = dict(FIXTURE_FILES, kipi="  dor)\n    python3 scripts/other.py\n    ;;\n")
    assert any("through ./kipi dor" in p for p in run_fixture(files=files))


def test_growing_missing_goes_red():
    reg = fixture_registry()
    reg["labels"]["needs-scope"] = {"refused_when": "present", "missing": {"ticket": "ASK-1"}}
    assert any("may only shrink" in p for p in run_fixture(registry=reg))
    assert run_fixture(registry=reg, ceiling=frozenset({"needs-scope"})) == []


def test_wrong_polarity_goes_red():
    reg = fixture_registry()
    reg["labels"]["owner:sana"]["refused_when"] = "present"
    assert any("refuses it when absent" in p for p in run_fixture(registry=reg))


def test_a_row_with_two_dispositions_goes_red():
    reg = fixture_registry()
    reg["labels"]["parked"]["missing"] = {"ticket": "ASK-2"}
    assert any("exactly one" in p for p in run_fixture(registry=reg))


def test_an_unlisted_outside_consumer_is_red():
    """PR #666 review, minor: five arbitrary strings turned a missing row green. On the
    fixture, never the live registry, so it holds when a real row changes (round 2)."""
    reg = fixture_registry()
    reg["labels"]["owner:sana"] = {"refused_when": "absent", "outside_consumer": {
        "repo": "nowhere", "path": "nothing", "marker": "none", "job": "a desk", "owner": "x"}}
    assert any("owner:sana: an outside consumer" in p for p in run_fixture(registry=reg))


def test_the_refuser_is_never_its_own_consumer():
    """PR #666 round 2, minor: the worker that refuses a label named as its consumer."""
    reg = fixture_registry()
    reg["labels"]["needs-scope"] = {"refused_when": "present", "refused_by": "scripts/worker.sh",
                                    "consumer": {"path": "scripts/worker.sh", "job": "com.kipi.dor"}}
    assert any("is the script that refuses it" in p for p in run_fixture(registry=reg))


def test_the_suite_is_declared_to_run_on_every_pr():
    """PR #666 round 2, major: verify.sh --changed skips tests/ unless a file there
    changes, so a new refusal in linear-worker.sh went unchecked. Declared with no
    `covers`, it sits on the capability gate's always-run floor."""
    frag = QDIR / "capability" / "expected_tests" / "q-system__.q-system__tests__test_hold_label_consumers.py.json"
    d = json.loads(frag.read_text())
    assert d["path"] == "q-system/.q-system/tests/test_hold_label_consumers.py"
    assert d["runner"] == "pytest" and "covers" not in d
