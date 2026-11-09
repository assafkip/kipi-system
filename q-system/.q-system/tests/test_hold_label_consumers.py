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

A CONSUMER THAT STOPS IS NOT AN EXIT. Every `*_CAP` constant in a consumer's source
is classified in its row as per-ticket (it can strand the ticket, so it names what
takes it out next) or not (a batch bound). PR #666 round 1 major 2: needs-scope read
as covered while linear-dor-drafter.py:1182 keeps the label ON at REDRAFT_CAP.

RED FIRST. On main hold-label-consumers.json does not exist, so no label maps.
The negative self-tests run the same checker on fixture sources that add a refusal
(top level, nested one block deep, and behind `not helper(i)`), drop a consumer's
literal, name an uninstalled job, grow `missing`, and cap a consumer without saying
what happens at the cap.
"""
from __future__ import annotations

import ast
import importlib.util
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

# The labels whose consumer gives up after a per-ticket cap and leaves the hold on, so
# the row names a TICKET rather than the next consumer. Same ratchet as MISSING_CEILING
# and for the same reason, one rung weaker than `missing`: a consumer exists and works
# for the first N attempts. Not intersected with origin/main's copy the way `missing`
# is -- origin has no `caps` at all, so an intersection would empty the ceiling and the
# census would go red on its own population.
CAP_GAP_CEILING = frozenset({"needs-scope"})

# A per-ticket bound in a consumer's source, at module level. The name is what the row
# classifies, so a cap that is renamed or removed fails the registry rather than
# silently losing its classification.
CAP_RE = re.compile(r"^([A-Z][A-Z0-9_]*CAP)\s*=\s*\d+", re.M)


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


def _labels_under(node, consts: dict, funcs: dict, sign: int, seen: frozenset):
    """(label, polarity) for every label test reachable from `node`.

    `sign` carries the polarity of the surrounding refusal. It starts at +1 (the
    refusal fires when the condition is true) and FLIPS under `not`, because
    `if not has_owner(i): return False` holds the ticket when the label is ABSENT.
    A call to a module function is followed with the sign it was reached under, so
    a refusal written as `not helper(i)` is counted (PR #666 round 1, major 1).
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield from _labels_under(node.operand, consts, funcs, -sign, seen)
        return
    if (isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.comparators[0], ast.Name) and node.comparators[0].id == "labels"):
        left = node.left
        value = (left.value if isinstance(left, ast.Constant) and isinstance(left.value, str)
                 else consts.get(left.id) if isinstance(left, ast.Name) else None)
        if value is not None:
            holds_when_present = isinstance(node.ops[0], ast.In)
            if sign < 0:
                holds_when_present = not holds_when_present
            yield value, "present" if holds_when_present else "absent"
        return
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in funcs and node.func.id not in seen):
        for stmt in funcs[node.func.id].body:
            yield from _labels_under(stmt, consts, funcs, sign, seen | {node.func.id})
        return
    for child in ast.iter_child_nodes(node):
        yield from _labels_under(child, consts, funcs, sign, seen)


def _is_refusal(node) -> bool:
    return (isinstance(node, ast.If) and bool(node.body)
            and isinstance(node.body[0], ast.Return)
            and isinstance(node.body[0].value, ast.Constant)
            and node.body[0].value.value is False)


def refused_labels(src: str) -> dict:
    """label -> polarity, for every `if <cond>: return False` in ready(), AT ANY DEPTH.

    PR #666 round 1, major 1: this read only the top level of ready()'s body, so a
    refusal nested one block deeper landed with no registry row and CI stayed green.
    ast.walk reaches every nested If; _labels_under follows helper calls and `not`.
    """
    tree = ast.parse(src)
    consts = _str_constants(tree)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    out = {}
    for node in ast.walk(funcs["ready"]):
        if not _is_refusal(node):
            continue
        for label, polarity in _labels_under(node.test, consts, funcs, 1, frozenset()):
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

