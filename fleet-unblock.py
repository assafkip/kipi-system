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
    if index_sha and index_sha == work_sha and index_mode != work_mode:
        return "restore-mode", (
            f"same blob {index_sha[:12]}, mode {work_mode or '?'} on disk vs "
            f"{index_mode} in index; chmod back, never commit the broken mode"
        )

    if row["kind"] == "fleet-written":
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
    was_staged = set()
    for path in paths:
        if git(repo, "diff", "--cached", "--quiet", "--", path)[0] != 0:
            was_staged.add(path)

    def unwind():
        for path in paths:
            if path not in was_staged:
                git(repo, "restore", "--staged", "--", path)

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
    parser.add_argument("--message", default=(
        "chore(fleet): commit updater exhaust its writer never committed\n\n"
        "Written by kipi update, never committed, so the dirty-tree guard "
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
            acted += 1
            print(f"    -> {action:12s} {path}: {outcome}")
        print()

    print(f"acted on {acted} path(s); refused {refused} path(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
