#!/usr/bin/env python3
"""Self-test for reuse-gate.py (RULE-2026-11-12-REUSE, ASK-4582).

Runs the hook the way Claude Code does: a subprocess, hook JSON on stdin. Every
case runs against a throwaway kipi-system fixture repo built in a temp dir, with
the REAL capability-map-gen.py copied into it, so the gate's lookup is exercised
end to end (cache miss, gate checkout, generator run, cache hit). Nothing here
reads or writes the live kipi-system checkout or ~/.cache.

Run: python3 test_reuse_gate.py   (exit 0 = all pass)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name("reuse-gate.py")
# The generator the gate reuses. Copied into the fixture so the fixture's
# origin/main carries it, exactly as kipi-system's does.
GEN = Path(__file__).resolve().parents[3] / "q-system" / ".q-system" / "scripts" / "capability-map-gen.py"
KIPI_URL = "https://github.com/assafkip/kipi-system.git"

fails = []
passed = 0


def check(name, ok, detail=""):
    global passed
    if ok:
        passed += 1
    else:
        fails.append(f"{name}: {detail}")


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True).stdout.strip()


def engine(path: Path, doc: str):
    """A python engine the generator will collect: a docstring and 40+ lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"x{i} = {i}" for i in range(45))
    path.write_text(f'#!/usr/bin/env python3\n"""{doc}"""\n{body}\n')


def make_kipi(root: Path) -> Path:
    repo = root / "kipi-system"
    scripts = repo / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(GEN, scripts / "capability-map-gen.py")
    engine(scripts / "backlog-sweep.py", "Sweep the backlog of stale threads into the archive.")
    engine(scripts / "linear-sync.py", "Turn a capability map into Linear issues.")
    engine(scripts / "worktree-reaper.py", "Remove finished agent worktrees.")
    # Ten more sweep engines, so one new file overlaps more than the 8 the
    # refusal lists, and the "name every listed one" contract is tested at its cap.
    for word in ("alpha", "bravo", "charlie", "delta", "echoes", "foxtrot",
                 "golfer", "hotel", "india", "juliet"):
        engine(scripts / f"{word}-sweep.py", f"Sweep the {word} queue.")
    skill = repo / "plugins" / "kipi-core" / "skills" / "founder-voice" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: founder-voice\ndescription: Voice rules for drafts.\n---\nBody.\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    git(repo, "remote", "add", "origin", KIPI_URL)
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def run(tool_input, env_extra, tool="Write", raw=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("KIPI_REUSE_GATE", "REUSE_GATE"))}
    env.update(env_extra)
    stdin = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input})
    p = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                       text=True, env=env, timeout=180)
    return p.returncode, p.stderr, p.stdout


def expect_block(name, res, *needles):
    rc, err = res[0], res[1]
    # rc 2 alone is not proof: python exits 2 when the hook file is missing.
    ok = rc == 2 and "BLOCKED by reuse-gate" in err and all(n in err for n in needles)
    check(name, ok, f"want BLOCK with {needles}, got rc={rc} err={err[:400]!r}")


def expect_pass(name, res):
    rc, err = res[0], res[1]
    # A crash that failed open also exits 0. Review of #755: a raise injected into
    # the worktree branch still read 52/52 green, so a pass must be a CLEAN pass.
    clean = "BLOCKED" not in err and "failing open" not in err
    check(name, rc == 0 and clean, f"want PASS, got rc={rc} err={err[:400]!r}")


def expect_open(name, res):
    rc, err, out = res
    # The warning must reach someone: on exit 0 Claude Code shows no stderr, so it
    # rides stdout as a systemMessage too.
    try:
        msg = json.loads(out.strip().splitlines()[-1]).get("systemMessage", "")
    except (ValueError, IndexError, AttributeError):
        msg = ""
    check(name, rc == 0 and "failing open" in err and "failing open" in msg,
          f"want fail-open warning on stderr and systemMessage, got rc={rc} "
          f"err={err[:300]!r} out={out[:200]!r}")


def w(path, content):
    return {"file_path": str(path), "content": content}


