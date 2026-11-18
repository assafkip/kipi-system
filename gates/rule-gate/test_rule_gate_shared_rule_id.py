#!/usr/bin/env python3
"""ASK-5448: one rule synced into two nested repos is one rule, not a duplicate owner.

THE SCAR. 2026-11-18 15:23, a consulting session moved its cwd into
~/projects/consulting/projects/4_points_consulting, a separate repo nested inside the
consulting tree. hot_set() walks up from the cwd, so it held both repos' .claude/rules/.
The skeleton syncs the same 5 rule files (RULE-2026-11-17-SCOPE-*) into both, byte for
byte. check_section() refused each copy because the other copy "already" owned its
Rule-ID, and repair_file() stripped the preamble of both. consulting's integrity tripwire
put its copy back on the next call and the gate stripped it again: two writers fighting
on every tool call, and every Stop blocked.

WHAT STAYS PROTECTED. A different rule body that reuses a live Rule-ID is still refused;
the negative case below holds that, so the fix cannot be "drop the uniqueness check".

The sandbox, the gate copy and the hook-style run come from test_rule_gate_tree_scope.py.
"""
import os

from test_rule_gate_tree_scope import sb, tok  # noqa: F401  (sb is a pytest fixture)

REL = os.path.join(".claude", "rules", "shared.md")


def shared_rule(t, enforcer, extra=""):
    # The real files' shape: frontmatter plus Rule-ID in the PREAMBLE. Their headings below
    # are grandfathered by the install baseline; this sandbox's baseline is empty, so a
    # heading here would fail on its own and hide the verdict under test.
    return (f"---\ndescription: shared rule {t}\n---\n\n"
            f"Rule-ID: RULE-SHARED-{t}\nEnforced by: {enforcer}\n{extra}\n"
            f"Do the shared thing {t}.\n")


def nested_pair(sb, t):
    """A parent repo and a separate repo nested inside it, plus a wired absolute enforcer
    (named by absolute path, as the real rules name the skeleton's test)."""
    enf = sb.h("projects", "skel", "tests", f"test_shared_{t}.py")
    sb.put(enf, f"# enforces RULE-SHARED-{t}\n")
    sb.put(sb.h("Library", "LaunchAgents", f"com.test.shared-{t}.plist"), f"<string>{enf}</string>\n")
    parent = sb.repo("parent", {REL: shared_rule(t, enf)}, sb.h("projects", "parent"))
    nested = sb.repo("nested", {REL: shared_rule(t, enf)}, os.path.join(parent, "projects", "nested"))
    return parent, nested, enf


def read(path):
    with open(path) as fh:
        return fh.read()


def test_identical_synced_copies_in_nested_repos_are_one_rule(sb):
    t = tok()
    parent, nested, enf = nested_pair(sb, t)
    want = shared_rule(t, enf)
    out = sb.run("PostToolUse", nested)
    assert "already belongs" not in out, f"an identical synced copy was judged a duplicate owner:\n{out}"
    assert read(os.path.join(parent, REL)) == want, "the gate rewrote the parent repo's synced copy"
    assert read(os.path.join(nested, REL)) == want, "the gate rewrote the nested repo's synced copy"
    assert sb.stop_scan_reasons(nested) == [], "the Stop blocked on identical synced copies"


def test_a_different_rule_reusing_the_id_is_still_refused(sb):
    # Negative self-test: the same id with a DIFFERENT body is a second rule, and the gate
    # must still catch it. Without this, removing the uniqueness check would pass above.
    t = tok()
    parent, nested, enf = nested_pair(sb, t)
    impostor = shared_rule(t, enf, extra="Also do a different thing that nobody wired.\n")
    sb.put(os.path.join(nested, REL), impostor)
    # The verdict comes from --scan, which judges without writing: a repair pass edits the
    # files one after another, so which copy it strips depends on the walk order.
    rc, out = sb.scan(nested)
    assert rc != 0 and f"RULE-SHARED-{t}: Rule-ID already belongs" in out, (
        f"a reused id with a new body passed the scan:\n{out}")
    sb.run("PostToolUse", nested)
    left = [os.path.exists(os.path.join(r, REL)) and read(os.path.join(r, REL)) for r in (parent, nested)]
    assert left != [shared_rule(t, enf), impostor], "the repair pass left the clashing pair in place"
