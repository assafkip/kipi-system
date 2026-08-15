#!/usr/bin/env python3
"""Clear updater exhaust out of instances, and ONLY what it can attribute.

`fleet-reach-audit.py` says WHY each instance refuses an update. This acts on
that answer. It is the write half; the audit stays read-only so it can still be
trusted as the before/after measurement of this script's own work.

THE CLASSIFIER IS IMPORTED, NEVER TRANSCRIBED. guard_pathspec / classify /
blob_sha come out of fleet-reach-audit.py at run time. A second copy of the
guard's pathspec is exactly how a clearing tool starts touching a path the real
guard never blocked on -- and this one writes, so that mistake costs founder
work rather than a wrong number.

Three actions, each with its own proof, and a refusal for everything else:

  restore-mode  index and worktree hold the SAME blob and differ only in file
                mode. The fix is chmod back to the index's mode, never a commit:
                committing would make the broken mode the new truth. Found on
                KTLYST_strategy 2026-08-14, where rsync had dropped +x (and
                group/other read) from skill-trigger-eval.py -- a script that
                had silently stopped being executable. The blocked update was
                the only symptom anybody could see.

  commit        the blob is one the SKELETON itself once held at this exact
                path (fleet-reach-audit.SkeletonBlobs). A founder hand-edit does
                not collide with skeleton bytes, so this is updater exhaust
                whose writer never committed it. Committing is non-destructive:
                the bytes are kept, not discarded, and the next sync writes the
                newer skeleton copy over it.

  unstage       a staged ADD whose worktree copy agrees with the index, AND
                whose blob is present in the skeleton's committed rescued/ tree.
                `git restore --staged` drops the index entry and leaves the file
                on disk byte-for-byte, so nothing is destroyed even before the
                rescued/ copy is counted. Both proofs are required because the
                one time this class showed up (memory-lifecycle, ASK-803) the
                orphan directory everybody read as dirt was the LAST COPY of
                working code, and the obvious clear -- delete it -- destroyed it.

Anything else is `refuse`: reported by name so a remaining refusal is legible
rather than mysterious. Never a delete, never a discard of worktree content,
never --no-verify.

Dry run is the default. --apply writes.
"""

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys

SKELETON = pathlib.Path(__file__).resolve().parent


