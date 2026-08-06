#!/usr/bin/env python3
"""Refuse a q-system sync whose --delete would remove instance-owned data.

WHY THIS EXISTS (sp-737ce1ae, sp-10cf4f76). kipi-update.sh syncs the skeleton's
q-system/ into each instance with `rsync -a --delete`, protecting instance data
with ANCHORED excludes (`--exclude=/my-project/`). An anchored exclude is
relative to the TRANSFER ROOT, so it only lines up when the destination IS the
instance's q-system dir.

Reproduced 2026-08-05: with `subtree_prefix` null the destination is the
instance ROOT, so an instance that still keeps its data under `q-system/` has
that data one level below where the excludes point. The dry run then itemizes

    *deleting   q-system/my-project/current-state.md
    *deleting   q-system/memory/last-handoff.md
    *deleting   q-system/canonical/decisions.md

and none of `--exclude=/my-project/` etc. matches, because they anchor at
`q-system/my-project/`'s PARENT. `reddit-build-radar` is a real registry entry
with a null prefix.

WHY A GUARD AND NOT ONLY AN EXCLUDE FIX. Re-anchoring the excludes fixes this
variant. It does not fix the class: any future layout, prefix, or registry drift
that moves the destination re-opens the same hole silently, and the failure mode
is deleted founder data with no error. This reads the deletions rsync ACTUALLY
plans, from rsync's own itemized output, and matches instance-owned names at ANY
depth. It is the fail-closed backstop; the excludes remain the first line.

WHAT IT DOES NOT COVER (sp-5e857e2a). This docstring used to claim it "also
covers sp-10cf4f76 (a tracked instance-only script inside the synced tree)
because a deletion is a deletion whatever git thinks of the file". THAT WAS
FALSE and it is the reason the sentence is now this long. `owned_hits` matches
seven instance-owned DATA-DIRECTORY names; a script is not one of them, so

    *deleting q-system/.q-system/scripts/income-scan.sh   -> exit 0

still passes. That exact path is how the fractional-cxo income scanners died
silently for six days. A guard that RECORDS a claim it never COMPUTED is worse
than an obvious gap, because the next reader trusts it -- reading this sentence
almost caused sp-10cf4f76 to be voided as already-fixed.

sp-10cf4f76 IS STILL OPEN. The class it belongs to -- an instance-created file
inside the synced tree, whose NAME nobody enumerated in advance -- cannot be
closed by adding names here, and that is not a matter of effort. Instance-only
and skeleton-owned files are INTERLEAVED IN THE SAME DIRECTORIES: measured
2026-08-06, `q-system/.q-system/scripts/` holds 141 skeleton-owned files, and
the skeleton has deleted 6 files from that directory over its history. Those
deletions are legitimate propagation. Adding `scripts` to INSTANCE_OWNED would
refuse every one of them on all 24 instances -- the PR #111 failure mode again,
and a guard that halts unattended updates gets switched off.

The discriminator therefore cannot be the PATH. It has to be PROVENANCE: did
the skeleton ever ship this file (legitimate removal) or did the instance
create it (data loss)? The skeleton's own git history answers that. Designing
and measuring that inversion is tracked separately; this file deliberately does
not attempt it.

Exit codes:
    0  no instance-owned deletion planned (sync may proceed)
    2  at least one planned deletion touches instance-owned data (ABORT)

Usage:
    rsync -ain --delete SRC DEST <excludes> | python3 kipi-update-deletion-guard.py

Reads the itemized dry-run on stdin. Emits the offending paths on stderr.
"""

from __future__ import annotations

import re
import sys

# Kept in sync with INSTANCE_OWNED_SUBTREES in kipi-update.sh. Duplicated
# deliberately rather than sourced: this script must stay runnable standalone
# (that is what makes it testable without building a skeleton fixture), and a
# drift between the two lists is caught by
# test-kipi-update-owned-deletion-guard.sh, which reads BOTH.
INSTANCE_OWNED = (
    "my-project",
    "canonical",
    "memory",
    "output",
    "research",
    ".q-system/data",
    ".q-system/agent-pipeline/bus",
)


