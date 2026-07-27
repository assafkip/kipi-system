#!/usr/bin/env python3
"""Mutation harness: patch the worker in the .pr24rev/mut clone, so the PR's own
test can be checked for 'could this ever go red?'."""
import pathlib, subprocess, sys

MUT = pathlib.Path("/Users/assafkipnis/projects/kipi-system/.pr24rev/mut")
W = MUT / "q-system/.q-system/scripts/linear-worker.sh"

FETCH_BLOCK = '''if ! git -C "$SKEL" fetch --quiet origin 2>>"$LOG"; then
  say "INFRA: git fetch failed in $SKEL. Stopping before any worktree is cut from a stale base."
  bash "$NOTIFY" "worker: git fetch failed in $SKEL -- the run did NO work. Check credentials/network." 2>/dev/null || true
  exit 9
fi
'''


def reset():
    subprocess.run(["git", "-C", str(MUT), "checkout", "-q", "--", str(W.relative_to(MUT))], check=True)


def read():
    return W.read_text()


def write(s):
    W.write_text(s)


def run_suite():
    p = subprocess.run(["bash", str(MUT / "q-system/.q-system/scripts/test/test-linear-worker-fetch.sh")],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


MUTATIONS = {
    # 1. no fetch at all -- the original defect
    "no-fetch": lambda s: s.replace(FETCH_BLOCK, ""),
    # 2. fetch moved BELOW the worktree add (the test claims a source-grep would
    #    pass on this and its side-effect assertion would not)
    "fetch-after-worktree": lambda s: s.replace(FETCH_BLOCK, "").replace(
        '  TREE="$STATE_DIR/worktrees/$(echo "$ISSUE" | tr \'A-Z\' \'a-z\')"',
        '  TREE="$STATE_DIR/worktrees/$(echo "$ISSUE" | tr \'A-Z\' \'a-z\')"\n'
        '  if [ ! -d "$TREE" ]; then :; fi\n'
        '  __POST_FETCH__'),
    # 3. guard present but exits 0 (the shape round 3 rejected)
    "exit-0": lambda s: s.replace('  exit 9\nfi\n', '  exit 0\nfi\n'),
    # 4. guard exits 9 but pages nobody
    "no-page": lambda s: s.replace(
        '  bash "$NOTIFY" "worker: git fetch failed in $SKEL -- the run did NO work. Check credentials/network." 2>/dev/null || true\n',
        ''),
    # 5. page is generic, does not name the cause
    "vague-page": lambda s: s.replace(
        'worker: git fetch failed in $SKEL -- the run did NO work. Check credentials/network.',
        'worker: something went wrong'),
    # 6. always fail + always page (the "same defect wearing the other hat")
    "always-page": lambda s: s.replace(
        'if ! git -C "$SKEL" fetch --quiet origin 2>>"$LOG"; then',
        'if git -C "$SKEL" fetch --quiet origin 2>>"$LOG"; then'),
}

name = sys.argv[1]
reset()
src = read()
if name == "fetch-after-worktree":
    out = MUTATIONS[name](src)
    out = out.replace("  __POST_FETCH__", '  git -C "$SKEL" fetch --quiet origin 2>>"$LOG" || true')
else:
    out = MUTATIONS[name](src)
if out == src:
    print("MUTATION DID NOT APPLY:", name)
    sys.exit(2)
write(out)
rc, o = run_suite()
reset()
print("=== mutation: %s -> suite rc=%d ===" % (name, rc))
print(o.strip()[-1400:])