def load_audit(skeleton):
    """Import fleet-reach-audit.py as a module (its name has a hyphen)."""
    path = pathlib.Path(skeleton) / "fleet-reach-audit.py"
    if not path.is_file():
        raise RuntimeError(
            f"{path} is missing; fleet-unblock refuses to re-derive the "
            "updater guard's pathspec from a second copy"
        )
    spec = importlib.util.spec_from_file_location("fleet_reach_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args):
    """Returns (returncode, stdout, stderr). No exceptions, no shell."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def entry_mode(repo, path, where):
    """File mode git sees, as a 6-digit string. "" when the path is absent."""
    if where == "index":
        out = git(repo, "ls-files", "-s", "--", path)[1].split()
        return out[0] if out else ""
    full = pathlib.Path(repo) / path
    if not full.is_file():
        return ""
    # git only records the executable bit, so ask git rather than os.stat:
    # a 100644-vs-100755 answer derived from st_mode would disagree with the
    # guard on any filesystem git treats as mode-less.
    for line in git(repo, "diff", "--raw", "--", path)[1].splitlines():
        fields = line.split("\t")[0].lstrip(":").split()
        if len(fields) >= 2:
            return fields[1]
    return entry_mode(repo, path, "index")


def in_head(repo, path):
    return git(repo, "cat-file", "-e", f"HEAD:{path}")[0] == 0


def head_blob(repo, path):
    """Blob sha at HEAD for `path`, or "" when the path is not in HEAD.

    Needed to tell "nothing is staged, so the index still mirrors HEAD" from
    "somebody deliberately staged something". The index alone cannot say which.
    """
    rc, out, _ = git(repo, "rev-parse", f"HEAD:{path}")
    return out.strip() if rc == 0 else ""


class RescuedBlobs:
    """Blobs the skeleton has COMMITTED under rescued/, by sha.

    The preservation half of the `unstage` proof. Reads the skeleton's HEAD
    tree, not the worktree: an uncommitted rescue is not a rescue, and this
    script's whole job is not to trust an uncommitted copy of anything.
    """

    def __init__(self, skeleton):
        self.shas = set()
        out = git(skeleton, "ls-tree", "-r", "HEAD", "--", "rescued/")[1]
        for line in out.splitlines():
            fields = line.split()
            if len(fields) >= 3:
                self.shas.add(fields[2])

    def holds(self, sha):
        return bool(sha) and sha in self.shas


def decide(repo, row, audit, rescued):
    """One blocking row -> (action, reason). Refuses by default."""
    path = row["path"]
    index_sha = audit.blob_sha(repo, path, "index")
    work_sha = audit.blob_sha(repo, path, "worktree")
    index_mode = entry_mode(repo, path, "index")
    work_mode = entry_mode(repo, path, "worktree")

    # Mode first. A mode-only row also classifies as fleet-written (the blob IS
    # a skeleton blob), and committing it would bake the broken mode in. Order
    # matters here; this is not an arbitrary sequence.
    #
    # BUT MODE-FIRST IS NOT ATTRIBUTION-FREE (PR #165 review round 3, major).
    # Running before the kind check meant this branch also swallowed the FOUNDER
    # case: a script the founder wrote and deliberately made executable has an
    # unchanged blob and a changed mode, which is precisely the shape matched
    # here. The tool chmod'ed it back and reported the instance repaired --
    # silently undoing a deliberate change, on a file the skeleton has never
    # heard of.
    #
    # The scar this branch exists for (KTLYST_strategy, skill-trigger-eval.py)
    # was a SKELETON file whose +x rsync had dropped. Requiring the blob to be
    # one the skeleton actually wrote keeps that case and drops the founder's.
    # A non-skeleton blob falls through to the kind checks and is refused.
    # Reproducer: test_a_founder_chmod_on_a_file_the_skeleton_never_shipped_is_refused
    # Control:    test_the_skeleton_owned_mode_fix_still_fires
    if (index_sha and index_sha == work_sha and index_mode != work_mode
            and audit_wrote(audit, path, index_sha)):
        return "restore-mode", (
            f"same blob {index_sha[:12]}, mode {work_mode or '?'} on disk vs "
            f"{index_mode} in index; chmod back, never commit the broken mode"
        )

    if row["kind"] == "fleet-written":
        # BOTH SIDES OF THE PATH, NOT ONE (PR #165 review, major).
        #
        # The index can hold a blob the skeleton really did ship while the
        # WORKTREE holds bytes it never had -- a founder edit on top of a staged
        # skeleton write. This branch used to match on the index alone and
        # schedule a commit. `git commit` takes the INDEX, so the run would clear
        # the dirty-tree guard, report the path repaired, and leave the founder's
        # edit uncommitted for the next sync to overwrite. Founder work destroyed
        # by the tool whose entire job is avoiding exactly that.
        #
        # One side matching the skeleton is not attribution, it is half of one.
        # Reproducer: test_a_staged_skeleton_blob_with_a_founder_worktree_edit_is_refused.
        #
        # Scoped to the WORKTREE differing from the index, deliberately. In the
        # ordinary case nothing is staged, so the index still holds the HEAD blob
        # -- which the skeleton never wrote and never should have -- and
        # demanding both sides be skeleton blobs would refuse every real repair.
        # What matters is what is LEFT BEHIND after committing the index.
        if work_sha and work_sha != index_sha and not audit_wrote(audit, path, work_sha):
            return "refuse", (
                f"index holds skeleton blob {index_sha[:12]} but the worktree "
                f"holds {work_sha[:12]}, which the skeleton never wrote; "
                "committing the index would leave that edit for the next sync "
                "to overwrite"
            )
        # THE MIRROR OF THE GUARD ABOVE (PR #165 review round 4, major).
        #
        # That one asks whether the WORKTREE is attributable. This asks the same
        # of the INDEX, and the case it catches is the reverse: the founder
        # STAGED their own version and the worktree happens to hold a skeleton
        # blob. The guard above passes, `git add` then replaces the founder's
        # staged entry with the worktree blob, and the commit SUCCEEDS -- so the
        # unwind added in round 2 never runs, because nothing failed. The
        # founder's staged version is committed away and gone.
        #
        # "Attributable" for the index means the skeleton wrote it, or nothing
        # was staged at all -- an unstaged path still has the HEAD blob in its
        # index, which is why this compares against HEAD rather than just
        # checking for skeleton authorship.
        #
        # Scoped inside the fleet-written branch on purpose: a staged ADD is not
        # in HEAD at all, and that case has its own rescued/ proof further down.
        # Reproducer: test_founder_staged_content_under_a_skeleton_worktree_blob_is_refused.
        if (in_head(repo, path) and index_sha
                and index_sha != head_blob(repo, path)
                and not audit_wrote(audit, path, index_sha)):
            return "refuse", (
                f"the index holds {index_sha[:12]}, which the skeleton never "
                "wrote and which differs from HEAD, so the founder staged it "
                "deliberately; committing would replace it with the worktree copy"
            )
        which = index_sha if audit_wrote(audit, path, index_sha) else work_sha
        return "commit", (
            f"blob {which[:12]} is one the skeleton itself held at {path}"
        )

    if row["kind"] == "staged-only" and row["staged"] and not in_head(repo, path):
        if rescued.holds(index_sha):
            return "unstage", (
                f"staged ADD, worktree agrees, and blob {index_sha[:12]} is "
                "committed in the skeleton under rescued/"
            )
        return "refuse", (
            f"staged ADD but blob {index_sha[:12]} is NOT in the skeleton's "
            "committed rescued/ tree; unstaging leaves the only copy untracked"
        )

    return "refuse", f"kind={row['kind']}; not attributable to the fleet"


def audit_wrote(audit, path, sha):
    return audit.SKEL_BLOBS.wrote(path, sha) if sha else False


def apply_instance(repo, plan, apply, message):
    """Run one instance's plan. Returns a list of (action, path, outcome)."""
    done = []
    to_commit = [p for a, p, _ in plan if a == "commit"]
    to_unstage = [p for a, p, _ in plan if a == "unstage"]
    to_chmod = [(p, r) for a, p, r in plan if a == "restore-mode"]

    for path, _reason in to_chmod:
        mode = entry_mode(repo, path, "index")
        if not apply:
            done.append(("restore-mode", path, f"would chmod to {mode}"))
            continue
        bits = 0o755 if mode == "100755" else 0o644
        (pathlib.Path(repo) / path).chmod(bits)
        still = entry_mode(repo, path, "worktree")
        done.append(("restore-mode", path,
                     "clean" if still == mode else f"STILL {still}"))

    for path in to_unstage:
        if not apply:
            done.append(("unstage", path, "would restore --staged"))
            continue
        rc, _, err = git(repo, "restore", "--staged", "--", path)
        done.append(("unstage", path, "clean" if rc == 0 else f"FAILED {err.strip()}"))

    if to_commit:
        if not apply:
            for path in to_commit:
                done.append(("commit", path, "would stage + commit"))
        else:
            done += commit_with_unwind(repo, to_commit, message)
    return done


# SUCCESS IS AN ALLOWLIST (PR #165 review round 2, major).
#
# Round 1 made a REFUSED commit exit non-zero by testing
# `outcome.startswith("REFUSED")`. The other producers emit "FAILED add: ",
# "FAILED <err>" and "STILL <mode>" -- none of which start with REFUSED -- so
# every one of them still counted as a successful action and still exited 0.
#
# A denylist of failure strings is the wrong shape for the thing an unattended
# job reads as its exit code: the next outcome string anyone adds lands on the
# success side by default. Fail closed instead. An outcome counts as success
# only if it says so, and "would ..." is the dry run, which succeeds by writing
# nothing.
#
# Pinned by test_a_failed_add_or_restore_is_not_counted_as_success and
# test_every_outcome_the_code_emits_is_classified, the second of which derives
# the outcome literals from this file so a new one cannot arrive unclassified.
def succeeded(outcome):
    return outcome in ("clean", "committed") or outcome.startswith("would ")


def commit_with_unwind(repo, paths, message):
    """Stage and commit `paths`, restoring the prior index if the commit fails.

    A commit here runs the INSTANCE's pre-commit hooks, and two of the five
    instances have them. A hook exiting non-zero must not leave the index in a
    state nobody chose: the founder would come back to paths staged by a script
    that then reported failure. So the pre-run staged set is recorded first and
    restored on any failure.

    Never --no-verify. A hook that refuses this commit is a hook doing its job,
    and the correct outcome is a refusal that says so.
    """
    # RECORD THE ENTRY, NOT JUST THE FACT (PR #165 review round 2, major).
    #
    # This used to be a set of "was already staged" paths, and unwind() SKIPPED
    # them: the tool did not stage it, so the tool should not unstage it. By the
    # time unwind runs, `git add` has already overwritten that index entry with
    # the worktree content -- so a founder who had staged their own version of
    # the path lost it, and the run printed "index unwound" while saying so.
    #
    # Skipping a path is not restoring it. Keep the exact index entry (mode and
    # blob) and put it back.
    # Reproducer: test_the_unwind_restores_content_the_founder_had_already_staged.
    was_staged = {}
    for path in paths:
        if git(repo, "diff", "--cached", "--quiet", "--", path)[0] != 0:
            rc, out, _ = git(repo, "ls-files", "--stage", "--", path)
            entry = out.strip().splitlines()
            if rc == 0 and entry:
                meta = entry[0].split("\t", 1)[0].split()
                if len(meta) >= 2:
                    was_staged[path] = (meta[0], meta[1])   # (mode, blob sha)

    def unwind():
        for path in paths:
            entry = was_staged.get(path)
            if entry is None:
                git(repo, "restore", "--staged", "--", path)
            else:
                mode, sha = entry
                git(repo, "update-index", "--cacheinfo", f"{mode},{sha},{path}")

    rc, _, err = git(repo, "add", "--", *paths)
    if rc != 0:
        unwind()
        return [("commit", p, f"FAILED add: {err.strip()}") for p in paths]

    rc, _, err = git(repo, "commit", "-m", message, "--", *paths)
    if rc != 0:
        unwind()
        detail = (err.strip() or "hook or commit refused").splitlines()[-1:]
        return [("commit", p, f"REFUSED (index unwound): {detail}") for p in paths]
    return [("commit", p, "committed") for p in paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--skeleton", default=str(SKELETON))
    parser.add_argument("--only", action="append", default=[],
                        help="limit to these instance names (repeatable)")
    # The [no-issue:] token is NOT a bypass added to get past a gate. One client
    # engagement's instance requires every commit to name a Linear issue in THAT
    # instance's project, and this commit is fleet exhaust: it has no issue there
    # and should not be given a fake one, which is the failure mode that gate's
    # own presence-check invites. Its script carries a first-class hatch
    # (BYPASS_RE, reason required), and the updater's own system-state commits
    # already use it. Instances without the gate ignore the token.
    parser.add_argument("--message", default=(
        "chore(fleet): commit updater exhaust its writer never committed "
        "[no-issue: fleet updater exhaust, no issue in this instance]\n\n"
        "Written by the fleet updater, never committed, so the dirty-tree guard "
        "refused every later sync. Attributed by fleet-unblock.py: each blob "
        "here is one the skeleton itself held at this exact path."))
    args = parser.parse_args()

    skeleton = pathlib.Path(args.skeleton).resolve()
    audit = load_audit(skeleton)
    owned = audit.instance_owned_subtrees(skeleton / "kipi-update.sh")
    audit.SKEL_BLOBS = audit.SkeletonBlobs(skeleton)
    rescued = RescuedBlobs(skeleton)

    registry = json.loads((skeleton / "instance-registry.json").read_text())
    entries = [
        i for i in registry["instances"]
        if not str(i.get("status", "")).startswith("merged")
        and i.get("skeleton_managed") is not False
        and (not args.only or i["name"] in args.only)
    ]

    print(f"MODE: {'APPLY' if args.apply else 'dry run'}\n")
    refused = 0
    failed = 0
    acted = 0
    for entry in entries:
        result = audit.audit_instance(entry, owned, audit.SKEL_BLOBS)
        if result["verdict"] not in ("BLOCKED-FLEET", "BLOCKED-FOUNDER"):
            continue
        repo = pathlib.Path(entry["path"])
        plan = []
        for row in result["blocked_by"]:
            action, reason = decide(repo, row, audit, rescued)
            plan.append((action, row["path"], reason))

        print(f"{entry['name']}  [{result['verdict']}]")
        for action, path, reason in plan:
            if action == "refuse":
                refused += 1
                print(f"    REFUSE  {path}\n              {reason}")
        actionable = [p for p in plan if p[0] != "refuse"]
        for action, path, reason in actionable:
            print(f"    {action:12s} {path}\n              {reason}")
        for action, path, outcome in apply_instance(repo, actionable, args.apply, args.message):
            if succeeded(outcome):
                acted += 1
            else:
                failed += 1
            print(f"    -> {action:12s} {path}: {outcome}")
        print()

    print(f"acted on {acted} path(s); refused {refused} path(s)"
          + (f"; {failed} action(s) FAILED" if failed else ""))
    # NON-ZERO WHEN AN ACTION WE ACCEPTED THEN FAILED (PR #165 review, major).
    #
    # `refused` is a decision and is a SUCCESSFUL outcome: the script looked,
    # could not attribute the change, and correctly left it alone. `failed` is
    # different -- the script accepted the path, tried, and the repair did not
    # happen (a pre-commit hook rejected it). Exiting 0 there tells an unattended
    # fleet job the run succeeded while every instance stays blocked, which is
    # the silent-success class this whole effort exists to end.
    #
    # Reproducers: test_a_refused_commit_does_not_report_success, and its
    # negative control test_a_clean_successful_run_still_exits_zero.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
