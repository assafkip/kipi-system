#!/usr/bin/env python3
"""test-job-checkouts.py -- no launchd job runs its code from the shared checkout (ASK-3966).

Founder, 2026-11-08: "ensure everyitng runs on separate work trees so things done
conflict". 14 installed com.kipi.* jobs ran from ~/projects/kipi-system, the checkout a
human works in and the orchestrator fast-forwards.

RED FIRST. Point KIPI_INSTALL_PLIST_UNDER_TEST at main's install-plist.sh: every committed
template renders into that checkout, and this prints RED with the count.

GREEN:
  * every committed template renders with --render-only (scratch HOME, nothing created);
  * only the labels in job-checkouts.json shared_exceptions point at the checkout the
    renderer lives in, and each exception names a reason, a ticket and at most 30 days;
  * every other job starts `/bin/bash <its own tree>/.../kipi-job-pinned.sh`, its tree is
    <HOME>/<pinned_root>/<label>/kipi-system, its working directory (if any) is that tree,
    and it writes no stdout or stderr inside it (a job that writes inside its checkout
    dirties it, and the next advance refuses);
  * the wrapper, in a scratch git fixture with its own bare origin: advances a tree to
    origin/main and runs the job there; on a dirty tree it refuses, keeps the edit, still
    runs the job and files once; it survives the advance rewriting the wrapper itself;
  * install, in the same fixture: creates the job tree locked, then installs; refuses and
    installs nothing when origin/main has no wrapper.
MUTANTS: the wrapper insertion removed from a fixture copy of install-plist.sh; an
exception with no ticket; an exception of 31 days.

NEVER A LIVE PATH: renders go to scratch with a scratch HOME, the fixture is a scratch
repo with a scratch origin, and launchctl is the KIPI_LAUNCHCTL test seam.

Run: python3 q-system/.q-system/scripts/test/test-job-checkouts.py   (exit 0 = pass)
"""

from __future__ import annotations

import copy
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2] if len(SCRIPTS.parents) > 2 else SCRIPTS
INSTALLER = Path(os.environ.get("KIPI_INSTALL_PLIST_UNDER_TEST") or SCRIPTS / "install-plist.sh")
UNDER_REPO = INSTALLER.resolve().parents[3] if len(INSTALLER.resolve().parents) > 3 else REPO
TABLE_PATH = UNDER_REPO / "q-system" / ".q-system" / "job-checkouts.json"
WRAPPER_REL = "q-system/.q-system/scripts/kipi-job-pinned.sh"
SANDBOX = Path(tempfile.mkdtemp(prefix="test-job-checkouts-"))
FAILS: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def git(*args, cwd):
    p = run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
            cwd=str(cwd))
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def labels_of(repo: Path) -> list[str]:
    out = git("ls-files", "--", "*/com.kipi.*.plist", "com.kipi.*.plist", cwd=repo)
    return sorted({Path(l).stem for l in out.splitlines() if l})


def render(installer: Path, label: str, home: Path) -> tuple[int, str, str]:
    dest = SANDBOX / "renders" / f"{label}.plist"
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    p = run(["bash", str(installer), label, "--render-only", str(dest)], env=env)
    return p.returncode, (dest.read_text() if dest.is_file() else ""), p.stderr


def exception_problems(table: dict, labels: list[str]) -> list[str]:
    out = []
    for label, row in sorted((table.get("shared_exceptions") or {}).items()):
        if label not in labels:
            out.append(f"{label}: an exception for a label with no committed template")
        if not str(row.get("reason", "")).strip():
            out.append(f"{label}: an exception gives no reason")
        if not re.match(r"^ASK-\d+$", str(row.get("ticket", ""))):
            out.append(f"{label}: an exception names no ticket")
        try:
            days = (datetime.strptime(row["expires"], "%Y-%m-%d") - datetime.strptime(row["since"], "%Y-%m-%d")).days
            if not 0 < days <= 30:
                out.append(f"{label}: an exception runs 1 to 30 days, this one {days}")
        except (KeyError, ValueError):
            out.append(f"{label}: since and expires must be YYYY-MM-DD")
    return out


print("test-job-checkouts.py")
labels = labels_of(UNDER_REPO)
shared = str(UNDER_REPO)
home = SANDBOX / "home"
hits, renders, bad_renders = [], {}, []
for label in labels:
    rc, text, err = render(INSTALLER, label, home)
    if rc != 0:
        bad_renders.append(f"{label}: rc {rc} {err.strip()[-160:]}")
        continue
    renders[label] = text
    if shared in text:
        hits.append(label)

if not TABLE_PATH.is_file():
    print(f"RED: {len(hits)} of {len(labels)} committed job templates render into the shared checkout "
          f"{shared} and there is no job-checkouts.json: {', '.join(hits)}")
    sys.exit(1)

table = json.loads(TABLE_PATH.read_text())
exceptions = set(table.get("shared_exceptions") or {})

print("-- every template renders, and only the named exceptions point at the shared checkout")
check("every committed template renders", bad_renders, [])
check("renders that point at the shared checkout are exactly the exceptions",
      sorted(set(hits) - exceptions), [])
