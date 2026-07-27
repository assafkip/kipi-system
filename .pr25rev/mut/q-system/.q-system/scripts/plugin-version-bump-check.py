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


def changed_files(diff_args):
    out = run(["git", "diff", "--name-only"] + diff_args)
    return [l for l in out.splitlines() if l.strip()]


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
        ref = sys.argv[sys.argv.index("--against") + 1]
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
