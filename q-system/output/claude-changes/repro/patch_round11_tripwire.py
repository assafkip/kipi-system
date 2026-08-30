#!/usr/bin/env python3
"""One-shot patcher for the round-11 BLOCKER, Layer 2 half (ASK-291).

THE FINDING: "Deleting the baseline in the same Bash call as an unanchored
.claude write makes enforcement trust the tampered tree forever"
(claude-integrity-tripwire.py:692).

Layer 1 closes the shape where both halves are VISIBLE in one Bash command
(patch_round11_guard.py). This file closes the half Layer 1 structurally cannot
reach: `bash evil.sh` hands Layer 1 no `.claude` mention, no baseline mention and
no rebaseliner, and the script can delete the baseline and tamper before any
PostToolUse hook fires. Only Layer 2 can notice -- and today it cannot, because a
MISSING baseline is indistinguishable from a fresh instance, so verify() arms
silently on whatever it finds and records the tamper as sanctioned at exit 0.

THE FIX: remember that this tree was armed, in a file that is not the baseline.
Missing baseline + no marker  -> fresh instance, arm silently (round-2 scar).
Missing baseline + marker     -> the backstop was removed. Alarm, refuse to arm.

Run through the sanctioned route (same Bash call as a --register), or Layer 2
reverts this edit one tool call later -- it watches its own file (round-2 scar).
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TARGET = os.path.join(ROOT, "q-system", ".q-system", "scripts", "claude-integrity-tripwire.py")
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# ---------------------------------------------------------------- change 1 --
# The marker constant, and why it is where it is.
pairs.append(('''QUARANTINE_REL = os.path.join("q-system", "output", "claude-integrity", "quarantine")''',
              '''QUARANTINE_REL = os.path.join("q-system", "output", "claude-integrity", "quarantine")

# "This tree has been armed at least once." Written beside the baseline by
# save_baseline(), never removed by this script.
#
# SCAR (review finding, PR #85 round 11, BLOCKER): a MISSING baseline was
# indistinguishable from a fresh instance, so verify() armed silently on
# whatever it found. Delete the baseline and tamper `.claude/` before the next
# hook fires, and the tamper becomes the sanctioned state, permanently, at exit
# 0 -- with `--check` then answering `clean`. Layer 1 closes the shape where
# both halves are VISIBLE in one Bash command (_voids_layer2), but it
# structurally cannot see inside `bash evil.sh`: no `.claude` mention, no
# baseline mention, no rebaseliner in the command it is handed. Only this layer
# can notice, and only if it remembers it was armed.
#
# NOT IN THE WATCH SET, deliberately. A watched marker that this script creates
# would land as `added` against the baseline that preceded it, --enforce would
# delete it, the next run would recreate it, and the flap would page forever.
# Its only job is existence.
#
# GITIGNORED, for the round-2 reason: committed state propagates fleet-wide via
# `kipi update`, so a committed marker would make every fresh instance claim
# prior arming and page SECURITY on its first run -- the exact outage round 2
# was about.
#
# HONEST BOUND, stated rather than hidden: an attacker who removes the marker
# too (or a `git clean -fdX`, which removes both because both are ignored) is
# back to a fresh tree and arms silently. This raises one unwatched `rm` to two
# named paths; it does not make local state undeletable by a local attacker.
# Captured as spillover, not claimed as closed.
ARMED_MARKER_REL = os.path.join("q-system", ".q-system", ".claude-integrity-armed")'''))

# ---------------------------------------------------------------- change 2 --
# save_baseline is the single chokepoint every arming path already goes through
# (--baseline, --register, the first-run arm, and the absorb re-saves), so the
# marker is written there rather than at four call sites that could drift apart.
pairs.append(('''        os.replace(tmp, path)  # atomic swap, never a half-written baseline
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path''',
              '''        os.replace(tmp, path)  # atomic swap, never a half-written baseline
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    mark_armed(root)
    return path


def mark_armed(root):
    """Record that this tree has been armed at least once.

    BEST EFFORT BY DESIGN. A marker we cannot write must never break the write
    that matters, so this swallows its errors: the cost of a missed marker is a
    silent re-arm, which is exactly the pre-fix behaviour and never worse than
    it. A raise here would turn a read-only-parent nuisance into a failed
    baseline, which is the guard breaking the thing it guards."""
    path = os.path.join(root, ARMED_MARKER_REL)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("armed %s -- claude-integrity-tripwire.py (ASK-291). "
                     "Presence means: a missing baseline on this tree is a "
                     "REMOVED backstop, not a fresh instance.\\n"
                     % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except Exception:
        pass


def was_armed(root):
    """True if this tree has ever had a baseline written. See ARMED_MARKER_REL."""
    return os.path.exists(os.path.join(root, ARMED_MARKER_REL))'''))

# ---------------------------------------------------------------- change 3 --
# The first-run branch stops being unconditional.
pairs.append(('''    baseline = load_baseline(root)
    if baseline is None:
        # FIRST RUN IN THIS INSTANCE -> arm silently, do not alarm.''',
              '''    baseline = load_baseline(root)
    if baseline is None and was_armed(root):
        # NOT a first run. This tree HAS been armed, and its baseline is gone.
        #
        # SCAR (review finding, PR #85 round 11, BLOCKER). Arming here is what
        # made `rm <baseline>` a permanent, silent disarm: the very next pass
        # recorded whatever `.claude/` happened to contain -- including a tamper
        # written in the same breath -- as the sanctioned state, returned 0, and
        # answered `clean` forever after. The measurement in the finding was
        # `trusted_sha=pwned`, `first_enforce_rc=0`, `second_enforce_rc=0`.
        #
        # We do NOT re-arm and we do NOT revert. There is no trusted state left
        # to revert TO, and inventing one from the current tree is the defect
        # itself. Alarm, exit non-zero, and name the one deliberate act that
        # restores service.
        #
        # STICKY ON PURPOSE: every later pass takes this same branch until a
        # human runs --baseline. Round 5's lesson was that a hold the next
        # session silently converts into a sanction was never a hold.
        notify(root, "SECURITY: .claude integrity baseline is MISSING on a tree "
                     "that was armed. The backstop was removed; the tree is "
                     "UNVERIFIED until re-baselined deliberately.")
        print("BASELINE MISSING on an armed tree -- refusing to re-arm on an "
              "unverified tree. Inspect .claude/ and the two guard scripts, then "
              "run this script with --baseline to sanction the current state.",
              file=sys.stderr)
        return 2
    if baseline is None:
        # FIRST RUN IN THIS INSTANCE -> arm silently, do not alarm.'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