def cap_problems(label: str, consumer: dict, src: str) -> tuple:
    """(problems, strands_the_ticket) for one consumer's caps.

    Every `*_CAP` constant the source defines is classified in the row, both
    directions, so a new cap landing in a consumer fails CI until somebody says
    whether reaching it strands the ticket.
    """
    out = []
    in_src = set(CAP_RE.findall(src))
    declared = consumer.get("caps") or {}
    for name in sorted(in_src - set(declared)):
        out.append(f"{label}: {consumer.get('path')} caps {name} and the row does not say "
                   f"whether reaching it strands the ticket")
    for name in sorted(set(declared) - in_src):
        out.append(f"{label}: row classifies cap {name}, which {consumer.get('path')} "
                   f"no longer defines")
    strands = False
    for name in sorted(set(declared) & in_src):
        c = declared[name] or {}
        if c.get("per_ticket"):
            ticket = ((c.get("after_cap") or {}).get("ticket") or "")
            if not re.fullmatch(r"ASK-\d+", ticket):
                out.append(f"{label}: {name} strands the ticket and its after_cap names "
                           f"no ticket that builds the next consumer")
            else:
                strands = True
        elif not c.get("what"):
            out.append(f"{label}: {name} is declared not per-ticket with no reason")
    return out, strands


def problems(registry: dict, refused: dict, templates: dict, read, missing_ceiling,
             outside_allowed=OUTSIDE_ALLOWED, cap_gap_ceiling=CAP_GAP_CEILING) -> list:
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

    missing, cap_gaps = set(), set()
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
        cap_out, strands = cap_problems(label, c, src)
        out.extend(cap_out)
        if strands:
            cap_gaps.add(label)
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
    for label in sorted(cap_gaps - set(cap_gap_ceiling)):
        out.append(f"{label}: its consumer stops at a per-ticket cap and the ticket is "
                   f"stranded there; the capped set may only shrink")
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


def run_fixture(registry=None, src=FIXTURE_READY, templates=None, files=None,
                ceiling=frozenset(), cap_gap_ceiling=frozenset()):
    return problems(registry or fixture_registry(), refused_labels(src),
                    FIXTURE_TEMPLATES if templates is None else templates,
                    (files or FIXTURE_FILES).get, ceiling, FIXTURE_OUTSIDE_ALLOWED,
                    cap_gap_ceiling=cap_gap_ceiling)


def test_fixture_baseline_is_green():
    assert refused_labels(FIXTURE_READY) == {"owner:sana": "absent", "needs-scope": "present",
                                             "parked": "present"}
    assert run_fixture() == []


def test_a_new_refusal_with_no_row_goes_red():
    src = FIXTURE_READY.replace("    return True", '    if "hold:new" in labels: return False\n    return True')
    assert any("hold:new" in p and "no row" in p for p in run_fixture(src=src))


# --- round 1, major 1: the census was blind one block deep and through `not` ----

NESTED_READY = FIXTURE_READY.replace(
    "    return True",
    '    if i.get("x"):\n        if "hold:nested" in labels: return False\n    return True')

NOT_HELPER_READY = '''
PARK_LABEL = "parked"
def expired_park(i):
    labels = set()
    return PARK_LABEL in labels and True
def has_owner(i):
    labels = set()
    return "hold:viahelper" in labels
def ready(i):
    labels = set()
    if "owner:sana" not in labels: return False
    if "needs-scope" in labels: return False
    if expired_park(i): return False
    if not has_owner(i): return False
    return True
'''


def test_a_refusal_nested_one_block_deep_goes_red():
    """Observed red before the fix: the census returned only the three top-level
    labels and problems() came back []."""
    assert refused_labels(NESTED_READY).get("hold:nested") == "present"
    assert any("hold:nested" in p and "no row" in p for p in run_fixture(src=NESTED_READY))


def test_a_refusal_through_not_helper_goes_red():
    """Same red. `not` INVERTS the polarity too: refusing when the helper is false
    means the label holds the ticket by being ABSENT, so a row claiming `present`
    is wrong in the other direction."""
    assert refused_labels(NOT_HELPER_READY).get("hold:viahelper") == "absent"
    assert any("hold:viahelper" in p and "no row" in p for p in run_fixture(src=NOT_HELPER_READY))


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


