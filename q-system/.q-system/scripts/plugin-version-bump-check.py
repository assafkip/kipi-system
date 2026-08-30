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

    # --fix: BUMP IT RATHER THAN REFUSE. Scar 2026-08-24 (sp-97303649, ASK-1039),
    # reproduced live during the ASK-999 port.
    #
    # Refusing created a deadlock and then something worse than a deadlock. The
    # deadlock: the bump needs a file edit, and under the token guard's call
    # ceiling only `git commit` is exempt, so the one action allowed is the one
    # action that cannot succeed. The worse part: a refused commit LEAVES ITS
    # CHANGES STAGED, so the follow-up commit that finally bumps the manifest
    # silently absorbs the whole original diff. That is what happened to the
    # ASK-999 port -- it landed under a message describing only a version bump,
    # and correcting the message needs a force-push, which is hook-blocked. A
    # refusal that mislabels permanent history is worse than no gate.
    #
    # The bump is DERIVABLE, so deriving it is strictly better than demanding it.
    # PATCH only, never minor or major: those carry intent a script cannot read,
    # and guessing intent is how a tool starts lying about what changed.
    if "--fix" in sys.argv:
        import json as _json
        for plugin, ver in violations:
            # USE THE CHECKER'S OWN RESOLVER. This hardcoded
            # plugins/<p>/.claude-plugin/plugin.json, so --fix crashed on the
            # root-level plugin.json layout that MANIFESTS explicitly supports:
            # the fixer could not repair the very layout the check flags
            # (Codex minor, PR #253).
            man = manifest_path(plugin)
            if not man:
                sys.stderr.write(
                    f"  - {plugin}: no manifest at any known path; bump it by hand\n")
                sys.exit(2)

            # NEVER `git add` A MANIFEST CARRYING UNSTAGED WORK. `git add <man>`
            # stages the WHOLE working-tree file, so an unrelated edit the author
            # had in flight is silently absorbed into a commit whose message says
            # only "version bump" (Codex major, PR #253).
            #
            # That is the SAME absorption this gate exists to stop -- the header
            # above records a refused commit eating the entire ASK-999 port -- so
            # a fixer that did it would reproduce the defect it was written to
            # end, and under a message that lies about what changed.
            #
            # Refusing ONLY here keeps the deadlock fix intact: a clean manifest,
            # which is the ordinary case, still auto-bumps and never asks.
            clean, _ = run_ok(["git", "diff", "--quiet", "--", man])
            if not clean:
                sys.stderr.write(
                    f"plugin-version-bump-check: {man} has UNSTAGED changes.\n"
                    f"  Auto-bumping stages the whole file, so that work would land "
                    f"under a message describing only a version bump.\n"
                    f"  Stage it or revert it, then commit again.\n")
                sys.exit(2)

            with open(man) as fh:
                data = _json.load(fh)
            parts = str(data.get("version", "0.0.0")).split(".")
            while len(parts) < 3:
                parts.append("0")
            try:
                parts[2] = str(int(parts[2]) + 1)
            except ValueError:
                sys.stderr.write(
                    f"  - {plugin}: version {ver!r} is not numeric; bump it by hand\n")
                sys.exit(2)
            data["version"] = ".".join(parts[:3])
            with open(man, "w") as fh:
                _json.dump(data, fh, indent=2)
                fh.write("\n")
            subprocess.run(["git", "add", man], check=True)
            # LOUD, never silent. A hook that edits your commit and says nothing
            # is its own defect; the author must see what shipped.
            sys.stderr.write(
                f"plugin-version-bump-check: auto-bumped {plugin} "
                f"{ver} -> {data['version']} and staged it\n")
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
