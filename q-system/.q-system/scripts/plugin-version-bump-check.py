#!/usr/bin/env python3
"""plugin-version-bump-check: a changed plugin must bump its version.

Scar (sp-9886486d, 2026-06-30): plugin code is loaded from a VERSION-KEYED cache
(~/.claude/plugins/cache/<mp>/<plugin>/<version>/). Change a plugin's command or
script WITHOUT bumping its .claude-plugin/plugin.json version and the cache key is
unchanged, so the stale cached copy keeps running forever -- the edit you made is
never the copy that loads. This check fails when a plugin's tracked files changed
but its manifest version did not.

This is the deterministic half of the broader "derived copy drifted from its
source" class (RCA rca-derived-copy-drift-2026-06-30): a version bump is what lets
the cache NOTICE a change.

Modes:
  --staged            diff staged changes vs HEAD (pre-commit). Default.
  --against <ref>     diff working tree vs <ref> (e.g. origin/main, for CI).

Exit 0 = every changed plugin bumped its version (or no plugin changed).
Exit 2 = at least one plugin changed without a version bump. stdlib only.
"""
import json
import os
import re
import subprocess
import sys

PLUGIN_RE = re.compile(r"^plugins/([^/]+)/")
# manifest may live at .claude-plugin/plugin.json or plugin.json (both seen in-repo)
MANIFESTS = (".claude-plugin/plugin.json", "plugin.json")


def run(args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def run_ok(args):
    """(succeeded, stdout). run() discards the return code, which is what let a
    FAILED git command look identical to one that found nothing: `git diff
    <bad-ref>` returns "", changed_files sees no files, and the gate exits 0
    having verified nothing at all (codex major, PR #129)."""
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode == 0, p.stdout


def changed_files(diff_args):
    out = run(["git", "diff", "--name-only"] + diff_args)
    return [l for l in out.splitlines() if l.strip()]


def merge_base(ref):
    """The commit this branch actually diverged at, or `ref` if git cannot say.

    Scar (ASK-514, sp-05762519): this compared against the moving TIP of
    origin/main, and it was wrong in BOTH directions at once.

    Too loud: any plugin changed on main AFTER a PR branched shows up in
    `git diff <tip>`, and its version matches on both sides because the PR never
    touched it -- which is precisely the violation shape. PR #127 touched only
    plugins/kipi-core and CI failed it for plugins/kipi-design; merging main in,
    with no code change at all, turned it green.

    Too quiet, and this is the half that is easy to miss: a version bump landing
    on MAIN makes the PR's own unbumped plugin look bumped, because
    version_at(tip) then differs from version_now() for a change the PR never
    made. The gate excuses a real violation.

    Both follow from one mistake, so both are fixed by one resolution: the
    comparison point is where the branch diverged, not wherever main has got to.
    Returning `ref` unchanged when merge-base fails (unrelated histories, a bare
    sha with no common ancestor) keeps the previous behaviour rather than
    crashing a blocking gate on an edge it cannot resolve.
    """
    # FAIL CLOSED on a ref that does not resolve. A blocking gate that silently
    # becomes NO gate is worse than no gate, because CI reports it green -- and
    # the workflow makes this reachable rather than theoretical:
    #     git fetch origin main || true
    #     ... --against origin/main
    # The `|| true` swallows a fetch failure, so on a runner whose fetch failed
    # origin/main may not resolve, and every version-bump violation in the PR
    # would sail through unexamined. Verified before the fix: `--against
    # no-such-ref-xyz` exited 0 with a real unbumped plugin change in the tree.
    resolves, _ = run_ok(["git", "rev-parse", "--verify", "--quiet",
                          "%s^{commit}" % ref])
    if not resolves:
        sys.stderr.write(
            "plugin-version-bump-check: cannot resolve --against ref %r, so the "
            "version-bump check could not run. Refusing rather than passing "
            "unchecked. If this is CI, the `git fetch` for that ref likely "
            "failed.\n" % ref)
        sys.exit(2)
    ok, out = run_ok(["git", "merge-base", ref, "HEAD"])
    base = out.strip()
    # No merge base (unrelated histories) is NOT the same as an unresolvable
    # ref: the ref exists, so comparing against it directly is still meaningful
    # and is the behaviour that shipped. Only the missing-ref case refuses.
    return base if ok and base else ref


def plugins_touched(files):
    """Map plugin name -> True if any non-manifest file changed (needs a bump)."""
    touched = {}
    for f in files:
        m = PLUGIN_RE.match(f)
        if m:
            touched.setdefault(m.group(1), set()).add(f)
    return touched


def manifest_path(plugin):
    for rel in MANIFESTS:
        p = os.path.join("plugins", plugin, rel)
        if os.path.isfile(p):
            return p
    return None


def version_now(plugin):
    p = manifest_path(plugin)
    if not p:
        return None
    try:
        return json.load(open(p)).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def version_at(ref, plugin):
    for rel in MANIFESTS:
        path = f"plugins/{plugin}/{rel}"
        out = run(["git", "show", f"{ref}:{path}"])
        if out.strip():
            try:
                return json.loads(out).get("version")
            except json.JSONDecodeError:
                return None
    return None


def find_violations(touched, version_before, version_after):
    """Pure core: plugins whose files changed but version did not. Testable."""
    violations = []
    for plugin in sorted(touched):
        before = version_before.get(plugin)
        after = version_after.get(plugin)
        if before == after:
            violations.append((plugin, after))
    return violations


def main():
    if not os.path.isdir("plugins"):
        sys.exit(0)  # not the skeleton; nothing to check

    if "--against" in sys.argv:
        ref = merge_base(sys.argv[sys.argv.index("--against") + 1])
        diff_args = [ref, "--"]
    else:
        ref = "HEAD"
        diff_args = ["--cached", "--"]

    touched = plugins_touched(changed_files(diff_args))
    if not touched:
        sys.exit(0)

    before = {p: version_at(ref, p) for p in touched}
    after = {p: version_now(p) for p in touched}
    violations = find_violations(touched, before, after)

    if not violations:
        sys.exit(0)

    sys.stderr.write(
        "plugin-version-bump-check: plugin(s) changed without a version bump -> "
        "the version-keyed cache will keep running the STALE copy:\n"
    )
    for plugin, ver in violations:
        sys.stderr.write(f"  - {plugin} (version still {ver}); bump plugins/{plugin}/.claude-plugin/plugin.json\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
