#!/usr/bin/env python3
"""Migrate ONE instance from the `voicekit` package name to `voiceloop`.

why this exists (sp-8d55455a, 2026-08-30): the rename landed in the skeleton as
cf6acdb4 and shipped `plugins/kipi-core/voiceloop/`. `kipi update` rsyncs
`plugins/` with `--delete`, so a sync DELIVERS voiceloop/ and DELETES voicekit/.
The code that imports it does NOT live under plugins/ -- it is instance-owned
pipeline code (consulting's `q-consult/pipeline/voice.py` puts
`<repo>/plugins/kipi-core` on sys.path and then does `from voicekit import ...`).
A sync therefore removes the name that code asks for and CANNOT rewrite the ask.
Measured 2026-08-30: 24 of 25 registered instances still carried voicekit, so the
next `kipi update` was armed to break the voice pipeline in every one of them.

So this is a MIGRATION, not a rename. The package swap and the import rewrite are
one operation, run per instance INSIDE the update path -- never a one-shot script
somebody remembers to run, because an instance that syncs later without it breaks
in exactly the same way.

## The order, and why it is this order

  1. move  plugins/kipi-core/voicekit -> plugins/kipi-core/voiceloop
  2. rewrite the token in instance source files
  3. (caller) rsync, which lands the skeleton's copy on top of the moved dir

Step 1 first, deliberately. Rewriting imports BEFORE the package has the new name
leaves a window where the instance asks for a name nothing provides; doing the
move first leaves a window where the package answers to a name nothing asks for,
which is inert rather than broken. Each step is independently idempotent, so a
run that dies between them is FINISHED by the next run rather than corrupted:
step 1 no-ops once voiceloop/ exists, step 2 no-ops once no token remains.

## Never a delete

If BOTH voicekit/ and voiceloop/ are present (a half-synced instance), this does
NOT remove either one. It rewrites the imports, reports `both_present`, and
leaves the stale directory for the rsync's own --delete or for a founder
decision. Removing a package directory is a destructive op and it is not this
script's call to make (~/.claude/hooks/destructive-op-deny.sh; the 2026-05-17
scar where an agent "fixed" a mismatch by deleting a production volume).

## What gets rewritten, and what deliberately does not

Extensions in REWRITE_EXTS are things the running system executes or reads as
configuration: a stale token there is a defect. Everything else -- .md, .txt and
especially .jsonl -- is a RECORD. `.prd-os/spillover.jsonl`,
`q-consult/output/postbook.jsonl` and the review docs say what was true when they
were written; rewriting them would falsify history to tidy a grep. They are
counted and reported as `history_left`, never edited.

.json is rewritten and .jsonl is not, and that split is the whole rule rather
than an oversight: .json here is config the engine reads (voice-channels.json
names `voiceloop/validate.py`, a path that genuinely moved), .jsonl is an
append-only ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

PLUGIN_PARENT = os.path.join("plugins", "kipi-core")
# Not in REWRITE_EXTS, deliberately: a backup this script wrote must never become
# a file a later run rewrites. .bak lands in `history_left`, counted and left
# alone, which is exactly where a record belongs.
BACKUP_SUFFIX = ".pre-voiceloop.bak"
OLD = "voicekit"
NEW = "voiceloop"

# All four case forms, longest-first is irrelevant here because none is a prefix
# of another. Plain substring replacement, not a \b-anchored regex: the token
# appears as `test_voicekit.py`, `voicekit/validate.py` and `VOICEKIT_DIR`, and a
# word boundary would miss every one of them. This is the same rule
# consulting's automation/export_voice_loop.py has applied to its public mirror
# since 2026-08-20, which is the evidence that a blanket token swap is safe on
# this corpus.
CASE_FORMS = (
    ("voicekit", "voiceloop"),
    ("Voicekit", "Voiceloop"),
    ("VoiceKit", "VoiceLoop"),
    ("VOICEKIT", "VOICELOOP"),
)

REWRITE_EXTS = {
    ".py", ".sh", ".bash", ".zsh",
    ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
}

# Directories never descended into. `.claude/worktrees` and `.wt-*` are OTHER
# LIVE SESSIONS' checkouts of the same repo (feedback_parallel_sessions_one_checkout):
# writing into one yanks another agent's working tree.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "target",
    ".claude-plugin",
}
SKIP_DIR_PREFIXES = (".wt-",)

# THE CHECK MUST NOT REWRITE ITSELF, and a fixture must not be tidied.
#
# Both are the same class (a text rule that matches its own text) and both were
# live defects in the first draft of this file:
#
#  * This module carries the string `voicekit` in its docstring and in
#    CASE_FORMS. Run over its own repo it would rewrite that table to
#    ("voiceloop", "voiceloop") and silently stop migrating anything, while
#    still reporting success.
#  * `**/tests/fixtures/*` holds byte-for-byte COPIES of real artifacts --
#    q-system/.q-system/tests/fixtures/destructive-op-deny.reference.sh mirrors
#    the live destructive-op hook, whose scar text names "voicekit deleted from
#    19 instances" as history. Rewriting the copy makes it stop matching the
#    original, so the fixture's own test fails and the recorded scar is falsified.
#
# Neither is an "adjacent issue to tidy later": a rule that edits its own
# definition is not a rule.
SELF_PATH = os.path.realpath(__file__)
SKIP_PATH_PARTS = (os.path.join("tests", "fixtures") + os.sep,)


def _exempt(path: str) -> bool:
    if os.path.realpath(path) == SELF_PATH:
        return True
    return any(part in path for part in SKIP_PATH_PARTS)


def _skip_dirname(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(SKIP_DIR_PREFIXES)


def iter_source_files(repo: str):
    """Every file in THIS repo's own tree. Nested repos are not this repo.

    A nested checkout carrying its own `.git` is a separate registered instance
    (consulting holds eleven of them under projects/) or an agent worktree. It
    gets its own migration run keyed on its own root; migrating it from the
    parent would write another repo's files and double-count the result. Same
    discriminator kipi-update.sh's own model_skip_scan uses.
    """
    for dirpath, dirnames, filenames in os.walk(repo):
        if dirpath != repo and os.path.exists(os.path.join(dirpath, ".git")):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not _skip_dirname(d)
                       and not os.path.exists(os.path.join(dirpath, d, ".git"))]
        # `.claude/worktrees` is a directory of sibling checkouts; each has a
        # .git FILE (not a dir), which the check above already catches, but the
        # container is skipped outright so a broken worktree cannot be walked.
        if os.path.basename(dirpath) == ".claude":
            dirnames[:] = [d for d in dirnames if d != "worktrees"]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def swap_tokens(text: str) -> str:
    for before, after in CASE_FORMS:
        text = text.replace(before, after)
    return text


def has_token(text: str) -> bool:
    return any(before in text for before, _ in CASE_FORMS)


def plan(repo: str) -> dict:
    """Read-only. What this instance needs, without touching a byte."""
    repo = os.path.abspath(repo)
    old_pkg = os.path.join(repo, PLUGIN_PARENT, OLD)
    new_pkg = os.path.join(repo, PLUGIN_PARENT, NEW)
    has_old = os.path.isdir(old_pkg)
    has_new = os.path.isdir(new_pkg)

    if has_old and has_new:
        package_action = "both_present"
    elif has_old:
        package_action = "move"
    elif has_new:
        package_action = "already"
    else:
        package_action = "absent"

    rewrite, renames, history = [], [], []
    for path in iter_source_files(repo):
        if _exempt(path):
            continue
        rel = os.path.relpath(path, repo)
        base = os.path.basename(path)
        ext = os.path.splitext(base)[1].lower()
        # A FILENAME follows the same record/source split as file CONTENT, and
        # not gating it on the extension was a live defect: the first version
        # queued `q-system/output/plans/ask-565-voicekit-fleet-skew-2026-08-09.md`
        # for rename. That plan is a dated record, its name is part of the
        # record, and other documents cite it by that name. Only a module the
        # import system resolves by filename (test_voicekit.py) has to move.
        if has_token(base) and ext in REWRITE_EXTS:
            renames.append(rel)
        if ext not in REWRITE_EXTS:
            # Cheap membership test first; only files we might edit are read.
            try:
                with open(path, "rb") as fh:
                    blob = fh.read()
            except OSError:
                continue
            if b"oicekit" in blob or b"OICEKIT" in blob:
                history.append(rel)
            continue
        try:
            text = open(path, encoding="utf-8", errors="strict").read()
        except (OSError, UnicodeError):
            continue
        if has_token(text):
            rewrite.append(rel)

    # STAGED-BUT-UNCOMMITTED MIGRATION WORK IS UNFINISHED WORK, and reading the
    # disk alone cannot see that. Measured 2026-08-30 on one instance: its own
    # commit-msg gate refused the migration commit, so the files were moved and
    # rewritten and left staged. The very next run then read the tree, saw the
    # new name everywhere, reported `already` / needs_work=False, and walked past
    # an instance that was dirty and one gate away from being permanently
    # refused by the updater's dirty-tree check. "Recovers rather than
    # corrupting" has to include recovering the COMMIT, not just the bytes.
    staged = _git(repo, "diff", "--cached", "--name-only", "--", PLUGIN_PARENT)
    staged_migration = sorted(l for l in staged.stdout.splitlines() if l.strip()) \
        if staged.returncode == 0 else []

    # ...and the same unfinished state OUTSIDE PLUGIN_PARENT, which the scan
    # above structurally cannot see. The rewrites that matter most are exactly
    # there (consulting's q-consult/pipeline/voice.py). The signature is exact
    # and needs no path heuristic: the HEAD blob asks for the old name and the
    # STAGED blob does not. A founder's own staged edit does not delete this
    # token from a file that carried it.
    #
    # This list is what makes the commit's pathspec (see apply) able to finish
    # an interrupted run without falling back to committing the whole index.
    #
    # --no-renames is load-bearing and was a live defect for one round: with
    # rename detection ON (git's default) `--name-only` prints ONLY the
    # DESTINATION of a rename. The source half of the package move was therefore
    # absent from this list, the commit's pathspec never named it, and a recovery
    # run committed the ADD while leaving the matching DELETE staged -- an
    # instance left dirty by the very run that was recovering it.
    staged_rewrites = []
    staged_all = _git(repo, "diff", "--cached", "--name-only", "--no-renames")
    if staged_all.returncode == 0:
        for rel in (l.strip() for l in staged_all.stdout.splitlines()):
            if not rel:
                continue
            head_blob = _git(repo, "show", f"HEAD:{rel}")
            if head_blob.returncode != 0 or not has_token(head_blob.stdout):
                continue
            idx_blob = _git(repo, "show", f":{rel}")
            if idx_blob.returncode != 0:
                # A staged DELETION of a file that carried the token: the source
                # half of a rename this migration made.
                staged_rewrites.append(rel)
            elif not has_token(idx_blob.stdout):
                staged_rewrites.append(rel)
    staged_rewrites = sorted(staged_rewrites)

    return {
        "repo": repo,
        "package_action": package_action,
        "rewrite": sorted(rewrite),
        "renames": sorted(renames),
        "history_left": sorted(history),
        "staged_migration": staged_migration,
        "staged_rewrites": staged_rewrites,
        # The one line a caller can branch on. `already`/`absent` with nothing to
        # rewrite AND nothing staged is a finished instance.
        "needs_work": (package_action in ("move", "both_present")
                       or bool(rewrite) or bool(renames)
                       or bool(staged_migration) or bool(staged_rewrites)),
    }


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    # errors="replace", and it is load-bearing rather than defensive dressing.
    # `staged_rewrites` asks for the HEAD and index blobs of every staged path,
    # and under the default strict decoding a staged BINARY file made subprocess
    # raise UnicodeDecodeError while merely PLANNING. The updater's dirty guard
    # permits staged work outside its managed paths, so a staged png is ordinary
    # and took the whole migration down before it read one source file.
    # Replacement characters cannot spell the token, so the membership test stays
    # exact for the text this actually cares about.
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, errors="replace")


def _tracked(repo: str, rel: str) -> bool:
    return _git(repo, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def _dirty_tracked(repo: str, rels: list) -> list:
    """Tracked files among `rels` carrying uncommitted changes, staged or not.

    UNTRACKED files are deliberately NOT included. This module already decided to
    rewrite those and leave them untracked rather than let them import a package
    that no longer exists (see the git add block); widening this to untracked
    would silently reverse that decision.
    """
    if not rels:
        return []
    r = _git(repo, "status", "--porcelain", "--", *sorted(set(rels)))
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        if not line.strip() or line.startswith("??"):
            continue
        path = line[3:].strip()
        if " -> " in path:                      # a staged rename: take the source
            path = path.split(" -> ")[0]
        out.append(path.strip('"'))
    return sorted(set(out))


def apply(repo: str, commit: bool = True) -> dict:
    repo = os.path.abspath(repo)
    p = plan(repo)
    result = {**p, "moved": False, "rewritten": [], "renamed": [], "committed": False,
              "errors": [], "left_untracked": [], "backed_up": []}
    # Snapshot tracked-ness BEFORE any write, because `git mv` and the rewrites
    # change it. Empty set when this is not a git repo, which makes every path
    # "untracked" and the commit step a no-op -- correct for a scratch copy.
    ls = _git(repo, "ls-files")
    tracked_before = set(ls.stdout.splitlines()) if ls.returncode == 0 else set()

    # A FILE THE FOUNDER IS ALREADY EDITING IS NOT THIS SCRIPT'S TO REWRITE.
    #
    # Codex MAJOR round 2 on PR #292: pathspec-limiting the commit stopped it
    # absorbing an UNRELATED staged file and left the case where the founder's
    # staged edit sits in the VERY file the token swap has to touch. The swap and
    # the edit are then the same file and no pathspec can separate them.
    #
    # So nothing is written. The error propagates, the caller abandons this
    # instance BEFORE the --delete rsync, and the founder's work is exactly where
    # they left it. The instance stays on the old package name, which is inert:
    # the rsync that would strand its imports never runs either. Loud and
    # reversible beats a migration commit that quietly carries somebody's WIP.
    #
    # Checked ONCE, here, against the PRE-MOVE paths. After `git mv` the package's
    # own files read as staged renames and would false-trip this.
    blocked = _dirty_tracked(repo, p["rewrite"] + p["renames"])
    if blocked:
        result["errors"].append(
            "refusing to rewrite %d file(s) with uncommitted changes; commit or "
            "stash them and re-run: %s" % (len(blocked), ", ".join(blocked[:5])))
        result["verified"] = False
        return result

    # --- step 1: the package gets the new name -------------------------------
    if p["package_action"] == "move":
        old_rel = os.path.join(PLUGIN_PARENT, OLD)
        new_rel = os.path.join(PLUGIN_PARENT, NEW)
        if _tracked(repo, old_rel):
            # `git mv` so the rename is recorded rather than showing as a mass
            # delete+add, which is what the updater's own dirty guards read.
            r = _git(repo, "mv", old_rel, new_rel)
            if r.returncode != 0:
                result["errors"].append("git mv failed: " + r.stderr.strip())
                return result
        else:
            os.rename(os.path.join(repo, old_rel), os.path.join(repo, new_rel))
        result["moved"] = True

    # --- step 2: the code asks for the new name ------------------------------
    # Re-planned against the POST-MOVE tree: the move relocated files that are
    # themselves in the rewrite set (the package's own modules and tests), so the
    # pre-move relative paths are stale. Re-reading is cheap; acting on a stale
    # path list is the "validate the mutant applied" failure -- an edit that
    # silently lands nowhere.
    p2 = plan(repo)
    for rel in p2["rewrite"]:
        path = os.path.join(repo, rel)
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeError) as exc:
            result["errors"].append(f"read {rel}: {exc}")
            continue
        new_text = swap_tokens(text)
        if new_text == text:
            continue
        # NOTHING RESTORES WHAT WAS NEVER TRACKED. Codex BLOCKER on PR #292:
        # rewriting an untracked file in place destroys the only copy of somebody
        # else's work in progress. Rewriting it is still right, because leaving it
        # importing a package that no longer exists is the breakage this file
        # exists to prevent, but making that irreversible is not this script's
        # call. Tracked files get no backup on purpose: version control already IS
        # the backup, and a .bak beside all 36 rewritten modules would be litter
        # in the one instance this runs on.
        if rel not in tracked_before:
            keep = path + BACKUP_SUFFIX
            if not os.path.exists(keep):
                shutil.copy2(path, keep)
                result["backed_up"].append(rel + BACKUP_SUFFIX)
        # Atomic per file: a run killed mid-sweep leaves whole files, never a
        # half-written module, and the next run finishes the remainder.
        tmp = path + ".voiceloop-migrate.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        # CARRY THE MODE ACROSS. Codex MAJOR on PR #292: the temp file is created
        # at the default 0644 and os.replace puts it over the original, so every
        # executable this touched came back non-executable. A hook or scheduled
        # job invoked as a bare path stops running at 0644 and says nothing -- the
        # failure is silence, not an error -- and .sh is in REWRITE_EXTS by design.
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except OSError as exc:
            result["errors"].append(f"chmod {rel}: {exc}")
            os.unlink(tmp)
            continue
        os.replace(tmp, path)
        result["rewritten"].append(rel)

    for rel in p2["renames"]:
        src = os.path.join(repo, rel)
        if not os.path.exists(src):
            continue
        dst_rel = os.path.join(os.path.dirname(rel), swap_tokens(os.path.basename(rel)))
        if _tracked(repo, rel):
            r = _git(repo, "mv", rel, dst_rel)
            if r.returncode != 0:
                result["errors"].append(f"git mv {rel}: {r.stderr.strip()}")
                continue
        else:
            os.rename(src, os.path.join(repo, dst_rel))
        result["renamed"].append(f"{rel} -> {dst_rel}")

    # --- step 3: prove it, against the tree we just wrote --------------------
    after = plan(repo)
    if after["package_action"] == "move":
        result["errors"].append("package still named voicekit after apply")
    if after["rewrite"]:
        result["errors"].append("tokens remain in source files: "
                                + ", ".join(after["rewrite"][:5]))
    if after["renames"]:
        result["errors"].append("filenames still carry the token: "
                                + ", ".join(after["renames"][:5]))
    result["verified"] = not result["errors"]

    # --- step 4: commit, or the next run's dirty guard refuses forever -------
    # feedback_writer_that_never_commits: this writes OUTSIDE the synced prefix
    # (q-consult/, automation/, scripts/), which the updater's own sync commit is
    # pathspec-limited away from. Left dirty, the migration blocks every future
    # update of the instance it just fixed.
    #
    # No --no-verify. The kipi-update.sh precedent is scoped to ITS auto-commit;
    # a hook that rejects this commit is a hook doing its job, and the honest
    # answer is a loud failure, not a bypass.
    # `p["staged_migration"]` is why a re-run finishes an interrupted one: this
    # run may have touched nothing because a PREVIOUS run already did the writes
    # and only its commit failed.
    touched = bool(result["moved"] or result["rewritten"] or result["renamed"]
                   or p["staged_migration"] or p["staged_rewrites"])
    if commit and touched and not result["errors"]:
        add = _git(repo, "add", "-A", "--", PLUGIN_PARENT)
        if add.returncode != 0:
            result["errors"].append("git add (plugins): " + add.stderr.strip())
        # ONLY files git already tracked. An UNTRACKED file in the rewrite set is
        # somebody's work in progress -- measured 2026-08-30, consulting had
        # q-consult/pipeline/tests/audit_channel_wiring.py untracked while another
        # live session worked in that tree. `git add` on it would commit a peer's
        # WIP inside a migration commit, which is the auto-commit-sweeps-the-wrong
        # -branch scar. It still gets REWRITTEN, because leaving it importing a
        # package that no longer exists is the breakage this whole file prevents;
        # it just stays untracked, exactly as its author left it.
        for rel in result["rewritten"]:
            if rel in tracked_before:
                _git(repo, "add", "--", rel)
            else:
                result["left_untracked"].append(rel)
        for pair in result["renamed"]:
            src, dst = pair.split(" -> ")
            _git(repo, "add", "--", src, dst)
        # THE COMMIT IS PATHSPEC-LIMITED, and this is the second half of a fix
        # whose first half was not enough. Codex MAJOR on PR #292 (sp-27bbf105):
        # the `git add` calls above were carefully scoped and `git commit -m`
        # was not, so it wrote the WHOLE index. The updater's dirty guard
        # deliberately PERMITS staged work outside q-system/, .claude/ and
        # plugins/, and every such founder file was landing inside a migration
        # commit. The earlier fix for this exact class scoped the add and left
        # the commit alone: the hole moved instead of closing
        # (feedback_defect_class_relocates), and the suite could not see it
        # because the only commit test staged everything with `git add -A` and
        # asserted the index came back empty -- true only while the commit is
        # unscoped.
        #
        # PLUGIN_PARENT is in the scope because the updater's dirty guard already
        # refuses an instance with dirt under plugins/, so nothing of the
        # founder's can be staged there. `staged_rewrites` carries a rewrite an
        # interrupted earlier run left staged OUTSIDE it, which is the only other
        # way a migration path is staged without THIS run having touched it;
        # without it a recovery run would commit the package and abandon the
        # imports, still staged, still dirty.
        scope = [PLUGIN_PARENT]
        scope += [rel for rel in result["rewritten"] if rel in tracked_before]
        for pair in result["renamed"]:
            scope += pair.split(" -> ")
        scope += p["staged_rewrites"]
        # --no-renames for the same reason plan() needs it: with rename
        # detection on, this returns only a rename's destination, and the
        # unnamed source stays staged after the commit.
        staged = _git(repo, "diff", "--cached", "--name-only", "--no-renames",
                      "--", *sorted(set(scope)))
        commit_paths = [l.strip() for l in staged.stdout.splitlines() if l.strip()]
        if commit_paths:
            # The `[no-issue:]` hatch, with a reason, is required and not
            # optional decoration. Measured 2026-08-30: one client engagement's
            # own commit-msg hook rejected the first fleet run, because a
            # spillover id does not match its issue pattern
            # ([A-Z][A-Z0-9]{1,9}-\d+), which left that instance rewritten,
            # staged and uncommitted. A per-instance gate is not a thing to route
            # around with --no-verify; this is the sanctioned hatch, and it is
            # written to that repo's bypass ledger.
            msg = (
                "migrate: voicekit -> voiceloop, package and imports together "
                "[no-issue: fleet migration, sp-8d55455a tracks it]\n\n"
                "kipi update rsyncs plugins/ with --delete, so a sync alone "
                "delivers voiceloop/, removes voicekit/, and cannot rewrite the "
                "instance-owned imports that still ask for the old name. The "
                "package move and the import rewrite are one operation.\n"
            )
            # Every path here came back from `diff --cached`, so each is already
            # known to the index and git will not reject the pathspec. Partial
            # commit mode takes the working-tree content for these paths and
            # leaves every other staged path staged, which is the whole point.
            c = _git(repo, "commit", "-m", msg, "--", *commit_paths)
            if c.returncode != 0:
                result["errors"].append("commit failed: "
                                        + (c.stderr.strip() or c.stdout.strip()))
            else:
                result["committed"] = True
        result["verified"] = not result["errors"]
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write. Without it this is a read-only plan.")
    ap.add_argument("--no-commit", action="store_true",
                    help="write but leave the changes uncommitted (tests only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.repo):
        print(f"ERROR: no such repo: {args.repo}", file=sys.stderr)
        return 2

    # The skeleton is not a migration target and pointing this at it is a
    # mistake worth refusing rather than absorbing. It shipped the rename in
    # cf6acdb4, so every `voicekit` still in it is DELIBERATE history: the scar
    # line in the destructive-op hook, the .verify-suites comment, the
    # why-the-name-changed note in voiceloop/__init__.py. A migration run there
    # would edit the record of why the migration exists.
    if os.path.isfile(os.path.join(args.repo, "instance-registry.json")):
        print("ERROR: that is the skeleton (instance-registry.json at its root). "
              "It already carries voiceloop; its remaining mentions are history. "
              "Point --repo at an instance.", file=sys.stderr)
        return 2

    out = apply(args.repo, commit=not args.no_commit) if args.apply else plan(args.repo)

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        name = os.path.basename(os.path.abspath(args.repo))
        if not args.apply:
            print(f"{name}: package={out['package_action']} "
                  f"rewrite={len(out['rewrite'])} rename={len(out['renames'])} "
                  f"history_left={len(out['history_left'])} "
                  f"needs_work={out['needs_work']}")
        else:
            print(f"{name}: moved={out['moved']} "
                  f"rewritten={len(out['rewritten'])} renamed={len(out['renamed'])} "
                  f"committed={out['committed']} verified={out['verified']}")
            for e in out["errors"]:
                print("  ERROR: " + e, file=sys.stderr)
    if args.apply and out.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
