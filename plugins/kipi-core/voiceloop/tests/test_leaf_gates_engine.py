#!/usr/bin/env python3
"""The moved leaf gates, tested as ENGINE code rather than through an instance.

why this file exists (2026-09-05, package extraction slice 2). `opener_gate`,
`placeholder_gate` and `slop_shapes` already have thorough suites on the instance
side, and those suites now reach them through a re-export. That proves the shim
works. It does NOT prove the property the move exists for: that another instance,
with no deployment tree anywhere on disk, can import these gates and get the same
verdicts.

why no instance name appears in this file, not even inside a string. The first
version asserted against the deployment directory as a literal and the public
mirror's exporter refused the whole tree, correctly: this file ships to a public
repo, and a test that polices a private name by quoting it becomes the leak it
polices. `test_no_founder_data.py` solves the same problem by sitting on an
exclusion list; that list is a hole in the mirror and it stays small, so this file
builds its needle from parts instead of earning an entry.

The identity check that pairs with this one (shim and engine are the SAME object)
lives on the instance side, in `pipeline/tests/test_leaf_gate_shims.py`, because
only the instance is allowed to know its own path.
"""
import ast
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import assistant_gate, ending_gate  # noqa: E402
from voiceloop import opener_gate, placeholder_gate  # noqa: E402
from voiceloop import slop_shapes, source_shape, substance_gate  # noqa: E402

# Slice 2 moved the first three, slice 3 the next four. They are tested together
# because the property asserted here is the same for all of them and belongs to the
# TREE, not to any one module: a gate that quietly reaches back into a deployment
# passes every test on that deployment and fails on the first other machine.
GATES = (opener_gate, placeholder_gate, slop_shapes,
         substance_gate, ending_gate, assistant_gate, source_shape)

# Assembled, never written whole. The exporter greps this tree for the literal.
DEPLOYMENT_DIR = "q-" + "consult"


def _without_cli_block(tree):
    """Drop the `if __name__ == "__main__"` subtree before inspecting a module.

    why (2026-09-05): `substance_gate` ends in a CLI that does
    `with open(sys.argv[1])`. That is not a reach into a deployment, it is a
    caller naming its own file, and refusing it would delete a working entry
    point to satisfy a test. The property this file actually cares about is what
    the IMPORTED module does, so the CLI guard is excluded rather than the rule
    being weakened for every line in the file.
    """
    kept = []
    for node in tree.body:
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            continue
        kept.append(node)
    return ast.Module(body=kept, type_ignores=[])


class TestTheEngineStandsAlone:
    """No deployment tree on the path, no corpus on disk, still a working gate."""

    def test_every_gate_exposes_check(self):
        for gate in GATES:
            assert callable(gate.check), f"{gate.__name__} has no callable check"

    def test_no_gate_reaches_a_deployment_tree(self):
        """Asserted on CODE, not on prose.

        An earlier version failed `slop_shapes` for two comment lines citing the
        exemplar corpus as the provenance of its 0-of-103 measurement. Those are
        comments, and a comment recording where a number came from is the thing
        this repo wants more of. What must not exist is a live read.
        """
        for gate in GATES:
            with open(gate.__file__, encoding="utf-8") as handle:
                body = handle.read()
            assert DEPLOYMENT_DIR not in body, (
                f"{gate.__name__} names a deployment directory; it cannot ship")

            tree = _without_cli_block(ast.parse(body))
            names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
            calls = [n.func.id for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            assert "open" not in calls, (
                f"{gate.__name__} opens a file; a leaf gate reads its argument "
                f"and nothing else")
            assert "__file__" not in names, (
                f"{gate.__name__} resolves a path from __file__, which is how a "
                f"packaged module silently binds to whichever corpus sits beside it")

    def test_a_gate_verdict_is_a_list_of_reasons(self):
        """Contract every caller depends on: check() returns rows, never a bool."""
        for gate in GATES:
            out = gate.check("An ordinary sentence that names its own subject.")
            assert isinstance(out, list), (
                f"{gate.__name__}.check returned {type(out).__name__}, not a list")


class TestTheRulesStillBite:
    """Behaviour, not just structure.

    Added 2026-09-05 (slice 4b). The deployment's `test_slop_shapes.py` measures
    these shapes against the founder's real corpus and therefore cannot ship to the
    fleet, which has no such corpus. Dropping it from the mirror would have left the
    published rule with structural coverage only, so the part that can run anywhere
    is asserted here on synthetic text.
    """

    def test_a_templated_shape_is_caught(self):
        caught = slop_shapes.check(
            "It's not just a tool. It's a way of thinking about your work.")
        assert caught, "the not-just-a-X shape stopped being caught"

    def test_ordinary_prose_is_not_caught(self):
        """Negative control. A rule that fires on everything protects nothing."""
        assert slop_shapes.check(
            "Four teams fought the same operation and none of them knew.") == []

    def test_a_template_token_is_caught(self):
        assert placeholder_gate.check("Ship it by [DATE] once the review clears.")

    def test_prose_with_no_token_is_not(self):
        assert placeholder_gate.check("Ship it once the review clears.") == []


class TestTheSuiteCannotPassVacuously:
    """Guard against the shape where a broken import makes everything skip."""

    def test_every_moved_gate_was_actually_imported(self):
        assert len(GATES) == 7
        for gate in GATES:
            assert gate.__file__.endswith(".py")