check("render-only creates nothing under HOME", home.exists(), False)
check("every exception is bounded and named", exception_problems(table, labels), [])

print("-- every pinned job starts the wrapper in its own tree")
root = Path(home) / table["pinned_root"]
for label in sorted(set(renders) - exceptions):
    tree = root / label / "kipi-system"
    # Comments stripped first: 5 committed templates carry `--` inside a comment, which
    # XML forbids and expat refuses while plutil and launchd accept it. This check reads
    # structure, not XML purity, so it must not fail on what launchd runs fine.
    try:
        d = plistlib.loads(re.sub(r"<!--.*?-->", "", renders[label], flags=re.S).encode())
    except Exception as exc:  # noqa: BLE001 - an unparseable render IS the finding
        check(f"{label}: renders a strict plist", type(exc).__name__, "no error")
        continue
    args = d.get("ProgramArguments") or []
    if not args:
        continue
    check(f"{label}: starts /bin/bash <its tree>/{WRAPPER_REL}", args[:2], ["/bin/bash", str(tree / WRAPPER_REL)])
    wd = d.get("WorkingDirectory")
    if wd:
        check(f"{label}: its working directory is its own tree", wd, str(tree))
    inside = [k for k in ("StandardOutPath", "StandardErrorPath") if str(d.get(k, "")).startswith(str(tree))]
    check(f"{label}: writes no stdout or stderr inside its tree", inside, [])

print("-- mutants on the table (in memory)")
m = copy.deepcopy(table)
first = sorted(m["shared_exceptions"])[0]
m["shared_exceptions"][first]["ticket"] = ""
check("mutant goes red: an exception with no ticket", any("names no ticket" in p for p in exception_problems(m, labels)), True)
m = copy.deepcopy(table)
m["shared_exceptions"][first].update(since="2026-11-08", expires="2026-12-09")
check("mutant goes red: an exception of 31 days", any("this one 31" in p for p in exception_problems(m, labels)), True)

# --- the fixture: a scratch skeleton with its own bare origin named kipi-system.git ------
print("-- the wrapper, in a scratch repo")
fx = SANDBOX / "fx"
origin = fx / "remote" / "kipi-system.git"
skel = fx / "skel"
origin.parent.mkdir(parents=True)
git("init", "-q", "--bare", str(origin), cwd=fx)
git("init", "-q", str(skel), cwd=fx)
git("remote", "add", "origin", str(origin), cwd=skel)
scripts = skel / "q-system" / ".q-system" / "scripts"
scripts.mkdir(parents=True)
wrapper_src = (UNDER_REPO / WRAPPER_REL).read_text()
(scripts / "kipi-job-pinned.sh").write_text(wrapper_src)
(skel / "f.txt").write_text("one\n")
git("add", "-A", cwd=skel)
git("commit", "-qm", "c1", cwd=skel)
git("push", "-q", "origin", "HEAD:main", cwd=skel)
c1 = git("rev-parse", "HEAD", cwd=skel)

tree = fx / "home" / ".local/state/kipi/jobs" / "com.kipi.fx" / "kipi-system"
tree.parent.mkdir(parents=True)
git("fetch", "-q", "origin", cwd=skel)
git("worktree", "add", "-q", "--detach", "--lock", str(tree), "origin/main", cwd=skel)

# c2 rewrites the wrapper itself (one more comment line) and moves f.txt.
(scripts / "kipi-job-pinned.sh").write_text(wrapper_src.replace("#!/bin/bash\n", "#!/bin/bash\n# c2\n", 1))
(skel / "f.txt").write_text("two\n")
git("commit", "-qam", "c2", cwd=skel)
git("push", "-q", "origin", "HEAD:main", cwd=skel)
c2 = git("rev-parse", "HEAD", cwd=skel)

log = fx / "pin.log"
notes = fx / "notify.calls"
notify = fx / "notify.sh"
notify.write_text(f"#!/bin/sh\necho \"$1\" >> {notes}\n")
notify.chmod(0o755)
env = dict(os.environ, HOME=str(fx / "home"), KIPI_JOB_PIN_LOG=str(log), KIPI_NOTIFY=str(notify))
job = ["/bin/sh", "-c", "git rev-parse HEAD > ran-at; pwd > ran-in"]
p = run(["bash", str(tree / WRAPPER_REL), *job], env=env)
check("the job runs (exit 0)", p.returncode, 0)
check("the tree was advanced to origin/main before the job ran", (tree / "ran-at").read_text().strip(), c2)
check("the job ran inside its own tree", Path((tree / "ran-in").read_text().strip()).resolve(), tree.resolve())
check("it survived the advance rewriting the wrapper itself",
      (tree / WRAPPER_REL).read_text().startswith("#!/bin/bash\n# c2\n"), True)
check("the log names the advance and the label", "com.kipi.fx: advanced" in log.read_text(), True)
for f in ("ran-at", "ran-in"):
    (tree / f).unlink()

