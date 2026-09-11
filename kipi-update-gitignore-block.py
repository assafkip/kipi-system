#!/usr/bin/env python3
"""Ship the skeleton's instance-local-never-commit stanza into an instance's
root .gitignore, as a managed block.

WHY (sp-097d2e23, sp-bd9bae14, measured 2026-08-14). The skeleton's root
.gitignore says three things must never be committed, and says why:

  * claude-integrity-baseline.json  -- instance-local (ASK-282); a shared
    baseline can never match and Slack-pages every instance daily.
  * .claude-integrity-armed         -- a committed marker makes a fresh
    instance claim prior arming, refuse to arm, and page SECURITY on its
    first run (the ASK-291 round-2 outage).
  * q-system/output/.update-check-* -- daily update stamps, pure exhaust.

Root .gitignore is NOT in the updater's sync set (the set is q-system/,
.claude/{agents,output-styles,rules}/*.md, .claude/settings.json, plugins/),
so no instance has ever received those rules. In the skeleton the gitignore
makes those paths invisible to `git status`; in an instance it does not, so
auto-commit.py sees them, classifies `q-system/.q-system/` as ("chore",
"update system infrastructure"), and commits them unattended.

That is not hypothetical. Measured across the 22 skeleton-managed instances:
five had already committed the baseline and/or the armed marker, the most
recent at 2026-08-14 14:22 under exactly that subject line. The two spillover
notes were filed as separate minor defects; they are one defect, and the
gitignore gap is the cause rather than a cosmetic side effect.

DERIVED, NOT TRANSCRIBED. The stanza is parsed out of the skeleton's own root
.gitignore between the two markers, so adding a fourth never-commit path there
cannot leave this script behind. Same discipline the preserve scan adopted for
INSTANCE_OWNED_PATHS in sp-3d5a247e, and for the same reason: a hand-kept
second copy of a list drifts the moment anyone adds an entry.

Refuses loudly rather than falling back to a literal. A silent fallback would
write a block that does not match what the skeleton actually declares, and the
failure mode -- an instance quietly committing its own tripwire state again --
is invisible until something pages.

Idempotent: rewrites the managed block in place, leaving every other line of
the instance's .gitignore untouched. An instance that already ignores one of
these paths on its own keeps that line; the block is additive.

Usage:
  kipi-update-gitignore-block.py --skeleton DIR --instance DIR [--check]

  --check  report whether the block is current, write nothing. Exit 0 when
           the instance block already matches the skeleton stanza, 1 when it
           would change.
"""
import argparse
import os
import re
import sys

BEGIN = "# >>> kipi-managed: instance-local, never commit >>>"
END = "# <<< kipi-managed: instance-local, never commit <<<"

# The markers as they appear in the SKELETON's .gitignore. Kept distinct from
# the block markers written into an instance so that the skeleton's own copy is
# never mistaken for a managed block and rewritten by a stray --instance run
# pointed at the skeleton.
SKELETON_BEGIN = "# >>> kipi-instance-local-stanza >>>"
SKELETON_END = "# <<< kipi-instance-local-stanza <<<"


def skeleton_stanza(skeleton_dir):
    """The never-commit path lines declared by the skeleton's root .gitignore."""
    path = os.path.join(skeleton_dir, ".gitignore")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise RuntimeError(f"cannot read skeleton .gitignore at {path}: {exc}")
    match = re.search(
        re.escape(SKELETON_BEGIN) + r"\n(.*?)^" + re.escape(SKELETON_END),
        text,
        re.S | re.M,
    )
    if not match:
        raise RuntimeError(
            f"{SKELETON_BEGIN} markers not found in {path}; the gitignore block "
            "writer cannot mirror the skeleton's never-commit stanza and refuses "
            "to guess it"
        )
    lines = [line.rstrip() for line in match.group(1).splitlines()]
    # Comments inside the stanza are the WHY, and an instance reading its own
    # .gitignore deserves them as much as the skeleton does. Blank lines are
    # dropped so the emitted block is stable regardless of skeleton spacing.
    lines = [line for line in lines if line.strip()]
    if not any(line and not line.startswith("#") for line in lines):
        raise RuntimeError(
            f"the stanza between the markers in {path} declares no paths; "
            "refusing to write an empty managed block"
        )
    return lines


def render_block(stanza):
    return "\n".join([BEGIN] + stanza + [END]) + "\n"


def existing_block(text):
    """(before, block, after) for the managed block, or None when absent."""
    match = re.search(
        re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?",
        text,
        re.S | re.M,
    )
    if not match:
        return None
    return text[: match.start()], match.group(0), text[match.end():]


def apply_block(instance_dir, stanza, check_only=False):
    """Write/refresh the managed block. Returns (changed, action)."""
    path = os.path.join(instance_dir, ".gitignore")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}: {exc}")

    block = render_block(stanza)
    found = existing_block(text)
    if found is None:
        # Append. A leading newline only when the file has content and does not
        # already end in one, so repeated runs cannot grow blank lines.
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        new_text = prefix + block
        action = "added"
    else:
        before, current, after = found
        if current.rstrip("\n") == block.rstrip("\n"):
            return False, "current"
        new_text = before + block + after
        action = "refreshed"

    if check_only:
        return True, action

    tmp = path + ".kipi-tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(new_text)
    os.replace(tmp, path)
    return True, action


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skeleton", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if os.path.abspath(args.skeleton) == os.path.abspath(args.instance):
        print("refusing to write a managed block into the skeleton itself",
              file=sys.stderr)
        return 2

    try:
        stanza = skeleton_stanza(args.skeleton)
        changed, action = apply_block(args.instance, stanza, args.check)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if changed:
            print(f"  .gitignore managed block would be {action}")
            return 1
        return 0

    if changed:
        print(f"  .gitignore managed block {action} "
              f"({sum(1 for l in stanza if not l.startswith('#'))} path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
