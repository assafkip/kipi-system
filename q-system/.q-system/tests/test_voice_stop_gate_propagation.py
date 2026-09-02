"""No registered instance may define a voice-stop-gate function the skeleton lacks.

WHY THIS EXISTS (ASK-1197, 2026-09-02). `q-system/` is an rsync --delete fanout
target, so `voice-stop-gate.py` is one file with 25 homes and the skeleton copy is
the one that survives an update. A function that exists only in an instance is a
capability the next `kipi update` DELETES. That is the voicekit class (19
instances, 2026-08-07) and it is what happened here: `enforce_route_receipt` and
its four helpers shipped into one instance and into no skeleton.

WHY THE ASSERTION IS ONE-DIRECTIONAL, and this is the load-bearing design call.
Measured across all 25 registered instances on 2026-09-02, before the port:

    24 of 24 instances that carry the file  lack the SAME 6 skeleton functions
     1 of 24 instances                      defines 5 the skeleton lacks

Those two numbers are not the same finding. The 24 are fanout LAG: `kipi update`
has not run since PR #290 and #291 merged, and when it does it ADDS those six and
deletes nothing. The 1 is fanout LOSS: an update deletes working code. Only the
second is a hazard, and only the second is asserted.

Blocking on the lag direction instead would put this gate red for 24 instances the
moment ANY skeleton change lands, which is every skeleton change. A gate that its
own population cannot satisfy is a gate that gets switched off, and a gate that is
off protects nothing -- the same reasoning that grandfathered plan-lint and that
keeps the channel registry opt-in. So the lag is COUNTED and PRINTED on every run,
never asserted on. If it grows without an update, that number says so.

WHY A FUNCTION SET AND NOT A DIFF. These copies legitimately differ in whitespace,
comment wording and constant ordering, so a byte comparison is noisy enough that a
reader learns to ignore it. What a reader actually cares about is whether a
CAPABILITY is present.

WHY `ast` AND NOT A REGEX over `^def `. A regex counts the word `def` inside a
docstring or a commented-out block, so it can report a function that is not defined
and miss one that is. `ast` answers what importing the module actually binds. It
also means a MOVED function is not drift, which is correct: the fanout copies the
whole file, so position carries nothing.

WHAT THIS DOES NOT PROVE. It does not run a fanout and it does not prove two copies
BEHAVE alike -- two functions can share a name and diverge completely inside. This
is a floor: it catches a whole capability present in one copy and absent from the
skeleton. Read the green narrowly.

Its counterpart on the instance side is `consulting/automation/
test_voice_stop_gate_propagation.py`, which asserts BOTH directions against one
instance. The two are deliberately not the same check: that one guards a single
repo against its own skeleton, this one guards the skeleton against all 25.
"""
import ast
import json
import os
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
GATE_REL = pathlib.Path("q-system") / ".q-system" / "scripts" / "voice-stop-gate.py"
REGISTRY = REPO / "instance-registry.json"

#: Names an instance is allowed to define that the skeleton does not.
#: name -> the reason the fanout is allowed to DELETE it.
#:
#: EMPTY ON PURPOSE. An entry here is a written promise that losing that function
#: on the next `kipi update` is fine. If you cannot write that sentence about a
#: name, port it upstream instead. Every difference measured on 2026-09-02 was
#: drift to be resolved by porting, so recording any of it here would have turned a
#: live hazard into a permanent excuse.
EXEMPT: "dict[str, str]" = {}


#: The crude fallback for a file `ast` refuses. Column 0 only, so a nested `def`
#: is not counted -- matching what `_top_level_functions` means by top level.
_DEF_RE = re.compile(r"(?m)^(?:async\s+)?def\s+(\w+)\s*\(")


def _top_level_functions(source, filename):
    """Names bound by a top-level `def`.

    Nested helpers are excluded: the fanout cannot delete one independently of its
    parent, so a nested name carries no information this check can act on.
    """
    tree = ast.parse(source, filename=str(filename))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _functions_at(path):
    return _top_level_functions(path.read_text(encoding="utf-8"), path)


def _registered_instances():
    # NOT a skip when the registry is missing. It is a file in this repo, so its
    # absence is a broken floor rather than an unavailable machine fact.
    assert REGISTRY.is_file(), f"instance registry missing at {REGISTRY}"
    return json.loads(REGISTRY.read_text(encoding="utf-8")).get("instances", [])


