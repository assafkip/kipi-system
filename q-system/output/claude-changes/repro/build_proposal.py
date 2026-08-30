#!/usr/bin/env python3
"""build_proposal.py -- generate arm-claude-write-path-guards.json. ASK-291.

WHY A GENERATOR AND NOT A HAND-WRITTEN JSON
The proposal's anchors are byte-exact slices of the two settings files. The
previous proposal carried one anchor that was never verified byte-for-byte
against the file ("an unverified anchor is a guess", its own note said) and one
that was verified but aimed at the WRONG hook group. Both failure modes are
transcription. This script slices the anchors out of the live files, so a
transcription error cannot exist, and prints the uniqueness count for each so a
non-unique anchor is visible before the applier ever sees it.

Re-run after any settings.json reshuffle:
    python3 q-system/output/claude-changes/repro/build_proposal.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "q-system", "output", "claude-changes",
                   "arm-claude-write-path-guards.json")
OUT_PRESENCE = os.path.join(ROOT, "q-system", "output", "claude-changes",
                            "arm-guard-presence-recovery.json")

GUARD1 = "q-system/.q-system/scripts/claude-path-write-guard.py"
GUARD2 = "q-system/.q-system/scripts/claude-integrity-tripwire.py"
CMD1 = 'test -f "$CLAUDE_PROJECT_DIR/%s" && python3 "$CLAUDE_PROJECT_DIR/%s"' % (GUARD1, GUARD1)
CMD2 = ('test -f "$CLAUDE_PROJECT_DIR/%s" && python3 "$CLAUDE_PROJECT_DIR/%s" --enforce --quiet'
        % (GUARD2, GUARD2))

# LAYER 0: the presence check for the other two.
#
# SCAR (review finding, PR #85 round 3): round 2 closed "delete Layer 1" by
# having Layer 2 WATCH Layer 1. Nothing closed "delete Layer 2". Its self-watch
# runs inside the file being deleted, and every configured invocation of it is
# `test -f X && python3 X` -- so the delete takes the detector and its own
# recovery with it, and the layer stays down until somebody notices by hand.
#
# The recovery therefore cannot live in either script. It lives HERE, in the hook
# command string, i.e. in settings.json -- the one artifact both layers exist to
# protect and the only file whose edit is refused by both. Deleting a guard now
# costs a page and a restore on the very next tool call; disarming the recovery
# means editing the guarded config. It also closes "delete BOTH in one command",
# which mutual watching structurally cannot: each hook repairs its own scripts.
#
# Fails LOUD, never silently: a script git cannot restore pages AND exits 2.
# KIPI_NOTIFY is honoured for the same reason the tripwire honours it -- a page
# path that cannot be exercised in a test is a page path nobody has proven.
CMD0 = (
    'for R in %s %s; do [ -f "$CLAUDE_PROJECT_DIR/$R" ] && continue; '
    'git -C "$CLAUDE_PROJECT_DIR" checkout -- "$R" >/dev/null 2>&1; '
    'N="${KIPI_NOTIFY:-$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/slack-notify.sh}"; '
    'if [ -f "$CLAUDE_PROJECT_DIR/$R" ]; then '
    '"$N" "SECURITY: $R was deleted; restored from git" >/dev/null 2>&1; else '
    '"$N" "SECURITY: $R was deleted and git could not restore it -- that layer is DOWN" '
    '>/dev/null 2>&1; echo "SECURITY: $R is missing and could not be restored" >&2; '
    'exit 2; fi; done' % (GUARD1, GUARD2))


def slice_between(text, start, end_after, label):
    """Byte-exact slice, refusing anything that is not unique in the file."""
    i = text.index(start)
    j = text.index(end_after, i) + len(end_after)
    anchor = text[i:j]
    hits = text.count(anchor)
    if hits != 1:
        sys.exit("anchor %s matches %d times, must be 1" % (label, hits))
    print("  anchor %-22s unique, %d bytes" % (label, len(anchor)))
    return anchor


def hook_entry(command, timeout):
    pad = " " * 10
    return ('{\n%s  "type": "command",\n%s  "command": %s,\n%s  "timeout": %d\n%s}'
            % (pad, pad, json.dumps(command), pad, timeout, pad))


def main():
    settings = open(os.path.join(ROOT, ".claude", "settings.json")).read()
    template = open(os.path.join(ROOT, "settings-template.json")).read()

    # Layer 1 rides in a NEW PreToolUse group with matcher "Bash". The anchor is
    # the read-first-gate group; the insert closes that group's hooks array and
    # opens a Bash sibling, and the file's own trailing `]` `}` close the new one.
    l1_anchor_s = slice_between(settings, '"matcher": "Write|Edit|MultiEdit",',
                                '"timeout": 10\n          }', "L1/settings")
    l1_anchor_t = slice_between(template, '"matcher": "Write|Edit|MultiEdit",',
                                '"timeout": 10\n          }', "L1/template")

    # Layer 2 rides in the EXISTING Bash-inclusive PostToolUse group. This is
    # defect 2: the previous proposal aimed it at the group holding
    # settings-template-sync-check.py, whose matcher is "Edit|Write" -- no Bash,
    # so it would never fire on the Bash write it exists to catch, while a
    # grep-based "is it wired?" check passed. Anchoring on the token-guard entry
    # inside `"matcher": "Edit|Write|MultiEdit|Bash"` puts it where Bash is seen.
    l2_anchor_s = slice_between(settings, '"matcher": "Edit|Write|MultiEdit|Bash",',
                                '"timeout": 5\n          }', "L2/settings")
    l2_anchor_t = slice_between(template, '"matcher": "Edit|Write|MultiEdit|Bash",',
                                '"timeout": 5\n          }', "L2/template")

    l1_insert = ('\n        ]\n      },\n      {\n        "matcher": "Bash",\n'
                 '        "hooks": [\n          ' + hook_entry(CMD1, 10))
    l2_insert = ",\n          " + hook_entry(CMD2, 20)
    # Anchored on the same token-guard entry as Layer 2, so it lands BETWEEN the
    # anchor and Layer 2: a guard restored by this entry is then exercised by the
    # tripwire entry in the SAME tool call, not one call later.
    l0_insert = ",\n          " + hook_entry(CMD0, 15)

    why1 = ("Layer 1. PreToolUse on Bash. Closes the measured hole: `touch "
            ".claude/_probe.txt` succeeded via Bash while Write/Edit were refused on "
            "the same path. The insert closes the read-first-gate hooks array and "
            "opens a Bash sibling group; the file's own following `]` and `}` close "
            "the new block, so the result stays valid JSON. Additive: no existing "
            "hook string is touched.")
    why2 = ("Layer 2, the control that actually holds. PostToolUse, in the "
            "Edit|Write|MultiEdit|Bash group -- the ONLY PostToolUse group that can "
            "see a Bash tool call. --enforce (not --check) is correct HERE and only "
            "here: on this path the actor is provably the agent, because the "
            "founder's own editor is not a tool call. Drift is quarantined before it "
            "is reverted, so a false positive costs nothing.")
    why0 = ("Layer 0, the presence check for the other two. Both layers are wired "
            "as `test -f X && python3 X`, so deleting a guard SCRIPT disarms that "
            "layer with no page and no repair. Round 2 closed that for Layer 1 by "
            "having Layer 2 watch it; nothing closed it for Layer 2, whose self-watch "
            "runs inside the very file being deleted. The recovery therefore cannot "
            "live in either script -- it lives in this command string, i.e. in the "
            "config both layers exist to protect. Deleting a guard now costs a page "
            "and a git restore on the next tool call; disarming the recovery means "
            "editing the guarded file. Ordered before Layer 2 in the same group, so a "
            "restored tripwire is exercised in the same tool call. A script git "
            "cannot restore pages AND exits 2 -- never a silent pass.")
    tail = (" Paired into settings-template.json in the same proposal: kipi update "
            "rebuilds every instance's settings.json from the template only, so a "
            "skeleton-only arming protects one repo and ships a dead switch to the "
            "other 22.")

    # DEFECT 4, found by running v1 against a copy rather than by reading it:
    # `notes` is not in the engine's ALLOWED_PROPOSAL_KEYS, so v1 was refused
    # before a single anchor was even looked up. The three defects in the issue
    # were all downstream of a parse that never happened. The engine's vocabulary
    # is deliberately closed (an unknown key is refused, never ignored), so the
    # notes belong inside `reason`, which is the field the applier logs.
    notes = (
        " || NOTES: anchors are sliced byte-exact out of the live files by "
        "q-system/output/claude-changes/repro/build_proposal.py, which refuses any "
        "anchor that is not unique -- re-run it if settings.json is reshuffled, do "
        "not hand-edit the anchors. || A grep for 'claude-integrity-tripwire' PASSES "
        "on the broken v1 of this proposal, so probe_tripwire2.sh instead parses "
        "settings.json, finds the group that CARRIES the hook, and asserts THAT "
        "group's matcher lists Bash: wiring proven structurally, never textually. || "
        "Layer 2 is ALREADY ARMED at session granularity without this proposal, via "
        "q-system/hooks/session-start.py, which is wired and lives outside .claude/. "
        "This proposal narrows the window from one session to one tool call; it is "
        "not what makes the tripwire exist.")

    proposal = {
        "schema_version": 1,
        "slug": "arm-claude-write-path-guards",
        "reason": (
            "ASK-282/ASK-291. Arm the two .claude/ write-path guards on BOTH "
            "surfaces. Layer 1 (claude-path-write-guard.py) blocks the ordinary Bash "
            "write shapes at PreToolUse. Layer 2 (claude-integrity-tripwire.py "
            "--enforce) is the real control: it ignores command shape and checks "
            "whether the CONTENT of .claude/ moved, so an unlisted command form is "
            "not an evasion. They cannot be wired by the agent that wrote them, "
            "because wiring means editing .claude/settings.json -- the exact "
            "vulnerability being closed. That is why this is a proposal and not a "
            "commit. ASK-291 fixed three defects that made the first draft "
            "unappliable: Layer 1 wedged agent worktrees under .claude/worktrees/, "
            "Layer 2 was aimed at a matcher that cannot see Bash, and only the "
            "runtime settings file was edited." + notes),
        "requires": {
            "files_present": [GUARD1, GUARD2],
            # Defect 3. Asserted, not assumed: the applier re-reads the STAGED
            # template and refuses if either command is absent, so the pair cannot
            # silently drift out of this proposal in a later edit.
            # check_template_pairs does a raw substring test against the STAGED
            # template TEXT, where the command's own quotes are JSON-escaped. So
            # the declared pair is the escaped body (json.dumps minus its outer
            # quotes), which is what actually appears in the file. Declaring the
            # unescaped command refuses with "template does not carry" even when
            # the pair is right there -- found by running this against a copy.
            "template_pairs": [json.dumps(CMD1)[1:-1], json.dumps(CMD2)[1:-1]],
        },
        "edits": [
            {"file": ".claude/settings.json", "op": "insert_after",
             "anchor": l1_anchor_s, "insert": l1_insert, "reason": why1},
            {"file": "settings-template.json", "op": "insert_after",
             "anchor": l1_anchor_t, "insert": l1_insert,
             "reason": "Layer 1, fleet surface." + tail},
            {"file": ".claude/settings.json", "op": "insert_after",
             "anchor": l2_anchor_s, "insert": l2_insert, "reason": why2},
            {"file": "settings-template.json", "op": "insert_after",
             "anchor": l2_anchor_t, "insert": l2_insert,
             "reason": "Layer 2, fleet surface." + tail},
        ],
    }

    # A SECOND proposal, not two more edits on the first. The applier refuses a
    # partially-applied proposal ("4 of 6 edits already present"), which is the
    # correct behaviour and the reason this is split: the arming proposal is
    # already applied on the skeleton and on every instance that ran it, so
    # growing it would strand exactly those trees. Each proposal stays a unit
    # that is either wholly applied or wholly absent.
    presence = {
        "schema_version": 1,
        "slug": "arm-guard-presence-recovery",
        "reason": why0 + tail,
        "requires": {
            "files_present": [GUARD1, GUARD2],
            "template_pairs": [json.dumps(CMD0)[1:-1]],
        },
        "edits": [
            {"file": ".claude/settings.json", "op": "insert_after",
             "anchor": l2_anchor_s, "insert": l0_insert, "reason": why0},
            {"file": "settings-template.json", "op": "insert_after",
             "anchor": l2_anchor_t, "insert": l0_insert,
             "reason": "Layer 0, fleet surface." + tail},
        ],
    }

    for path, doc in ((OUT, proposal), (OUT_PRESENCE, presence)):
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        print("wrote %s (%d edits)" % (os.path.relpath(path, ROOT), len(doc["edits"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
