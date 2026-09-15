## Verdict: REQUEST CHANGES

Reviewer engine: `codex`. Full review on disk: `/Users/assafkipnis/.config/kipi/pr-reviews/codex/assafkip_kipi-system__pr-165-20260814-173102.md` (253197 bytes).

```
FINDINGS:
major|A rejected commit overwrites an already-staged version instead of restoring it despite reporting index unwound|fleet-unblock.py:233
major|Git add and restore failures are counted as successful actions so the command can exit zero after repairing nothing|fleet-unblock.py:317
END FINDINGS
```

--- reviewer output, last 54697 bytes of 253197 (full review at the path above) ---

167:    staged-only     staged, and the worktree agrees with the index. Unstaging
178:        return "staged-only"
182:def audit_instance(entry, owned, skel_blobs, cleared=()):
189:        "blocked_by": [],
199:    spec = guard_pathspec(prefix, owned, cleared)
213:        result["blocked_by"].append(
216:    kinds = {row["kind"] for row in result["blocked_by"]}
235:    skel_blobs = SkeletonBlobs(skeleton)
270:        for item in row["blocked_by"]:
#!/usr/bin/env python3
"""Why the fleet cannot receive an update, per instance, read-only.

`kipi update` reports "Failed: N" without saying whether the blocker is founder
work (correct refusal) or the updater's own abandoned exhaust (a defect). Four
of 23 instances received the 2026-08-14 skeleton; this answers WHY for the
other 19 in one pass, and gives the before/after number that any fix has to
move.

REPLICATES THE GUARD, DOES NOT APPROXIMATE IT. The refusal at kipi-update.sh
"Refuse tracked work in progress" is two `git diff --quiet` calls over the
pathspec `<prefix>/ .claude/ plugins/` minus the instance-owned subtrees. A
`git status` grep answers a DIFFERENT question -- it counts untracked files and
paths outside the sync scope, neither of which the guard reads -- so this runs
the same two commands with the same pathspec instead. INSTANCE_OWNED_SUBTREES
is parsed out of kipi-update.sh rather than transcribed, because a
hand-transcribed copy is how the audit and the guard would come to disagree
about what is blocking.

Writes nothing anywhere. Every git call is a read.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

SKELETON = pathlib.Path(__file__).resolve().parent


def git(repo, *args, check=False):
    """Read-only git. Returns stdout, or "" when the call fails."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {repo}: {proc.stderr.strip()}")
    return proc.stdout


def instance_owned_subtrees(updater):
    """Parse INSTANCE_OWNED_SUBTREES out of kipi-update.sh.

    Derived, never transcribed. A second hand-written copy of this list is how
    the audit would start naming a path as "blocking" that the real guard
    excludes, and the audit exists to be trusted about exactly that.
    """
    text = updater.read_text(encoding="utf-8")
    match = re.search(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise RuntimeError(
            f"INSTANCE_OWNED_SUBTREES not found in {updater}; the audit cannot "
            "build the guard's pathspec and refuses to guess it"
        )
    subs = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    if not subs:
        raise RuntimeError(f"INSTANCE_OWNED_SUBTREES parsed empty from {updater}")
    return subs


def never_commit_paths(updater):
    """SYSTEM_NEVER_COMMIT, parsed from kipi-update.sh.

    Feeds --after. Parsed rather than transcribed for the same reason the
    subtree list is: a second copy is how the projection would start crediting
    a fix the updater does not actually apply.
    """
    text = updater.read_text(encoding="utf-8")
    match = re.search(r"^SYSTEM_NEVER_COMMIT=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise RuntimeError(f"SYSTEM_NEVER_COMMIT not found in {updater}")
    paths = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line.strip('"').strip("'"))
    return paths


def guard_pathspec(prefix, owned, cleared=()):
    """The exact pathspec the dirty-tree guard uses.

    `cleared` is how --after models the one-time untrack migration. Excluding a
    path from the pathspec makes git answer the question the migration creates
    -- "would this instance sync if that path were not tracked?" -- and GIT
    answers it, against the real repo. Subtracting the paths by hand from the
    blocking list would be arithmetic on my own classifier instead, which is
    the part most likely to be wrong.
    """
    spec = [f"{prefix}/", ".claude/", "plugins/"] if prefix else [".claude/", "plugins/"]
    if prefix:
        spec += [f":(exclude){prefix}/{sub}/" for sub in owned]
    spec += [f":(exclude){path}" for path in cleared]
    return spec


def name_status(repo, pathspec, cached):
    """Blocking paths as (status, path), from the guard's own diff."""
    args = ["diff", "--name-status"]
    if cached:
        args.append("--cached")
    out = git(repo, *args, "--", *pathspec)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[-1]))
    return rows


class SkeletonBlobs:
    """Was this exact blob ever written by the skeleton at this exact path?

    The proof that a change is fleet-written rather than founder-written. A
    founder hand-edit does not produce bytes that collide with a blob the
    skeleton itself once held at the same path, so a hit here is evidence the
    updater wrote the file and never committed it.

    Scoped per path and memoised: a single file's own history is short, while
    walking every commit in the skeleton to build one big index is not.
    """

    def __init__(self, skeleton):
        self.skeleton = skeleton
        self._cache = {}

    def shas_for(self, path):
        if path not in self._cache:
            shas = set()
            commits = git(self.skeleton, "rev-list", "--all", "--", path).split()
            for commit in commits:
                sha = git(self.skeleton, "rev-parse", "-q", "--verify",
                          f"{commit}:{path}").strip()
                if sha:
                    shas.add(sha)
            self._cache[path] = shas
        return self._cache[path]

    def wrote(self, path, sha):
        return bool(sha) and sha in self.shas_for(path)


def blob_sha(repo, path, source):
    """Blob sha of a path in the index or the worktree. "" when absent."""
    if source == "index":
        out = git(repo, "ls-files", "-s", "--", path).split()
        return out[1] if len(out) >= 2 else ""
    full = pathlib.Path(repo) / path
    if not full.is_file():
        return ""
    return git(repo, "hash-object", "--", str(full)).strip()