# Verified against the rsync on this machine (openrsync, protocol 29):
# `rsync -ain --delete` emits `*deleting <path>` per removal. The bare
# `deleting <path>` form is accepted too -- it costs one alternation and the
# failure mode of missing it is deleted founder data.
_DELETING = re.compile(r"^\*?deleting\s+(?P<path>.+?)\s*$")


def deletions(itemized: str) -> list[str]:
    """The paths rsync says it will delete, from its own itemized output."""
    out = []
    for line in itemized.splitlines():
        m = _DELETING.match(line.strip())
        if m and m.group("path"):
            out.append(m.group("path"))
    return out


def owned_hits(paths: list[str]) -> list[tuple[str, str]]:
    """(path, subtree) for every deletion that touches instance-owned data.

    Matched at the TRANSFER ROOT or directly under a `q-system/` segment --
    not at any depth.

    "Any depth" was the first shape, because the defect being fixed was an
    anchor in the wrong place and an anchored check looked like it would
    inherit that bug. It over-corrected: `q-system/.q-system/agent-pipeline/
    templates/deck/output/` is a REAL skeleton-owned directory, so deleting a
    skeleton file under it refused the sync for every instance in the fleet
    (Codex, PR #111, with a repro against that live path).

    That is the worse failure. A guard that halts every unattended update gets
    switched off, and a gate that is off protects nothing -- the same scar
    `design-auto-invoke.md` already carries.

    Anchoring on `q-system/` instead of on the transfer root keeps the P0
    catch: the bug was `q-system/my-project/...` appearing when the excludes
    pointed at `my-project/...`, and BOTH still match here, at any prefix
    depth (`<anything>/q-system/my-project/...` matches too).
    """
    hits = []
    for path in paths:
        # Case-FOLDED. macOS is case-insensitive by default, so
        # `q-system/My-Project/` and `q-system/my-project/` are the SAME
        # directory on the founder's machine -- a case-exact match would let a
        # real deletion of real data through on the platform this actually runs
        # on. Found by attacking my own guard, 2026-08-05.
        segments = [s.casefold() for s in path.strip("/").split("/")]
        # An owned name counts at index 0 (destination IS the q-system dir), or
        # directly after a `q-system` segment (destination is the instance root,
        # or any deeper prefix). Anywhere else it is skeleton content that
        # merely shares a name.
        starts = [0] + [i + 1 for i, seg in enumerate(segments)
                        if seg == "q-system"]
        for sub in INSTANCE_OWNED:
            parts = [s.casefold() for s in sub.split("/")]
            for i in starts:
                if segments[i:i + len(parts)] == parts:
                    hits.append((path, sub))
                    break
            else:
                continue
            break
    return hits


def main() -> int:
    # NOTE ON EMPTY INPUT. No deletions planned is the NORMAL case, so empty
    # stdin exits 0 and cannot be made to fail closed here without refusing
    # every healthy sync. The failure it cannot distinguish -- rsync itself
    # erroring and producing nothing -- is caught at the call site instead:
    # kipi-update.sh runs `set -o pipefail`, so a failed rsync fails the whole
    # pipeline and the caller abandons the instance. A caller WITHOUT pipefail
    # would be unsafe; that is why the wiring test asserts the call site.
    hits = owned_hits(deletions(sys.stdin.read()))
    if not hits:
        return 0
    sys.stderr.write(
        f"REFUSING SYNC: rsync --delete would remove {len(hits)} "
        "instance-owned path(s):\n"
    )
    for path, sub in hits[:20]:
        sys.stderr.write(f"  {path}   (instance-owned: {sub}/)\n")
    if len(hits) > 20:
        sys.stderr.write(f"  ... and {len(hits) - 20} more\n")
    sys.stderr.write(
        "\nThis means the destination and the anchored --exclude patterns "
        "disagree about\nwhere the instance's q-system lives (sp-737ce1ae). "
        "Check the instance's\n`subtree_prefix` in instance-registry.json "
        "against its real layout.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