# --- round 1, major 2: a consumer that stops after N attempts ------------------
# `every-terminal-state-needs-a-named-next-actor` (q-system/lessons, 2026-11-07):
# go cap by cap and ask what reads the outcome; a consumer must be code, never a
# label or an alert. linear-dor-drafter.py:1182-1193 keeps needs-scope ON at
# REDRAFT_CAP deliberately, so the row read as covered while the ticket was stranded.

CAPPED_FILES = dict(FIXTURE_FILES,
                    **{"scripts/drafter.py": 'REDRAFT_CAP = 3\nX = "needs-scope"\n'})


def _capped_registry(caps):
    reg = fixture_registry()
    reg["labels"]["needs-scope"]["consumer"]["caps"] = caps
    return reg


def test_an_unclassified_cap_in_a_consumer_goes_red():
    """Observed red before the fix: problems() was [] on a consumer that caps."""
    assert any("REDRAFT_CAP" in p and "needs-scope" in p
               for p in run_fixture(files=CAPPED_FILES))


def test_a_per_ticket_cap_with_no_after_cap_goes_red():
    reg = _capped_registry({"REDRAFT_CAP": {"per_ticket": True}})
    assert any("after_cap" in p for p in run_fixture(registry=reg, files=CAPPED_FILES))


def test_a_per_ticket_cap_past_the_ceiling_goes_red():
    reg = _capped_registry({"REDRAFT_CAP": {"per_ticket": True,
                                            "after_cap": {"ticket": "ASK-9", "what": "x"}}})
    assert any("stranded" in p and "may only shrink" in p
               for p in run_fixture(registry=reg, files=CAPPED_FILES))
    assert run_fixture(registry=reg, files=CAPPED_FILES,
                       cap_gap_ceiling=frozenset({"needs-scope"})) == []


def test_a_cap_classified_but_gone_from_the_source_goes_red():
    reg = _capped_registry({"GONE_CAP": {"per_ticket": False, "what": "batch size"}})
    assert any("GONE_CAP" in p and "no longer" in p
               for p in run_fixture(registry=reg, files=CAPPED_FILES))


def test_a_cap_declared_not_per_ticket_needs_a_reason():
    reg = _capped_registry({"REDRAFT_CAP": {"per_ticket": False}})
    assert any("not per-ticket" in p for p in run_fixture(registry=reg, files=CAPPED_FILES))


def test_the_live_needs_scope_row_owns_its_redraft_cap():
    """The one real capped consumer: its row says the cap strands the ticket and
    names the ticket that builds the exit (ASK-4092)."""
    caps = json.loads(REGISTRY.read_text())["labels"]["needs-scope"]["consumer"]["caps"]
    assert caps["REDRAFT_CAP"]["per_ticket"] is True
    assert re.fullmatch(r"ASK-\d+", caps["REDRAFT_CAP"]["after_cap"]["ticket"])
    assert "needs-scope" in CAP_GAP_CEILING


# --- the suite's own wiring ----------------------------------------------------

def _change_size():
    spec = importlib.util.spec_from_file_location(
        "change_size", REPO / "q-system/.q-system/scripts/change-size.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_suite_is_declared_to_run_on_every_pr():
    """PR #666 round 2, major: verify.sh --changed skips tests/ unless a file there
    changes, so a new refusal in linear-worker.sh went unchecked. The capability
    gate's always-run floor is `scans_the_tree(text) AND no covers` -- both halves,
    so the scanner property is asserted here too: strip the tree scan out of this
    file and it would fall off the floor silently."""
    frag = QDIR / "capability" / "expected_tests" / "q-system__.q-system__tests__test_hold_label_consumers.py.json"
    d = json.loads(frag.read_text())
    assert d["path"] == "q-system/.q-system/tests/test_hold_label_consumers.py"
    assert d["runner"] == "pytest" and "covers" not in d
    assert _change_size().scans_the_tree(pathlib.Path(__file__).read_text())