def test_no_instance_defines_a_function_the_skeleton_lacks(capsys):
    """The hazard direction. A name here is code the next fanout deletes."""
    skeleton = _functions_at(REPO / GATE_REL)
    assert skeleton, "parsed no functions from the skeleton gate; the parser is broken"

    loss = {}       # instance name -> names the fanout would delete
    lag = {}        # instance name -> count of skeleton names it has not received
    absent = []     # instances that do not carry this file at all
    unparseable = []

    for entry in _registered_instances():
        name = entry.get("name", "?")
        path = pathlib.Path(entry.get("path", "")) / GATE_REL
        if not path.is_file():
            absent.append(name)
            continue
        try:
            found = _functions_at(path)
        except (SyntaxError, OSError) as exc:
            # A FALLBACK, not a skip (Codex minor, ASK-1197 round 1). Skipping here
            # meant an instance that adds a unique function and then acquires a
            # syntax error drops out of `loss` entirely and the gate goes green over
            # a live hazard -- the exact silent-absence shape this file exists to
            # catch, reproduced inside it.
            #
            # So a file `ast` cannot parse is scanned with the crude regex instead.
            # The regex OVER-reports (it counts `def` inside a docstring or a
            # commented-out block, which is why `ast` is used everywhere else), and
            # over-reporting is the safe direction for a hazard check: the cost is a
            # false name in the failure message on a file that is already broken.
            unparseable.append(f"{name}: {exc}")
            try:
                found = set(_DEF_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                # Cannot even read it. Nothing to assert on either way; the line
                # above is the whole report.
                continue
        extra = sorted((found - skeleton) - set(EXEMPT))
        if extra:
            loss[name] = extra
        behind = sorted(skeleton - found)
        if behind:
            lag[name] = behind

    # Printed on every run, asserted on never. See the module docstring.
    print(f"voice-stop-gate propagation: {len(loss)} instance(s) carry code the "
          f"fanout would DELETE; {len(lag)} lag the skeleton (an update ADDS those); "
          f"{len(absent)} do not carry the file.")
    if lag:
        worst = max(len(v) for v in lag.values())
        print(f"  lag: up to {worst} function(s) behind, e.g. "
              f"{sorted(lag.items())[0][0]}: {sorted(lag.items())[0][1]}")
    if unparseable:
        print("  could not parse: " + "; ".join(unparseable))

    assert not loss, (
        "voice-stop-gate.py defines functions in an instance that the SKELETON does "
        "not have. The next `kipi update` rsync --delete overwrites the instance "
        "copy with the skeleton one, so this code is deleted on the next update.\n"
        f"  skeleton: {REPO / GATE_REL}\n"
        + "".join(f"  {n}: {v}\n" for n, v in sorted(loss.items()))
        + "Port these upstream into the skeleton copy. Do NOT add an EXEMPT entry "
          "unless losing the function on the next fanout is genuinely fine."
    )


def test_the_regex_fallback_sees_a_file_ast_refuses():
    """The instrument behind the unparseable branch (Codex minor, round 1).

    A skipped instance drops out of `loss` entirely, so an instance that adds a
    unique function and then acquires a syntax error goes green over a live
    hazard. The fallback must still find the name in a file `ast` will not parse.
    """
    broken = (
        "def a_real_top_level_def():\n"
        "    return 1\n"
        "def another_one(x):\n"
        "    if x = 1:\n"          # the syntax error
        "        pass\n"
        "    def a_nested_one():\n"
        "        pass\n"
    )
    with pytest.raises(SyntaxError):
        _top_level_functions(broken, "<broken>")
    found = set(_DEF_RE.findall(broken))
    assert "a_real_top_level_def" in found and "another_one" in found, found
    assert "a_nested_one" not in found, (
        "the fallback counted an INDENTED def. It must mean the same thing by "
        f"'top level' as the ast walk does, or the two disagree. {found}")


def test_every_exemption_carries_a_reason():
    """An exemption with no reason is a silent permanent hole.

    Guards the escape hatch, not the gate. Reads only this file, so it needs no
    instance checkouts present.
    """
    for name, reason in EXEMPT.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"EXEMPT[{name!r}] has no reason. Name why the fanout is allowed to "
            f"delete this function, or remove the entry and port it upstream."
        )


def test_the_comparison_can_actually_fail():
    """Negative self-test: prove the comparison distinguishes two different sets.

    Without it, a bug making `_top_level_functions` return an empty set for every
    input would make the real test pass unconditionally and read green forever --
    which is the exact failure class this file exists to prevent, so reproducing it
    inside the file would be a poor result.
    """
    real = _functions_at(REPO / GATE_REL)
    assert real, "parsed no top-level functions at all; the parser, not the gate, is broken"

    # An instance that added a name the skeleton lacks must be caught.
    invented = real | {"a_function_no_skeleton_has"}
    assert sorted(invented - real) == ["a_function_no_skeleton_has"]

    # And the parser must not be counting the word `def` in prose. This source
    # defines exactly one function; the other two `def`s are a docstring and a
    # comment, and a regex over `^def ` reports three.
    decoy = (
        'def real_one():\n'
        '    """\n'
        'def not_a_function():\n'
        '    """\n'
        '    return 1\n'
        '# def also_not_a_function():\n'
    )
    assert _top_level_functions(decoy, "<decoy>") == {"real_one"}, (
        "the parser counted a `def` that is not a definition; it is a text scan, "
        "not an ast walk.")
