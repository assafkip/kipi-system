#!/usr/bin/env python3
"""The METHOD/DATA boundary, held by a test and not a comment.

Founder-decided split (voice-architecture PRD, 2026-08-06): the plugin ships the
machinery fleet-wide; the operator's corpus stays in their own instance.
kipi-system is a PUBLIC repo, so a corpus line leaking into this tree is not just
architecture drift, it is founder data published to the world.

The check greps the voiceloop tree for distinctive fingerprints of the private
corpus: phrases from his real writing, his instance paths, and personal
identifiers. Distinctive-but-harmless probes, chosen so the test itself does not
become the leak it polices (the public-skeleton rule: name the data class, never
quote the data at length).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fingerprints of the PRIVATE side. Short, distinctive, non-sensitive probes.
FORBIDDEN = (
    "q-consult",                 # his instance's content dir
    "askconsulting",             # his business
    "pig butchering",            # his corpus subject matter
    "whac-a-mole",               # his coined metric name
    "60 muscles",                # his known post
    "Kipnis",                    # the founder's surname
    # THE GIVEN NAME, added 2026-09-06 (sp-5c0b6406). It was missing, so a module
    # carrying it passed this suite and was caught only later by
    # automation/export_voice_loop.py refusing the public transform. That is the wrong
    # order: this guard is the early check and the exporter is the last one, and until
    # today the PRIVATE package that syncs to every instance carried the name while only
    # the PUBLIC mirror was clean.
    #
    # Two live cases had to be reworded in the same change or this entry turns the suite
    # red on arrival: selector.py's "most Assaf" (now the words the exporter already
    # rendered publicly, so the mirror is byte-identical) and this file's own docstring.
    #
    # The exporter's RENAMES entry for that phrase is deliberately left in place. It
    # matches nothing now, and a dead rename is a second line of defence if the name
    # ever comes back. The layer that worked does not get weakened.
    "Assaf",                     # the founder's given name
)


# BINARY-ONLY DENYLIST, not a text allowlist (PR #311 review, MINOR, 2026-09-06).
# This used to scan an ALLOWLIST of .py/.json/.jsonl/.md, which silently exempted
# every other extension. The port that added this line also added a .txt file to
# the tree, so the one guard standing between a public repo and the founder's
# corpus did not read it -- and the same hole was open for .yaml, .toml, .cfg and
# anything else a future module ships beside itself. The given name was widened
# into FORBIDDEN the same night without anyone noticing the extension list
# underneath it, which is the more dangerous half: a guard that looks stricter
# while covering less.
#
# Inverted deliberately. An allowlist fails OPEN on the file nobody predicted,
# and this guard is exactly the wrong place to fail open.
_BINARY_SUFFIXES = (
    ".pyc", ".pyo", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".gif",
    ".pdf", ".zip", ".gz", ".woff", ".woff2", ".ico",
)


def _tree_files():
    out = []
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        out.extend(os.path.join(root, f) for f in files
                   if not f.endswith(_BINARY_SUFFIXES))
    return out


def test_the_tree_has_files_to_check():
    """Vacuous-pass guard, DERIVED from the tree rather than a pinned literal.

    This asserted `>= 7` against what is now a 44-file package (PR #311 review,
    NIT), so a walk that returned 8 files would have passed while grepping
    almost nothing. A floor that cannot notice a 36-file shortfall is decoration.

    ITS FIRST VERSION WAS TAUTOLOGICAL, and the fix is the whole point of this
    docstring (PR #105 review, MINOR, 2026-09-07). It derived the expected set as
    every `.py` on disk. But `.py` matches no `_BINARY_SUFFIXES` entry, so a `.py`
    file is in the scanned set BY CONSTRUCTION and `py_on_disk - scanned` was empty
    no matter what `_tree_files` did. Its only reachable failure was a walk that
    returned literally nothing.

    Measured against the exact regression it exists to prevent -- putting the old
    `.py/.json/.jsonl/.md` allowlist back:

        hardened scan sees 45 files, allowlist scan sees 44
        missed by the allowlist: requirements-authorship.txt
        py-derived assertion   -> PASSES under both        <- blind
        non-binary assertion   -> FAILS under the allowlist <- catches it

    So the expected set is derived with the SAME predicate the scan uses, negated
    off a raw walk. Now the only way to satisfy it is to actually scan everything
    that is not binary, which is the property the file is about.
    """
    scanned = set(_tree_files())
    on_disk = {
        os.path.join(root, f)
        for root, dirs, files in os.walk(PKG)
        if "__pycache__" not in root
        for f in files
        if not f.endswith(_BINARY_SUFFIXES)
    }
    assert on_disk, "the walk found no files at all -- it is broken"
    missing = sorted(on_disk - scanned)
    assert not missing, "the scan skipped shipped files: %s" % ", ".join(missing)


def test_no_founder_data_in_the_plugin_tree():
    here = os.path.abspath(__file__)
    for path in _tree_files():
        if os.path.abspath(path) == here:
            continue                     # the probe list itself lives here
        with open(path, encoding="utf-8", errors="replace") as handle:
            content = handle.read().lower()
        for needle in FORBIDDEN:
            assert needle.lower() not in content, (
                f"{os.path.relpath(path, PKG)} contains {needle!r}: founder data "
                f"or an instance path is inside the fleet plugin. The corpus "
                f"lives in the instance's voice/ dir, never here.")


def test_the_guard_catches_the_given_name_on_its_own(tmp_path):
    """The needle that was missing, proven to bite.

    The existing self-test plants "pig butchering", which the old FORBIDDEN already
    held. It would have stayed green through the entire window in which the given
    name was invisible. A guard gains a needle and a control for that needle in the
    same change, or the control only ever proves what already worked.
    """
    planted = tmp_path / "leak.py"
    planted.write_text("# the voice most like Assaf, whatever that means\n")
    content = planted.read_text().lower()
    hits = [n for n in FORBIDDEN if n.lower() in content]
    assert hits == ["Assaf"], (
        f"the tree guard did not catch a planted given name; matched {hits}")


def test_negative_selftest_the_probe_detects_a_planted_leak(tmp_path):
    """Prove the predicate catches the thing it exists to catch."""
    planted = tmp_path / "leak.md"
    planted.write_text("notes on the pig butchering analysis")
    with open(planted, encoding="utf-8") as handle:
        content = handle.read().lower()
    assert any(n.lower() in content for n in FORBIDDEN)