# Dirty: the tree holds an edit to a file origin changes again. Refuse, keep it, still run, file once.
(tree / "f.txt").write_text("a human edit\n")
(skel / "f.txt").write_text("three\n")
git("commit", "-qam", "c3", cwd=skel)
git("push", "-q", "origin", "HEAD:main", cwd=skel)
p = run(["bash", str(tree / WRAPPER_REL), *job], env=env)
check("dirty: the job still runs", p.returncode, 0)
check("dirty: it runs on the head it had", (tree / "ran-at").read_text().strip(), c2)
check("dirty: the edit is kept, never reset", (tree / "f.txt").read_text(), "a human edit\n")
check("dirty: the refusal is logged", "could not advance" in log.read_text(), True)
run(["bash", str(tree / WRAPPER_REL), *job], env=env)
check("dirty: filed once a day, not once a run",
      len(notes.read_text().splitlines()) if notes.exists() else 0, 1)
check("no job command is refused with exit 2", run(["bash", str(tree / WRAPPER_REL)], env=env).returncode, 2)

# --- install, in the same fixture --------------------------------------------------------
print("-- install creates the job tree locked, or installs nothing")
for rel in ("q-system/.q-system/scripts/install-plist.sh", "q-system/.q-system/job-checkouts.json"):
    (skel / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(UNDER_REPO / rel, skel / rel)
fixture_table = json.loads((skel / "q-system/.q-system/job-checkouts.json").read_text())
fixture_table["shared_exceptions"] = {}
(skel / "q-system/.q-system/job-checkouts.json").write_text(json.dumps(fixture_table))
(scripts / "com.kipi.fxjob.plist").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">\n<dict>\n'
    '  <key>Label</key><string>com.kipi.fxjob</string>\n'
    '  <key>ProgramArguments</key>\n  <array>\n    <string>/bin/echo</string><string>__KIPI_REPO__</string>\n  </array>\n'
    '  <key>StandardOutPath</key><string>__HOME__/.config/kipi/fxjob.out</string>\n'
    '</dict>\n</plist>\n')
git("checkout", "-q", "--", "f.txt", cwd=tree)
git("add", "-A", cwd=skel)
git("commit", "-qm", "c4 installer", cwd=skel)
git("push", "-q", "origin", "HEAD:main", cwd=skel)
stub = fx / "launchctl"
stub.write_text("#!/bin/sh\nexit 0\n")
stub.chmod(0o755)
ienv = dict(env, KIPI_LAUNCHCTL=str(stub))
fx_installer = skel / "q-system/.q-system/scripts/install-plist.sh"
p = run(["bash", str(fx_installer), "com.kipi.fxjob"], env=ienv)
jt = fx / "home" / ".local/state/kipi/jobs" / "com.kipi.fxjob" / "kipi-system"
check("install exits 0", p.returncode, 0 if p.returncode == 0 else f"{p.returncode}: {p.stderr.strip()[-200:]}")
check("install created the job's own tree", (jt / ".git").exists(), True)
porcelain = git("worktree", "list", "--porcelain", cwd=skel)
block = [b for b in porcelain.split("\n\n") if f"worktree {jt}" in b or f"worktree {jt.resolve()}" in b]
check("the job tree is locked, so worktree-reaper keeps it", bool(block) and "locked" in block[0], True)
installed = fx / "home" / "Library/LaunchAgents/com.kipi.fxjob.plist"
check("the installed job starts the wrapper in its own tree",
      plistlib.loads(installed.read_bytes())["ProgramArguments"][:2] if installed.exists() else None,
      ["/bin/bash", str(jt / WRAPPER_REL)])

# Mutant: the renderer without the wrapper insertion.
src = fx_installer.read_text()
anchor = '"$TEMPLATE" | wrap_pinned'
check("mutant anchor present once", src.count(anchor), 1)
fx_installer.write_text(src.replace(anchor, '"$TEMPLATE"', 1))
_, text, _ = render(fx_installer, "com.kipi.fxjob", fx / "home")
check("mutant goes red: no wrapper in front of the job", "kipi-job-pinned.sh" in text, False)
fx_installer.write_text(src)

# Refuse: origin/main has no wrapper, so a new job tree would have nothing to run.
git("rm", "-q", WRAPPER_REL, cwd=skel)
git("commit", "-qm", "c5 no wrapper", cwd=skel)
git("push", "-q", "origin", "HEAD:main", cwd=skel)
(scripts / "kipi-job-pinned.sh").write_text(wrapper_src)  # the renderer's own checkout keeps one
(scripts / "com.kipi.fxjob2.plist").write_text((scripts / "com.kipi.fxjob.plist").read_text().replace("fxjob", "fxjob2"))
git("add", "q-system/.q-system/scripts/com.kipi.fxjob2.plist", cwd=skel)
git("commit", "-qm", "c6 second template", cwd=skel)
p = run(["bash", str(fx_installer), "com.kipi.fxjob2"], env=ienv)
check("a job tree with no wrapper refuses the install", p.returncode != 0 and "REFUSED" in p.stderr, True)
check("...and nothing was installed", (fx / "home" / "Library/LaunchAgents/com.kipi.fxjob2.plist").exists(), False)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