def script(header="", doc="Sweep the backlog of muted senders."):
    return f'#!/usr/bin/env python3\n"""{doc}\n\n{header}\n"""\nprint(1)\n'


def main():
    if not GEN.is_file():
        print(f"FAIL: generator not found at {GEN}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = make_kipi(root)
        sha = git(repo, "rev-parse", "HEAD")
        cache = root / "cache"
        client = root / "client"
        client.mkdir()
        # Override the temp policy so the fixture (under /var/folders) is NOT
        # temp space here; otherwise every client case would pass for the wrong reason.
        env = {"KIPI_REUSE_GATE_REPO": str(repo), "KIPI_REUSE_GATE_CACHE": str(cache),
               "KIPI_REUSE_GATE_TEMP_ROOTS": str(root / "declared-temp")}
        new = client / "backlog_sweep.py"

        # 1. a new script with no header refuses, and names the overlapping kipi tool
        expect_block("no header", run(w(new, script()), env),
                     "backlog-sweep", "q-system/.q-system/scripts/backlog-sweep.py",
                     "no Reuses-kipi or Kipi-checked line", "Reuses-kipi:", "Kipi-checked:")
        # 1b. the cache is a file named by origin/main's sha
        check("cache named by sha", (cache / f"{sha}.json").is_file(),
              f"no {sha}.json in {sorted(p.name for p in cache.glob('*'))}")
        # 2. Reuses-kipi naming a real kipi-system file passes
        expect_pass("reuses real", run(w(new, script(
            "Reuses-kipi: q-system/.q-system/scripts/backlog-sweep.py")), env))
        # 2b. the same path written with the checkout prefix passes
        expect_pass("reuses ~/projects prefix", run(w(new, script(
            "Reuses-kipi: ~/projects/kipi-system/q-system/.q-system/scripts/backlog-sweep.py")), env))
        expect_pass("reuses absolute repo path", run(w(new, script(
            f"Reuses-kipi: {repo}/q-system/.q-system/scripts/backlog-sweep.py")), env))
        # 3. Reuses-kipi naming a missing file refuses, even beside a real one
        expect_block("reuses missing", run(w(new, script(
            "Reuses-kipi: q-system/.q-system/scripts/nope.py")), env), "nope.py")
        expect_block("reuses one missing of two", run(w(new, script(
            "Reuses-kipi: q-system/.q-system/scripts/backlog-sweep.py\n"
            "Reuses-kipi: q-system/.q-system/scripts/nope.py")), env), "nope.py")
        # 3b. a directory is not a file (the brief: "naming an existing kipi-system file")
        expect_block("reuses a directory", run(w(new, script(
            "Reuses-kipi: q-system/.q-system/scripts")), env), "not a file")
        # 3c. ordinary ways of writing a real citation pass
        for form in ("q-system/.q-system/scripts/backlog-sweep.py.",
                     "kipi-system/q-system/.q-system/scripts/backlog-sweep.py",
                     "`q-system/.q-system/scripts/backlog-sweep.py`"):
            expect_pass(f"reuses form {form}", run(w(new, script(f"Reuses-kipi: {form}")), env))
        expect_pass("reuses in a /* */ comment", run(w(client / "backlog_sweep.js",
            "/* Reuses-kipi: q-system/.q-system/scripts/backlog-sweep.py */\nrun();\n"), env))
        # 4. Kipi-checked must name EVERY overlapping capability
        both = client / "backlog_linear_sync.py"
        expect_block("checked misses one", run(w(both, script(
            "Kipi-checked: backlog-sweep -- it archives, this one files", doc="Sync tool.")), env),
            "linear-sync")
        expect_pass("checked names all", run(w(both, script(
            "Kipi-checked: backlog-sweep, linear-sync -- neither files mail threads",
            doc="Sync tool.")), env))
        expect_pass("checked by path", run(w(both, script(
            "Kipi-checked: q-system/.q-system/scripts/backlog-sweep.py, "
            "q-system/.q-system/scripts/linear-sync.py -- neither fits", doc="Sync tool.")), env))
        expect_block("checked without reason", run(w(both, script(
            "Kipi-checked: backlog-sweep, linear-sync", doc="Sync tool.")), env), "no reason")
        # 4b. an em or en dash also separates the reason (the founder bans "--" in output)
        for dash in ("\u2014", "\u2013"):
            expect_pass(f"checked with dash {dash!a}", run(w(both, script(
                f"Kipi-checked: backlog-sweep, linear-sync {dash} neither files mail threads",
                doc="Sync tool.")), env))
        # 4c. the refusal's own template pasted back is not an answer
        expect_block("template pasted back", run(w(both, script(
            "Kipi-checked: <slug>, <slug> -- <why none fits>", doc="Sync tool.")), env), "linear-sync")
        # 5. no overlap still needs the lookup recorded
        zebra = client / "zebra_quokka.py"
        expect_block("no overlap, no header", run(w(zebra, script(doc="Count quokkas.")), env),
                     "Kipi-checked: none")
        expect_pass("no overlap, checked none", run(w(zebra, script(
            "Kipi-checked: none -- nothing in kipi counts animals", doc="Count quokkas.")), env))
        expect_block("checked none without reason", run(w(zebra, script(
            "Kipi-checked: none", doc="Count quokkas.")), env), "--")
        expect_block("checked none while overlaps exist", run(w(new, script(
            "Kipi-checked: none -- I looked")), env), "backlog-sweep")
        # 5b. with nothing listed, the literal `none` is required
        expect_block("no overlap, names something else", run(w(zebra, script(
            "Kipi-checked: linear-sync -- looked", doc="Count quokkas.")), env),
            "nothing in kipi-system overlaps it")
        expect_block("no overlap, template pasted back", run(w(zebra, script(
            "Kipi-checked: <slug>, <slug> -- <why none fits>", doc="Count quokkas.")), env), "none")
        # The one shape only the reason check catches (mutation run, round 1 of #755).
        expect_block("none with the template reason", run(w(zebra, script(
            "Kipi-checked: none -- <reason>", doc="Count quokkas.")), env), "no reason")
        # 6. more than 8 overlaps: the refusal lists exactly 8, and naming those 8 passes
        many = client / "sweep_runner.py"
        rc, err, _ = run(w(many, script(doc="Run every sweep.")), env)
        expect_block("many overlaps", (rc, err), "sweep")
        listed = [ln.split()[1] for ln in err.splitlines() if ln.startswith("  - ")]
        check("lists exactly 8 of 11", len(listed) == 8, f"listed {listed}")
        expect_pass("naming the listed 8 passes", run(w(many, script(
            "Kipi-checked: " + ", ".join(listed) + " -- none of them runs all sweeps",
            doc="Run every sweep.")), env))
        # 7. test files pass untouched
        for t in (client / "tests" / "backlog_sweep.py", client / "test_backlog_sweep.py",
                  client / "backlog_sweep_test.py", client / "test" / "backlog_sweep.sh"):
            expect_pass(f"test file {t.relative_to(client)}", run(w(t, script()), env))
        # 8. kipi-system's own tree passes: the repo, a linked worktree, and a clone
        expect_pass("kipi repo file", run(w(repo / "q-system" / "new_backlog_sweep.py", script()), env))
        wt = root / "kipi-wt"
        git(repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
        expect_pass("kipi worktree file", run(w(wt / "scripts" / "new_backlog_sweep.py", script()), env))
        clone = root / "kipi-clone"
        clone.mkdir()
        git(clone, "init", "-q")
        git(clone, "remote", "add", "origin", "git@github.com:assafkip/kipi-system.git")
        expect_pass("kipi clone file", run(w(clone / "new_backlog_sweep.py", script()), env))
        # 8a. the configured repo is kipi-system by identity, not only by its URL:
        # with origin moved off GitHub, its own tree and worktree still pass.
        # (Mutation run 2026-11-11: the URL check alone covered both cases above.)
        git(repo, "remote", "set-url", "origin", str(root / "mirror.git"))
        expect_pass("configured repo, non-github origin", run(
            w(repo / "q-system" / "new_backlog_sweep.py", script()), env))
        expect_pass("its worktree, non-github origin", run(
            w(wt / "scripts" / "new_backlog_sweep.py", script()), env))
        git(repo, "remote", "set-url", "origin", KIPI_URL)
        # 8a2. a symlink into a kipi-system SUBDIR is kipi (judged on the resolved path).
        # A link to the kipi root would pass either way: its .git shows through the link.
        link = root / "link-to-kipi-q"
        link.symlink_to(repo / "q-system")
        expect_pass("symlink into kipi subdir", run(w(link / "new_backlog_sweep.py", script()), env))
        # 8a3. an absolute citation from a kipi worktree names the same kipi file
        expect_pass("reuses absolute worktree path", run(w(new, script(
            f"Reuses-kipi: {wt}/q-system/.q-system/scripts/backlog-sweep.py")), env))
        # 8b. control: a git repo with another origin is gated (being in a repo is not the exemption)
        other = root / "other-repo"
        other.mkdir()
        git(other, "init", "-q")
        git(other, "remote", "add", "origin", "https://github.com/assafkip/chief.git")
        expect_block("other repo gated", run(w(other / "scripts" / "backlog_sweep.py", script()), env),
                     "backlog-sweep")
        # 8c. a worktree of a client repo is gated too: the fleet worker's trees are this shape
        git(other, "-c", "user.email=f@example.invalid", "-c", "user.name=f",
            "commit", "-q", "--allow-empty", "-m", "base")
        owt = root / "other-wt"
        git(other, "worktree", "add", "-q", "--detach", str(owt), "HEAD")
        expect_block("client worktree gated", run(w(owt / "scripts" / "backlog_sweep.py", script()), env),
                     "backlog-sweep")
        # 9. temp space passes under the DEFAULT policy, and a non-temp path still gates
        default = {k: v for k, v in env.items() if k != "KIPI_REUSE_GATE_TEMP_ROOTS"}
        for p in ("/tmp/reuse-gate-probe/backlog_sweep.py",
                  "/private/var/folders/zz/reuse-gate-probe/backlog_sweep.py",
                  "/Users/nobody-reuse-gate/x/scratchpad/reuse-gate/backlog_sweep.py"):
            expect_pass(f"temp {p}", run(w(p, script()), default))
        expect_block("default policy still gates", run(w(
            "/Users/nobody-reuse-gate/x/backlog_sweep.py", script()), default), "backlog-sweep")
        # 10. only NEW executable scripts are in scope
        expect_pass("markdown", run(w(client / "backlog_sweep.md", "# notes\n"), env))
        expect_pass("json", run(w(client / "backlog_sweep.json", "{}\n"), env))
        expect_block("extensionless shebang", run(w(client / "bin" / "backlog-sweep",
                                                    "#!/bin/bash\n# Sweep the backlog.\necho hi\n"), env),
                     "backlog-sweep")
        for ext in (".sh", ".js", ".ts"):
            expect_block(f"new {ext}", run(w(client / f"backlog_sweep{ext}",
                                              "// Sweep the backlog.\n"), env), "backlog-sweep")
        existing = client / "existing_backlog_sweep.py"
        existing.write_text("print(0)\n")
        expect_pass("rewrite of an existing script", run(w(existing, script()), env))
        # 11. an Edit that creates a file is a creation too
        expect_block("edit-create", run({"file_path": str(client / "edit_backlog_sweep.py"),
                                         "old_string": "", "new_string": script()}, env, tool="Edit"),
                     "backlog-sweep")
        expect_pass("edit of an existing file", run({"file_path": str(existing),
                                                     "old_string": "print(0)",
                                                     "new_string": "print(2)"}, env, tool="Edit"))
        # 11b. a MultiEdit that creates a file is judged on ALL its edits applied
        me = str(client / "multi_backlog_sweep.py")
        first = {"old_string": "", "new_string": script()}
        expect_block("multiedit-create, no header", run(
            {"file_path": me, "edits": [first]}, env, tool="MultiEdit"), "backlog-sweep")
        expect_pass("multiedit-create, header in a later edit", run(
            {"file_path": me, "edits": [first, {"old_string": "print(1)", "new_string":
             "# Reuses-kipi: q-system/.q-system/scripts/backlog-sweep.py\nprint(1)"}]},
            env, tool="MultiEdit"))
        # 12. origin/main packed into packed-refs still resolves (cache hit, still gated)
        git(repo, "pack-refs", "--all")
        check("loose ref gone", not (repo / ".git" / "refs" / "remotes" / "origin" / "main").exists(),
              "pack-refs left the loose ref")
        expect_block("packed ref still gates", run(w(new, script()), env), "backlog-sweep")
        # 13. a broken map fails OPEN with a warning, and is not regenerated per write
        counter = root / "gen-calls.txt"
        bad = root / "bad-gen.py"
        bad.write_text(f"import sys\nopen({str(counter)!r}, 'a').write('x\\n')\nsys.exit(1)\n")
        benv = dict(env, KIPI_REUSE_GATE_CACHE=str(root / "cache-bad"), KIPI_REUSE_GATE_GEN=str(bad))
        expect_open("generator fails", run(w(new, script()), benv))
        stray = sorted(p.name for p in (root / "cache-bad").glob(".tree-*"))
        check("a failed run leaves no export behind", stray == [], f"left {stray}")
        expect_open("generator fails, second write", run(w(new, script()), benv))
        calls = counter.read_text().count("x") if counter.exists() else 0
        check("broken map generated once per sha", calls == 1, f"generator ran {calls} times")
        junk = root / "junk-gen.py"
        junk.write_text("import sys\na = sys.argv\nopen(a[a.index('--out') + 1], 'w').write('not json')\n")
        jenv = dict(env, KIPI_REUSE_GATE_CACHE=str(root / "cache-junk"), KIPI_REUSE_GATE_GEN=str(junk))
        expect_open("generator writes junk", run(w(new, script()), jenv))
        expect_open("repo missing", run(w(new, script()), dict(
            env, KIPI_REUSE_GATE_REPO=str(root / "no-such-repo"), KIPI_REUSE_GATE_CACHE=str(root / "c3"))))
        # 14. old cache files are pruned on a miss
        pc = root / "cache-prune"
        pc.mkdir()
        for i in range(15):
            f = pc / f"{i:040x}.json"
            f.write_text("{}")
            os.utime(f, (1_000_000 + i, 1_000_000 + i))
        # what a run killed midway leaves behind: an export dir and a temp file
        (pc / ".tree-killed" / "q-system").mkdir(parents=True)
        (pc / ".tmp-killed").write_text("partial")
        run(w(new, script()), dict(env, KIPI_REUSE_GATE_CACHE=str(pc)))
        kept = sorted(p.name for p in pc.glob("*.json"))
        check("prune keeps the newest", f"{sha}.json" in kept and len(kept) <= 10, f"kept {kept}")
        left = sorted(p.name for p in pc.glob(".t*"))
        check("prune drops killed-run leftovers", left == [], f"left {left}")
        # 14b. no checkout is kept: the gate leaves no worktree in the kipi repo
        wts = git(repo, "worktree", "list", "--porcelain")
        check("no gate worktree registered", str(cache) not in wts and str(pc) not in wts, wts)
        # 14c. after a broken map, the NEXT origin/main sha regenerates and gates again
        git(repo, "commit", "-q", "--allow-empty", "-m", "next sha")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        recovered = dict(env, KIPI_REUSE_GATE_CACHE=str(root / "cache-bad"))
        expect_block("next sha recovers after a broken map", run(w(new, script()), recovered),
                     "backlog-sweep")
        # 15. malformed input and the founder's kill switch pass
        expect_pass("malformed stdin", run(None, env, raw="not json"))
        expect_pass("kill switch", run(w(new, script()), dict(env, REUSE_GATE_OFF="1")))
        # 16. the enforcer names its Rule-ID (rule_gate.py links rule to code by it)
        check("rule id in hook", HOOK.is_file() and "RULE-2026-11-12-REUSE" in HOOK.read_text(),
              "hook missing or lacks RULE-2026-11-12-REUSE")

    if fails:
        print(f"FAIL: {len(fails)} failed, {passed} passed")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK: {passed} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