def classify(repo, path, staged, skel_blobs):
    """Why this path is blocking, and whether a fix may touch it.

    Three answers, and the distinction is the point of the audit:

    fleet-written   the blob is one the skeleton itself once held at this path.
                    Provably updater exhaust, never committed by its writer.
    staged-only     staged, and the worktree agrees with the index. Unstaging
                    restores the HEAD index entry and leaves the file on disk
                    byte-for-byte, so it cannot lose work.
    founder         everything else. Not ours to clear, and named in the report
                    so a refusal over it is legible rather than mysterious.
    """
    index_sha = blob_sha(repo, path, "index")
    work_sha = blob_sha(repo, path, "worktree")
    if skel_blobs.wrote(path, index_sha) or skel_blobs.wrote(path, work_sha):
        return "fleet-written"
    if staged and index_sha and index_sha == work_sha:
        return "staged-only"
    return "founder"


def audit_instance(entry, owned, skel_blobs, cleared=()):
    path = pathlib.Path(entry["path"])
    prefix = entry.get("subtree_prefix") or ""
    result = {
        "name": entry["name"],
        "path": str(path),
        "prefix": prefix,
        "blocked_by": [],
        "verdict": None,
    }
    if not path.exists():
        result["verdict"] = "MISSING"
        return result
    if not (path / ".git").exists():
        result["verdict"] = "NOT-A-REPO"
        return result

    spec = guard_pathspec(prefix, owned, cleared)
    rows = ([(s, p, True) for s, p in name_status(path, spec, cached=True)] +
            [(s, p, False) for s, p in name_status(path, spec, cached=False)])
    if not rows:
        result["verdict"] = "WOULD-SYNC"
        return result

    seen = {}
    for status, rel, staged in rows:
        kind = classify(path, rel, staged, skel_blobs)
        # A path dirty in BOTH index and worktree keeps the stricter answer:
        # a founder edit riding on top of fleet-written bytes is founder work.
        if seen.get(rel) != "founder":
            seen[rel] = kind
        result["blocked_by"].append(
            {"status": status, "path": rel, "staged": staged, "kind": seen[rel]}
        )
    kinds = {row["kind"] for row in result["blocked_by"]}
    result["verdict"] = "BLOCKED-FOUNDER" if "founder" in kinds else "BLOCKED-FLEET"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--skeleton", default=str(SKELETON))
    parser.add_argument(
        "--after", action="store_true",
        help="model the SYSTEM_NEVER_COMMIT untrack migration: report reach "
             "as if those paths were no longer tracked in each instance")
    args = parser.parse_args()

    skeleton = pathlib.Path(args.skeleton).resolve()
    updater = skeleton / "kipi-update.sh"
    registry = skeleton / "instance-registry.json"
    owned = instance_owned_subtrees(updater)
    skel_blobs = SkeletonBlobs(skeleton)

    entries = [
        i for i in json.loads(registry.read_text())["instances"]
        if not str(i.get("status", "")).startswith("merged")
        and i.get("skeleton_managed") is not False
    ]
    cleared = never_commit_paths(updater) if args.after else ()
    if cleared:
        print("MODE: --after, modelling the untrack migration for:")
        for path in cleared:
            print(f"  {path}")
        print()
    results = [audit_instance(e, owned, skel_blobs, cleared) for e in entries]

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    order = {"WOULD-SYNC": 0, "BLOCKED-FLEET": 1, "BLOCKED-FOUNDER": 2}
    counts = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    print(f"registered, skeleton-managed : {len(results)}")
    for verdict in sorted(counts, key=lambda v: order.get(v, 9)):
        print(f"  {verdict:16s} {counts[verdict]}")
    print()
    print(f"REACH: {counts.get('WOULD-SYNC', 0)} of {len(results)} would sync now")
    print()

    for row in sorted(results, key=lambda r: (order.get(r["verdict"], 9), r["name"])):
        if row["verdict"] == "WOULD-SYNC":
            continue
        print(f"{row['name']}  [{row['verdict']}]")
        for item in row["blocked_by"]:
            where = "index " if item["staged"] else "wtree "
            print(f"    {item['status']:2s} {where} {item['kind']:14s} {item['path']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
   190	    to_commit = [p for a, p, _ in plan if a == "commit"]
   191	    to_unstage = [p for a, p, _ in plan if a == "unstage"]
   192	    to_chmod = [(p, r) for a, p, r in plan if a == "restore-mode"]
   193	
   194	    for path, _reason in to_chmod:
   195	        mode = entry_mode(repo, path, "index")
   196	        if not apply:
   197	            done.append(("restore-mode", path, f"would chmod to {mode}"))
   198	            continue
   199	        bits = 0o755 if mode == "100755" else 0o644
   200	        (pathlib.Path(repo) / path).chmod(bits)
   201	        still = entry_mode(repo, path, "worktree")
   202	        done.append(("restore-mode", path,
   203	                     "clean" if still == mode else f"STILL {still}"))
   204	
   205	    for path in to_unstage:
   206	        if not apply:
   207	            done.append(("unstage", path, "would restore --staged"))
   208	            continue
   209	        rc, _, err = git(repo, "restore", "--staged", "--", path)
   210	        done.append(("unstage", path, "clean" if rc == 0 else f"FAILED {err.strip()}"))
   211	
   212	    if to_commit:
   213	        if not apply:
   214	            for path in to_commit:
   215	                done.append(("commit", path, "would stage + commit"))
   216	        else:
   217	            done += commit_with_unwind(repo, to_commit, message)
   218	    return done
   219	
   220	
   221	def commit_with_unwind(repo, paths, message):
   222	    """Stage and commit `paths`, restoring the prior index if the commit fails.
   223	
   224	    A commit here runs the INSTANCE's pre-commit hooks, and two of the five
   225	    instances have them. A hook exiting non-zero must not leave the index in a
   226	    state nobody chose: the founder would come back to paths staged by a script
   227	    that then reported failure. So the pre-run staged set is recorded first and
   228	    restored on any failure.
   229	
   230	    Never --no-verify. A hook that refuses this commit is a hook doing its job,
   231	    and the correct outcome is a refusal that says so.
   232	    """
   233	    was_staged = set()
   234	    for path in paths:
   235	        if git(repo, "diff", "--cached", "--quiet", "--", path)[0] != 0:
   236	            was_staged.add(path)
   237	
   238	    def unwind():
   239	        for path in paths:
   240	            if path not in was_staged:
   241	                git(repo, "restore", "--staged", "--", path)
   242	
   243	    rc, _, err = git(repo, "add", "--", *paths)
   244	    if rc != 0:
   245	        unwind()
   246	        return [("commit", p, f"FAILED add: {err.strip()}") for p in paths]
   247	
   248	    rc, _, err = git(repo, "commit", "-m", message, "--", *paths)
   249	    if rc != 0:
   250	        unwind()
   251	        detail = (err.strip() or "hook or commit refused").splitlines()[-1:]
   252	        return [("commit", p, f"REFUSED (index unwound): {detail}") for p in paths]
   253	    return [("commit", p, "committed") for p in paths]
   254	
   255	
   256	def main():
   257	    parser = argparse.ArgumentParser(description=__doc__)
   258	    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
   259	    parser.add_argument("--skeleton", default=str(SKELETON))
   260	    parser.add_argument("--only", action="append", default=[],
   261	                        help="limit to these instance names (repeatable)")
   262	    # The [no-issue:] token is NOT a bypass added to get past a gate. One client
   263	    # engagement's instance requires every commit to name a Linear issue in THAT
   264	    # instance's project, and this commit is fleet exhaust: it has no issue there
   265	    # and should not be given a fake one, which is the failure mode that gate's
   266	    # own presence-check invites. Its script carries a first-class hatch
   267	    # (BYPASS_RE, reason required), and the updater's own system-state commits
   268	    # already use it. Instances without the gate ignore the token.
   269	    parser.add_argument("--message", default=(
   270	        "chore(fleet): commit updater exhaust its writer never committed "
   271	        "[no-issue: fleet updater exhaust, no issue in this instance]\n\n"
   272	        "Written by the fleet updater, never committed, so the dirty-tree guard "
   273	        "refused every later sync. Attributed by fleet-unblock.py: each blob "
   274	        "here is one the skeleton itself held at this exact path."))
   275	    args = parser.parse_args()
   276	
   277	    skeleton = pathlib.Path(args.skeleton).resolve()
   278	    audit = load_audit(skeleton)
   279	    owned = audit.instance_owned_subtrees(skeleton / "kipi-update.sh")
   280	    audit.SKEL_BLOBS = audit.SkeletonBlobs(skeleton)
   281	    rescued = RescuedBlobs(skeleton)
   282	
   283	    registry = json.loads((skeleton / "instance-registry.json").read_text())
   284	    entries = [
   285	        i for i in registry["instances"]
   286	        if not str(i.get("status", "")).startswith("merged")
   287	        and i.get("skeleton_managed") is not False
   288	        and (not args.only or i["name"] in args.only)
   289	    ]
   290	
   291	    print(f"MODE: {'APPLY' if args.apply else 'dry run'}\n")
   292	    refused = 0
   293	    failed = 0
   294	    acted = 0
   295	    for entry in entries:
   296	        result = audit.audit_instance(entry, owned, audit.SKEL_BLOBS)
   297	        if result["verdict"] not in ("BLOCKED-FLEET", "BLOCKED-FOUNDER"):
   298	            continue
   299	        repo = pathlib.Path(entry["path"])
   300	        plan = []
   301	        for row in result["blocked_by"]:
   302	            action, reason = decide(repo, row, audit, rescued)
   303	            plan.append((action, row["path"], reason))
   304	
   305	        print(f"{entry['name']}  [{result['verdict']}]")
   306	        for action, path, reason in plan:
   307	            if action == "refuse":
   308	                refused += 1
   309	                print(f"    REFUSE  {path}\n              {reason}")
   310	        actionable = [p for p in plan if p[0] != "refuse"]
   311	        for action, path, reason in actionable:
   312	            print(f"    {action:12s} {path}\n              {reason}")
   313	        for action, path, outcome in apply_instance(repo, actionable, args.apply, args.message):
   314	            # A REFUSED outcome is not an action (PR #165 review, major).
   315	            # Counting it toward `acted` made "acted on 3 path(s)" the printed
   316	            # result of a run that repaired nothing.
   317	            if outcome.startswith("REFUSED"):
   318	                failed += 1
   319	            else:
   320	                acted += 1
   321	            print(f"    -> {action:12s} {path}: {outcome}")
   322	        print()
   323	
   324	    print(f"acted on {acted} path(s); refused {refused} path(s)"
   325	          + (f"; {failed} action(s) FAILED" if failed else ""))
   326	    # NON-ZERO WHEN AN ACTION WE ACCEPTED THEN FAILED (PR #165 review, major).
   327	    #
   328	    # `refused` is a decision and is a SUCCESSFUL outcome: the script looked,
   329	    # could not attribute the change, and correctly left it alone. `failed` is
   330	    # different -- the script accepted the path, tried, and the repair did not
   331	    # happen (a pre-commit hook rejected it). Exiting 0 there tells an unattended
   332	    # fleet job the run succeeded while every instance stays blocked, which is
   333	    # the silent-success class this whole effort exists to end.
   334	    #
   335	    # Reproducers: test_a_refused_commit_does_not_report_success, and its
   336	    # negative control test_a_clean_successful_run_still_exits_zero.
   337	    return 1 if failed else 0
   338	
   339	
   340	if __name__ == "__main__":
   341	    sys.exit(main())
     1	#!/usr/bin/env python3
     2	"""Ship the skeleton's instance-local-never-commit stanza into an instance's
     3	root .gitignore, as a managed block.
     4	
     5	WHY (sp-097d2e23, sp-bd9bae14, measured 2026-08-14). The skeleton's root
     6	.gitignore says three things must never be committed, and says why:
     7	
     8	  * claude-integrity-baseline.json  -- instance-local (ASK-282); a shared
     9	    baseline can never match and Slack-pages every instance daily.
    10	  * .claude-integrity-armed         -- a committed marker makes a fresh
    11	    instance claim prior arming, refuse to arm, and page SECURITY on its
    12	    first run (the ASK-291 round-2 outage).
    13	  * q-system/output/.update-check-* -- daily update stamps, pure exhaust.
    14	
    15	Root .gitignore is NOT in the updater's sync set (the set is q-system/,
    16	.claude/{agents,output-styles,rules}/*.md, .claude/settings.json, plugins/),
    17	so no instance has ever received those rules. In the skeleton the gitignore
    18	makes those paths invisible to `git status`; in an instance it does not, so
    19	auto-commit.py sees them, classifies `q-system/.q-system/` as ("chore",
    20	"update system infrastructure"), and commits them unattended.
    21	
    22	That is not hypothetical. Measured across the 22 skeleton-managed instances:
    23	five had already committed the baseline and/or the armed marker, the most
    24	recent at 2026-08-14 14:22 under exactly that subject line. The two spillover
    25	notes were filed as separate minor defects; they are one defect, and the
    26	gitignore gap is the cause rather than a cosmetic side effect.
    27	
    28	DERIVED, NOT TRANSCRIBED. The stanza is parsed out of the skeleton's own root
    29	.gitignore between the two markers, so adding a fourth never-commit path there
    30	cannot leave this script behind. Same discipline the preserve scan adopted for
    31	INSTANCE_OWNED_PATHS in sp-3d5a247e, and for the same reason: a hand-kept
    32	second copy of a list drifts the moment anyone adds an entry.
    33	
    34	Refuses loudly rather than falling back to a literal. A silent fallback would
    35	write a block that does not match what the skeleton actually declares, and the
    36	failure mode -- an instance quietly committing its own tripwire state again --
    37	is invisible until something pages.
    38	
    39	Idempotent: rewrites the managed block in place, leaving every other line of
    40	the instance's .gitignore untouched. An instance that already ignores one of
    41	these paths on its own keeps that line; the block is additive.
    42	
    43	Usage:
    44	  kipi-update-gitignore-block.py --skeleton DIR --instance DIR [--check]
    45	
    46	  --check  report whether the block is current, write nothing. Exit 0 when
    47	           the instance block already matches the skeleton stanza, 1 when it
    48	           would change.
    49	"""
    50	import argparse
    51	import os
    52	import re
    53	import sys
    54	
    55	BEGIN = "# >>> kipi-managed: instance-local, never commit >>>"
    56	END = "# <<< kipi-managed: instance-local, never commit <<<"
    57	
    58	# The markers as they appear in the SKELETON's .gitignore. Kept distinct from
    59	# the block markers written into an instance so that the skeleton's own copy is
    60	# never mistaken for a managed block and rewritten by a stray --instance run
    61	# pointed at the skeleton.
    62	SKELETON_BEGIN = "# >>> kipi-instance-local-stanza >>>"
    63	SKELETON_END = "# <<< kipi-instance-local-stanza <<<"
    64	
    65	
    66	def skeleton_stanza(skeleton_dir):
    67	    """The never-commit path lines declared by the skeleton's root .gitignore."""
    68	    path = os.path.join(skeleton_dir, ".gitignore")
    69	    try:
    70	        with open(path, encoding="utf-8") as handle:
    71	            text = handle.read()
    72	    except OSError as exc:
    73	        raise RuntimeError(f"cannot read skeleton .gitignore at {path}: {exc}")
    74	    match = re.search(
    75	        re.escape(SKELETON_BEGIN) + r"\n(.*?)^" + re.escape(SKELETON_END),
    76	        text,
    77	        re.S | re.M,
    78	    )
    79	    if not match:
    80	        raise RuntimeError(
    81	            f"{SKELETON_BEGIN} markers not found in {path}; the gitignore block "
    82	            "writer cannot mirror the skeleton's never-commit stanza and refuses "
    83	            "to guess it"
    84	        )
    85	    lines = [line.rstrip() for line in match.group(1).splitlines()]
    86	    # Comments inside the stanza are the WHY, and an instance reading its own
    87	    # .gitignore deserves them as much as the skeleton does. Blank lines are
    88	    # dropped so the emitted block is stable regardless of skeleton spacing.
    89	    lines = [line for line in lines if line.strip()]
    90	    if not any(line and not line.startswith("#") for line in lines):
    91	        raise RuntimeError(
    92	            f"the stanza between the markers in {path} declares no paths; "
    93	            "refusing to write an empty managed block"
    94	        )
    95	    return lines
    96	
    97	
    98	def render_block(stanza):
    99	    return "\n".join([BEGIN] + stanza + [END]) + "\n"
   100	
   101	
   102	def existing_block(text):
   103	    """(before, block, after) for the managed block, or None when absent."""
   104	    match = re.search(
   105	        re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?",
   106	        text,
   107	        re.S | re.M,
   108	    )
   109	    if not match:
   110	        return None
   111	    return text[: match.start()], match.group(0), text[match.end():]
   112	
   113	
   114	def apply_block(instance_dir, stanza, check_only=False):
   115	    """Write/refresh the managed block. Returns (changed, action)."""
   116	    path = os.path.join(instance_dir, ".gitignore")
   117	    try:
   118	        with open(path, encoding="utf-8") as handle:
   119	            text = handle.read()
   120	    except FileNotFoundError:
   121	        text = ""
   122	    except OSError as exc:
   123	        raise RuntimeError(f"cannot read {path}: {exc}")
   124	
   125	    block = render_block(stanza)
   126	    found = existing_block(text)
   127	    if found is None:
   128	        # Append. A leading newline only when the file has content and does not
   129	        # already end in one, so repeated runs cannot grow blank lines.
   130	        prefix = text
   131	        if prefix and not prefix.endswith("\n"):
   132	            prefix += "\n"
   133	        if prefix:
   134	            prefix += "\n"
   135	        new_text = prefix + block
   136	        action = "added"
   137	    else:
   138	        before, current, after = found
   139	        if current.rstrip("\n") == block.rstrip("\n"):
   140	            return False, "current"
   141	        new_text = before + block + after
   142	        action = "refreshed"
   143	
   144	    if check_only:
   145	        return True, action
   146	
   147	    tmp = path + ".kipi-tmp"
   148	    with open(tmp, "w", encoding="utf-8") as handle:
   149	        handle.write(new_text)
   150	    os.replace(tmp, path)
   151	    return True, action
   152	
   153	
   154	def main(argv=None):
   155	    ap = argparse.ArgumentParser(description=__doc__)
   156	    ap.add_argument("--skeleton", required=True)
   157	    ap.add_argument("--instance", required=True)
   158	    ap.add_argument("--check", action="store_true")
   159	    args = ap.parse_args(argv)
   160	
   161	    if os.path.abspath(args.skeleton) == os.path.abspath(args.instance):
   162	        print("refusing to write a managed block into the skeleton itself",
   163	              file=sys.stderr)
   164	        return 2
   165	
   166	    try:
   167	        stanza = skeleton_stanza(args.skeleton)
   168	        changed, action = apply_block(args.instance, stanza, args.check)
   169	    except RuntimeError as exc:
   170	        print(f"ERROR: {exc}", file=sys.stderr)
   171	        return 2
   172	
   173	    if args.check:
   174	        if changed:
   175	            print(f"  .gitignore managed block would be {action}")
   176	            return 1
   177	        return 0
   178	
   179	    if changed:
   180	        print(f"  .gitignore managed block {action} "
   181	              f"({sum(1 for l in stanza if not l.startswith('#'))} path(s))")
   182	    return 0
   183	
   184	
   185	if __name__ == "__main__":
   186	    raise SystemExit(main())
diff --git a/kipi-update-preserve-scan.py b/kipi-update-preserve-scan.py
index a869a2fe..fcf5d5b2 100644
--- a/kipi-update-preserve-scan.py
+++ b/kipi-update-preserve-scan.py
@@ -35,14 +35,43 @@ import sys
 # stale skeleton copy from the old `git subtree add` creation path). Listing it
 # here stops this scanner from flagging shadow-tree files as preserve-candidates,
 # so the updater's rsync --delete can actually remove them (fleet cleanup 2026-07-01).
-EXCLUDED_PREFIXES = (
-    "my-project/",
-    "canonical/",
-    "memory/",
-    "output/",
-    ".q-system/agent-pipeline/bus/",
-    "q-system/",
-)
+def _owned_subtrees():
+    """INSTANCE_OWNED_SUBTREES, parsed out of kipi-update.sh.
+
+    DERIVED, NOT TRANSCRIBED (sp-3d5a247e). The comment above has always claimed
+    this list mirrors the updater's excludes "exactly"; measured 2026-08-14 it
+    was missing `research` and `.q-system/data`, so the claim had been false for
+    as long as those two entries had existed. A hand-kept second copy of a list
+    that lives somewhere else drifts the moment anyone adds an entry, and a
+    comment asserting the mirror is worse than no comment: it is read as
+    coverage, so nobody goes looking.
+
+    Refuses loudly rather than falling back to a literal. A silent fallback here
+    would preserve a file the updater is about to delete, or skip one it is not
+    permitted to touch, with nothing on screen either way.
+    """
+    import re
+    updater = os.path.join(os.path.dirname(os.path.abspath(__file__)),
+                           "kipi-update.sh")
+    with open(updater, encoding="utf-8") as handle:
+        text = handle.read()
+    match = re.search(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", text, re.S | re.M)
+    if not match:
+        raise RuntimeError(
+            f"INSTANCE_OWNED_SUBTREES not found in {updater}; the preserve scan "
+            "cannot mirror the updater's excludes and refuses to guess them"
+        )
+    subs = [line.strip() for line in match.group(1).splitlines() if line.strip()]
+    if not subs:
+        raise RuntimeError(f"INSTANCE_OWNED_SUBTREES parsed empty from {updater}")
+    return tuple(f"{sub}/" for sub in subs)
+
+
+# The updater's own instance-owned subtrees, plus one entry that is NOT an rsync
+# exclude: "q-system/" is the forbidden nested shadow tree described above, and
+# it is excluded here for a different reason. Kept separate so the derived half
+# stays a faithful mirror.
+EXCLUDED_PREFIXES = _owned_subtrees() + ("q-system/",)
 
 
 def is_excluded(rel):
diff --git a/kipi-update.sh b/kipi-update.sh
index eb247506..ae63f889 100755
--- a/kipi-update.sh
+++ b/kipi-update.sh
@@ -1610,6 +1610,40 @@ PY
       git merge --abort 2>/dev/null || true
     fi
 
+    # THE OTHER HALF OF THE UNTRACK BELOW, and it must run FIRST (sp-097d2e23).
+    #
+    # `git rm --cached` leaves the file on disk, UNTRACKED. In the skeleton that
+    # is invisible, because root .gitignore has covered these paths since
+    # .gitignore:123. No instance has ever had those lines: root .gitignore is
+    # not in this script's sync set (q-system/, .claude/{agents,output-styles,
+    # rules}/*.md, .claude/settings.json, plugins/). So on an instance the
+    # untracked marker is REPORTED by git status, auto-commit.py classifies
+    # q-system/.q-system/ as `chore` exhaust, and the next ordinary session
+    # commits it straight back. The migration below would then have to run
+    # again, and again, forever.
+    #
+    # That is not a prediction. SYSTEM_NEVER_COMMIT closes this script's own
+    # commit path; the commit that re-added the marker to an instance at
+    # 2026-08-14 14:22 carried auto-commit.py's subject ("chore: update system
+    # infrastructure"), not this script's ("...before skeleton sync"). Two
+    # writers, and the array only ever guarded one of them.
+    #
+    # Ignoring the path guards every writer at once -- this script, the Stop
+    # hook, a stray `git add -A`, the founder's own commit -- because it works
+    # at the layer all of them read. The stanza is PARSED from the skeleton's
+    # own .gitignore, so adding a fourth never-commit path there reaches all 22
+    # instances without touching this file.
+    #
+    # Advisory: an instance that cannot take the block is not a reason to
+    # abandon an otherwise good update, and the untrack below still runs.
+    GITIGNORE_BLOCK="$SCRIPT_DIR/kipi-update-gitignore-block.py"
+    if [ -f "$GITIGNORE_BLOCK" ]; then
+      python3 "$GITIGNORE_BLOCK" --skeleton "$SCRIPT_DIR" --instance "$path" ||
+        echo "    WARN: could not write the .gitignore managed block; never-commit paths stay visible to auto-commit here"
+    else
+      echo "    WARN: .gitignore block writer missing; never-commit paths stay visible to auto-commit here"
+    fi
+
     # ONE-TIME MIGRATION, and it must run BEFORE the block below (measured 2026-08-14, 6 instances).
     #
     # The chokepoint stops the baseline from BECOMING tracked. It does nothing for
diff --git a/q-system/hooks/auto-commit.py b/q-system/hooks/auto-commit.py
index 0c3e5d10..4c12ac59 100755
--- a/q-system/hooks/auto-commit.py
+++ b/q-system/hooks/auto-commit.py
@@ -39,6 +39,31 @@ AREA_MAP = [
     (".claude/agents/",               "chore",    "update agent definitions"),
     (".claude/output-styles/",        "chore",    "update output styles"),
     (".claude/settings",              "chore",    "update settings"),
+    # sp-097d2e23. The updater writes a managed never-commit block into every
+    # instance's root .gitignore. Every instance HAS one already (70-76 lines)
+    # and it is TRACKED, so the writer MODIFIES a tracked file -- measured on a
+    # real copy of an instance, where it lands as ` M .gitignore`.
+    #
+    # (An earlier version of this comment said instances have no root .gitignore
+    # at all. That was a misread of a malformed `grep -c` check, corrected the
+    # same day by copying a real instance and looking. The fix below was right;
+    # the reason written beside it was not, which is worse than no reason --
+    # a wrong scar comment is read as coverage, so nobody goes looking.)
+    #
+    # This classifier answered `unclassified` for .gitignore, which means
+    # REPORTED and never committed (ASK-498). So every one of the 22 instances
+    # would carry a permanently modified, never-committable tracked file and
+    # print the same unclassifiable path on every run, forever.
+    #
+    # It does NOT block the sync: the dirty-tree guard is scoped to
+    # `$prefix/ .claude/ plugins/` (kipi-update.sh ~L2012) and root .gitignore
+    # is in none of them. Checked rather than assumed, because the first guess
+    # was that this self-blocked the whole fleet.
+    #
+    # `chore`, so the fleet sync may take it: system exhaust, not authored
+    # content. Config, never source, so the executable-source refusal above
+    # does not reach it.
+    (".gitignore",                    "chore",    "update gitignore"),
     ("sites/",                        "feat",     "update site pages"),
     ("memory/",                       "chore",    "update auto-memory"),
 ]

exec
/bin/zsh -lc "sed -n '105,155p' .gitignore; rg -n \"SYSTEM_NEVER_COMMIT|GITIGNORE_BLOCK|system_state_paths|gitignore\" kipi-update.sh q-system/hooks/auto-commit.py; sed -n '1560,1705p' kipi-update.sh; sed -n '1,240p' q-system/hooks/auto-commit.py; pytest -q test_fleet_unblock.py q-system/.q-system/tests/test_gitignore_block.py test_destructive_op_deny_anchor.py" in /Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165
 exited 1 in 118ms:
Traceback (most recent call last):
  File "/opt/homebrew/bin/pytest", line 6, in <module>
    sys.exit(console_main())
             ~~~~~~~~~~~~^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/config/__init__.py", line 223, in console_main
    code = main()
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/config/__init__.py", line 193, in main
    config = _prepareconfig(new_args, plugins)
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/config/__init__.py", line 361, in _prepareconfig
    config: Config = pluginmanager.hook.pytest_cmdline_parse(
                     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pluginmanager=pluginmanager, args=args
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
    ~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/helpconfig.py", line 124, in pytest_cmdline_parse
    config = yield
             ^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1192, in pytest_cmdline_parse
    self.parse(args)
    ~~~~~~~~~~^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1562, in parse
    self.hook.pytest_load_initial_conftests(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        early_config=self, args=args, parser=self._parser
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
    ~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/warnings.py", line 128, in pytest_load_initial_conftests
    return (yield)
            ^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/pluggy/_callers.py", line 116, in _multicall
    next(function_gen)  # first yield
    ~~~~^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/capture.py", line 170, in pytest_load_initial_conftests
    capman.start_global_capturing()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/capture.py", line 773, in start_global_capturing
    self._global_capturing = _get_multicapture(self._method)
                             ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/capture.py", line 714, in _get_multicapture
    return MultiCapture(in_=FDCapture(0), out=FDCapture(1), err=FDCapture(2))
                                              ~~~~~~~~~^^^
  File "/opt/homebrew/lib/python3.14/site-packages/_pytest/capture.py", line 493, in __init__
    TemporaryFile(buffering=0),
    ~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 652, in TemporaryFile
    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
                                       ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 127, in _sanitize_params
    dir = gettempdir()
  File "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 312, in gettempdir
    return _os.fsdecode(_gettempdir())
                        ~~~~~~~~~~~^^
  File "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 305, in _gettempdir
    tempdir = _get_default_tempdir()
  File "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 222, in _get_default_tempdir
    raise FileNotFoundError(_errno.ENOENT,
                            "No usable temporary directory found in %s" %
                            dirlist)
FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165']

codex
The shipped tests cannot start because the managed environment exposes no writable temporary directory. I’m continuing with non-mutating executable probes against the checked-out code itself. For the fleet dry-run probe, `fleet-unblock.py` reads instance paths listed in this project’s `instance-registry.json`; those directories are outside the review tree, and I’m using them only to verify the command’s real operator output without `--apply`.
exec
/bin/zsh -lc "python3 -c \"import importlib.util,pathlib; p=pathlib.Path('fleet-unblock.py').resolve(); s=importlib.util.spec_from_file_location('fleet_unblock',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.commit_with_unwind('/definitely/not/a/repo',['plugins/prd-os/runner.py'],'repro')); outcome='FAILED add: fatal'; failed=0; acted=0; failed = failed+1 if outcome.startswith('REFUSED') else failed; acted = acted if outcome.startswith('REFUSED') else acted+1; print(f'current main accounting => acted={acted} failed={failed} exit={1 if failed else 0}')\"" in /Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165
 succeeded in 0ms:
[('commit', 'plugins/prd-os/runner.py', "FAILED add: fatal: cannot change to '/definitely/not/a/repo': No such file or directory")]
current main accounting => acted=1 failed=0 exit=0

exec
/bin/zsh -lc "python3 -c \"import importlib.util,pathlib; p=pathlib.Path('fleet-unblock.py').resolve(); s=importlib.util.spec_from_file_location('fleet_unblock',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); state={'index':'staged-v1'}; calls=[]; orig='staged-v1';
def_git=lambda repo,*a: ((calls.append(a) or (1,'','')) if a[:3]==('diff','--cached','--quiet') else ((state.__setitem__('index','worktree-v2') or calls.append(a) or (0,'','')) if a[0]=='add' else ((calls.append(a) or (1,'','hook rejected')) if a[0]=='commit' else ((state.__setitem__('index','HEAD') or calls.append(a) or (0,'','')) if a[0]=='restore' else (0,'','')))); m.git=def_git; print(m.commit_with_unwind('/repo',['plugins/prd-os/runner.py'],'msg')); print('index before:',orig); print('index after: ',state['index']); print('git calls:',calls)\"" in /Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165
 exited 1 in 0ms:
  File "<string>", line 2
    def_git=lambda repo,*a: ((calls.append(a) or (1,'','')) if a[:3]==('diff','--cached','--quiet') else ((state.__setitem__('index','worktree-v2') or calls.append(a) or (0,'','')) if a[0]=='add' else ((calls.append(a) or (1,'','hook rejected')) if a[0]=='commit' else ((state.__setitem__('index','HEAD') or calls.append(a) or (0,'','')) if a[0]=='restore' else (0,'','')))); m.git=def_git; print(m.commit_with_unwind('/repo',['plugins/prd-os/runner.py'],'msg')); print('index before:',orig); print('index after: ',state['index']); print('git calls:',calls)
                                                                                                                                                                                                                                                                                                                                                                                      ^
SyntaxError: invalid syntax

exec
/bin/zsh -lc 'python3 -c $'"'import importlib.util, pathlib\\np=pathlib.Path(\"fleet-unblock.py\").resolve()\\ns=importlib.util.spec_from_file_location(\"fleet_unblock\",p)\\nm=importlib.util.module_from_spec(s)\\ns.loader.exec_module(m)\\nstate={\"index\":\"staged-v1\"}\\ncalls=[]\\ndef fake(repo,*a):\\n    calls.append(a)\\n    if a[:3] == (\"diff\",\"--cached\",\"--quiet\"): return (1,\"\",\"\")\\n    if a[0] == \"add\": state[\"index\"]=\"worktree-v2\"; return (0,\"\",\"\")\\n    if a[0] == \"commit\": return (1,\"\",\"hook rejected\")\\n    if a[0] == \"restore\": state[\"index\"]=\"HEAD\"; return (0,\"\",\"\")\\n    return (0,\"\",\"\")\\nm.git=fake\\nprint(m.commit_with_unwind(\"/repo\",[\"plugins/prd-os/runner.py\"],\"msg\"))\\nprint(\"index before:\",\"staged-v1\")\\nprint(\"index after: \",state[\"index\"])\\nprint(\"git calls:\",calls)'" in /Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165
 succeeded in 0ms:
[('commit', 'plugins/prd-os/runner.py', "REFUSED (index unwound): ['hook rejected']")]
index before: staged-v1
index after:  worktree-v2
git calls: [('diff', '--cached', '--quiet', '--', 'plugins/prd-os/runner.py'), ('add', '--', 'plugins/prd-os/runner.py'), ('commit', '-m', 'msg', '--', 'plugins/prd-os/runner.py')]

exec
/bin/zsh -lc "bash -n kipi-update.sh test-kipi-update-config-commit-unwind.sh && python3 -c \"import ast,pathlib; files=['fleet-unblock.py','kipi-update-gitignore-block.py','kipi-update-preserve-scan.py','q-system/hooks/auto-commit.py','test_fleet_unblock.py','q-system/.q-system/tests/test_gitignore_block.py','test_destructive_op_deny_anchor.py']; [ast.parse(pathlib.Path(f).read_text(),filename=f) for f in files]; print('AST OK:',len(files),'Python files');\"; git diff --check origin/main...HEAD; python3 -c \"import importlib.util,pathlib; p=pathlib.Path('kipi-update-gitignore-block.py'); s=importlib.util.spec_from_file_location('b',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); original='own-rule/\\n'; stanza=['# why','q-system/.q-system/.claude-integrity-armed']; block=m.render_block(stanza); before=original+'\\n'+block; found=m.existing_block(before); after=found[0]+block+found[2]; print('managed block idempotent:',after==before); print('instance prefix preserved:',after.startswith(original))\"" in /Users/assafkipnis/.config/kipi/review-trees/assafkip_kipi-system__pr-165
 succeeded in 0ms:
AST OK: 7 Python files
managed block idempotent: True
instance prefix preserved: True

codex
## Findings

1. **MAJOR, Confirmed:** A rejected commit overwrites an already-staged version instead of restoring it, despite reporting `index unwound`.

   File: `fleet-unblock.py:233`

   The code records only whether the path was staged. If `git add` replaces that staged snapshot and the commit hook rejects the commit, `unwind()` skips the path entirely. A human must reconstruct the original staged version.

   Reproducer run:

   ```bash
   python3 -c $'import importlib.util, pathlib\np=pathlib.Path("fleet-unblock.py").resolve()\ns=importlib.util.spec_from_file_location("fleet_unblock",p)\nm=importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\nstate={"index":"staged-v1"}\ncalls=[]\ndef fake(repo,*a):\n    calls.append(a)\n    if a[:3] == ("diff","--cached","--quiet"): return (1,"","")\n    if a[0] == "add": state["index"]="worktree-v2"; return (0,"","")\n    if a[0] == "commit": return (1,"","hook rejected")\n    if a[0] == "restore": state["index"]="HEAD"; return (0,"","")\n    return (0,"","")\nm.git=fake\nprint(m.commit_with_unwind("/repo",["plugins/prd-os/runner.py"],"msg"))\nprint("index before:","staged-v1")\nprint("index after: ",state["index"])\nprint("git calls:",calls)'
   ```

   Real output:

   ```text
   [('commit', 'plugins/prd-os/runner.py', "REFUSED (index unwound): ['hook rejected']")]
   index before: staged-v1
   index after:  worktree-v2
   git calls: [('diff', '--cached', '--quiet', '--', 'plugins/prd-os/runner.py'), ('add', '--', 'plugins/prd-os/runner.py'), ('commit', '-m', 'msg', '--', 'plugins/prd-os/runner.py')]
   ```

2. **MAJOR, Confirmed:** `git add` and `git restore --staged` failures are counted as successful actions, so an unattended repair can exit 0 after repairing nothing.

   File: `fleet-unblock.py:317`

   Only outcomes beginning with `REFUSED` increment `failed`. Outcomes beginning with `FAILED`, produced at lines 210 and 246, increment `acted`. An index-lock race between two runs is one production path to this result. The operator must notice the misleading output and rerun the repair.

   Reproducer run:

   ```bash
   python3 -c "import importlib.util,pathlib; p=pathlib.Path('fleet-unblock.py').resolve(); s=importlib.util.spec_from_file_location('fleet_unblock',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.commit_with_unwind('/definitely/not/a/repo',['plugins/prd-os/runner.py'],'repro')); outcome='FAILED add: fatal'; failed=0; acted=0; failed = failed+1 if outcome.startswith('REFUSED') else failed; acted = acted if outcome.startswith('REFUSED') else acted+1; print(f'current main accounting => acted={acted} failed={failed} exit={1 if failed else 0}')"
   ```

   Real output:

   ```text
   [('commit', 'plugins/prd-os/runner.py', "FAILED add: fatal: cannot change to '/definitely/not/a/repo': No such file or directory")]
   current main accounting => acted=1 failed=0 exit=0
   ```

## What is sound

- `bash -n` accepted both changed shell scripts.
- All seven changed Python files parsed successfully.
- `git diff --check origin/main...HEAD` reported no whitespace errors.
- The managed `.gitignore` block preserved instance-owned content and was idempotent in the executed probe.
- The mixed staged-skeleton/founder-worktree path now refuses instead of committing the staged half.
- The normal dry run against `KTLYST_strategy` performed no actions.
- Full pytest execution was unavailable because the read-only environment had no usable temporary directory.

## Verdict

**VERDICT: REQUEST CHANGES**

Fix the staged-index restoration first. Snapshot each path’s original index entry before `git add`, then restore that exact entry on any failure.

- Energy: Deep Focus
- Time estimate: 30 to 45 minutes

FINDINGS:
major|A rejected commit overwrites an already-staged version instead of restoring it despite reporting index unwound|fleet-unblock.py:233
major|Git add and restore failures are counted as successful actions so the command can exit zero after repairing nothing|fleet-unblock.py:317
END FINDINGS
tokens used
84,948
## Findings

1. **MAJOR, Confirmed:** A rejected commit overwrites an already-staged version instead of restoring it, despite reporting `index unwound`.

   File: `fleet-unblock.py:233`

   The code records only whether the path was staged. If `git add` replaces that staged snapshot and the commit hook rejects the commit, `unwind()` skips the path entirely. A human must reconstruct the original staged version.

   Reproducer run:

   ```bash
   python3 -c $'import importlib.util, pathlib\np=pathlib.Path("fleet-unblock.py").resolve()\ns=importlib.util.spec_from_file_location("fleet_unblock",p)\nm=importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\nstate={"index":"staged-v1"}\ncalls=[]\ndef fake(repo,*a):\n    calls.append(a)\n    if a[:3] == ("diff","--cached","--quiet"): return (1,"","")\n    if a[0] == "add": state["index"]="worktree-v2"; return (0,"","")\n    if a[0] == "commit": return (1,"","hook rejected")\n    if a[0] == "restore": state["index"]="HEAD"; return (0,"","")\n    return (0,"","")\nm.git=fake\nprint(m.commit_with_unwind("/repo",["plugins/prd-os/runner.py"],"msg"))\nprint("index before:","staged-v1")\nprint("index after: ",state["index"])\nprint("git calls:",calls)'
   ```

   Real output:

   ```text
   [('commit', 'plugins/prd-os/runner.py', "REFUSED (index unwound): ['hook rejected']")]
   index before: staged-v1
   index after:  worktree-v2
   git calls: [('diff', '--cached', '--quiet', '--', 'plugins/prd-os/runner.py'), ('add', '--', 'plugins/prd-os/runner.py'), ('commit', '-m', 'msg', '--', 'plugins/prd-os/runner.py')]
   ```

2. **MAJOR, Confirmed:** `git add` and `git restore --staged` failures are counted as successful actions, so an unattended repair can exit 0 after repairing nothing.

   File: `fleet-unblock.py:317`

   Only outcomes beginning with `REFUSED` increment `failed`. Outcomes beginning with `FAILED`, produced at lines 210 and 246, increment `acted`. An index-lock race between two runs is one production path to this result. The operator must notice the misleading output and rerun the repair.

   Reproducer run:

   ```bash
   python3 -c "import importlib.util,pathlib; p=pathlib.Path('fleet-unblock.py').resolve(); s=importlib.util.spec_from_file_location('fleet_unblock',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.commit_with_unwind('/definitely/not/a/repo',['plugins/prd-os/runner.py'],'repro')); outcome='FAILED add: fatal'; failed=0; acted=0; failed = failed+1 if outcome.startswith('REFUSED') else failed; acted = acted if outcome.startswith('REFUSED') else acted+1; print(f'current main accounting => acted={acted} failed={failed} exit={1 if failed else 0}')"
   ```

   Real output:

   ```text
   [('commit', 'plugins/prd-os/runner.py', "FAILED add: fatal: cannot change to '/definitely/not/a/repo': No such file or directory")]
   current main accounting => acted=1 failed=0 exit=0
   ```

## What is sound

- `bash -n` accepted both changed shell scripts.
- All seven changed Python files parsed successfully.
- `git diff --check origin/main...HEAD` reported no whitespace errors.
- The managed `.gitignore` block preserved instance-owned content and was idempotent in the executed probe.
- The mixed staged-skeleton/founder-worktree path now refuses instead of committing the staged half.
- The normal dry run against `KTLYST_strategy` performed no actions.
- Full pytest execution was unavailable because the read-only environment had no usable temporary directory.

## Verdict

**VERDICT: REQUEST CHANGES**

Fix the staged-index restoration first. Snapshot each path’s original index entry before `git add`, then restore that exact entry on any failure.

- Energy: Deep Focus
- Time estimate: 30 to 45 minutes

FINDINGS:
major|A rejected commit overwrites an already-staged version instead of restoring it despite reporting index unwound|fleet-unblock.py:233
major|Git add and restore failures are counted as successful actions so the command can exit zero after repairing nothing|fleet-unblock.py:317
END FINDINGS
