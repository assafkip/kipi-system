#!/usr/bin/env python3
"""spec-merge-gate.py: a PR whose dsse spec is not closed at its head does not merge (ASK-4947).

Three layers, all in a temp dir with a fake gh on PATH; nothing reaches GitHub.
1. verdict(), pure: the brief's three cases plus the edges that decide them.
2. The CLI end to end against the fake gh: exit 2 names the spec, exit 0 is silent.
3. pr-verdict-lib.sh automerge_arm (linear-worker.sh, converge.sh): a refused spec
   never sends `gh pr merge --auto`, and a closed one does.
The scar: chief PR #395 merged with .prd-os/issues/gs-runtime-checkout.md in-progress.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
GATE = SCRIPTS / "spec-merge-gate.py"
LIB = SCRIPTS / "pr-verdict-lib.sh"

spec = importlib.util.spec_from_file_location("spec_merge_gate", GATE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

FAILS: list[str] = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
        FAILS.append(name)


def pr(branch="gs/gs-runtime-checkout", title="Pinned runtime checkout", body=""):
    return {"number": "395", "head": "a75249aa0000", "branch": branch, "title": title, "body": body}


def reader(statuses):
    return lambda sid: statuses.get(sid, "missing")


CODE = [("modified", "scripts/runtime_checkout.py"), ("modified", "tests/test_gs.py")]

print("-- verdict(), the brief's three cases")
why = g.verdict(pr(), CODE, {"gs-runtime-checkout", "gs-other"}, reader({"gs-runtime-checkout": "in-progress"}))
check("PR whose branch names an in-progress spec is refused", why.startswith("spec-merge-gate: REFUSED PR #395"), True)
check("... and the refusal names the spec and its status",
      ".prd-os/issues/gs-runtime-checkout.md reads status: in-progress" in why, True)
check("the same PR with the spec closed merges",
      g.verdict(pr(), CODE, {"gs-runtime-checkout"}, reader({"gs-runtime-checkout": "closed"})), "")
split = [("added", ".prd-os/issues/a-one.md"), ("added", ".prd-os/issues/a-two.md"), ("added", ".prd-os/prds/p.md")]
check("a split PR that adds open specs merges",
      g.verdict(pr(branch="plan/split-p", title="PRD p split into 2 issues"), split, {"a-one", "a-two"},
                reader({"a-one": "open", "a-two": "open"})), "")

print("-- verdict(), the edges")
in_diff = CODE + [("modified", ".prd-os/issues/gs-x.md")]
check("a spec in the diff that reads in-progress is refused, whatever the branch says",
      "gs-x.md reads status: in-progress" in g.verdict(pr(branch="feat/y", title="y"), in_diff, {"gs-x"},
                                                      reader({"gs-x": "in-progress"})), True)
check("a code PR editing an existing open spec is refused (it is not a split)",
      "gs-x.md reads status: open" in g.verdict(pr(branch="feat/y", title="y"), in_diff, {"gs-x"},
                                                reader({"gs-x": "open"})), True)
filed = CODE + [("added", ".prd-os/issues/gs-followup.md")]
check("a code PR that files a new open follow-up spec merges",
      g.verdict(pr(branch="feat/y", title="y"), filed, {"gs-followup"}, reader({"gs-followup": "open"})), "")
check("an open spec the branch names is refused even when this PR adds it",
      "gs-followup.md reads status: open" in g.verdict(pr(branch="gs/gs-followup", title="y"), filed, {"gs-followup"},
                                                      reader({"gs-followup": "open"})), True)
amend = [("modified", ".prd-os/issues/gs-x.md")]
check("a .prd-os-only PR amending an open spec merges",
      g.verdict(pr(branch="docs/amend", title="amend"), amend, {"gs-x"}, reader({"gs-x": "open"})), "")
check("a removed spec is not judged",
      g.verdict(pr(branch="feat/y", title="y"), [("removed", ".prd-os/issues/gs-x.md")], {"gs-x"},
                reader({"gs-x": "in-progress"})), "")
body395 = "H5 `gs-runtime-checkout` of prd-gs-health (track H). Depends on gs-done. Follow-up: gs-later."
st = {"gs-runtime-checkout": "in-progress", "gs-done": "closed", "gs-later": "open"}
why = g.verdict(pr(branch="feat/y", title="y", body=body395), CODE, set(st), reader(st))
check("a body naming an in-progress spec is refused (the #395 body)", "gs-runtime-checkout.md" in why, True)
check("... while the closed dependency and the open follow-up it cites are not",
      ("gs-done" in why, "gs-later" in why), (False, False))
check("an id is matched as a whole token, never inside a longer id",
      g.verdict(pr(branch="gs/gs-runtime-checkout-closeout", title="y"), CODE, {"gs-runtime-checkout"},
                reader({"gs-runtime-checkout": "in-progress"})), "")
check("the worker's lowercased branch names an uppercase spec id (linear-worker.sh BRANCH=sana/<lowercased>)",
      "ASK-1810.md reads status: in-progress" in g.verdict(pr(branch="sana/ask-1810", title="worker run: the thing"),
                                                           CODE, {"ASK-1810"}, reader({"ASK-1810": "in-progress"})), True)
check("a PR naming no spec merges",
      g.verdict(pr(branch="feat/y", title="y"), CODE, {"gs-x"}, reader({"gs-x": "in-progress"})), "")
check("spec_status reads frontmatter only",
      (g.spec_status("---\nid: x\nstatus: closed\n---\nstatus: open\n"), g.spec_status("status: closed\n"),
       g.spec_status("---\nid: x\n---\nstatus: closed\n")), ("closed", "", ""))

# ---------------------------------------------------------------- fake gh
tmp = Path(tempfile.mkdtemp(prefix="spec-gate-test-"))
bindir = tmp / "bin"
bindir.mkdir()
state = tmp / "state.json"
calls = tmp / "gh.calls"
(bindir / "gh").write_text(f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
open({str(calls)!r}, "a").write(" ".join(args) + "\\n")
st = json.load(open({str(state)!r}))
joined = " ".join(args)
if st.get("reads502") and args[:2] != ["pr", "merge"] and "autoMergeRequest" not in joined:
    print("gh: Something went wrong (HTTP 502)", file=sys.stderr); sys.exit(1)
if args[:2] == ["pr", "view"] and "autoMergeRequest" in joined:
    print("true" if st.get("armed") else "false"); sys.exit(0)
if args[:2] == ["pr", "view"]:
    print(json.dumps({{"number": 395, "headRefOid": "a75249aa0000", "headRefName": st["branch"],
                      "title": "t", "body": ""}})); sys.exit(0)
if args[:2] == ["pr", "merge"]:
    st["armed"] = "--disable-auto" not in args
    json.dump(st, open({str(state)!r}, "w")); sys.exit(0)
if args[0] == "api" and "/files" in joined:
    for s, f in st["files"]: print(s + "\\t" + f)
    sys.exit(0)
if args[0] == "api" and "contents/.prd-os/issues?" in joined:
    for k in st["specs"]: print(k + ".md")
    sys.exit(0)
if args[0] == "api" and "contents/.prd-os/issues/" in joined:
    sid = joined.split("contents/.prd-os/issues/")[1].split(".md")[0]
    if sid not in st["specs"]:
        print("HTTP 404: Not Found", file=sys.stderr); sys.exit(1)
    print("---\\nid: " + sid + "\\nstatus: " + st["specs"][sid] + "\\n---\\n"); sys.exit(0)
print("fake gh: unhandled " + joined, file=sys.stderr); sys.exit(1)
""")
(bindir / "gh").chmod(0o755)
env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
for k in ("GH_REPO", "GH_HOST", "GH_TOKEN"):
    env.pop(k, None)
repo = tmp / "repo"
(repo / ".prd-os" / "issues").mkdir(parents=True)
nospec = tmp / "nospec"
nospec.mkdir()


def setup(spec_status, armed=False, reads502=False):
    state.write_text(json.dumps({"branch": "gs/gs-runtime-checkout", "armed": armed, "files": CODE,
                                 "specs": {"gs-runtime-checkout": spec_status}, "reads502": reads502}))
    calls.write_text("")


def cli(n="395"):
    p = subprocess.run([sys.executable, str(GATE), n, "--dir", str(repo)], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.strip()


print("-- the CLI against a fake gh")
setup("in-progress")
rc, out = cli()
check("in-progress spec -> exit 2 with the refusal line", (rc, "gs-runtime-checkout.md reads status: in-progress" in out),
      (2, True))
setup("closed")
check("closed spec -> exit 0, silent", cli(), (0, ""))
check("a PR URL is accepted (lessons-daily.sh holds one)", cli("https://github.com/o/r/pull/395"), (0, ""))
calls.write_text("")
p = subprocess.run([sys.executable, str(GATE), "395", "--dir", str(nospec)], capture_output=True, text=True, env=env)
check("a checkout with no .prd-os/issues is allowed with no gh call",
      (p.returncode, calls.read_text()), (0, ""))
state.write_text(json.dumps({"broken": True}))
rc, out = cli()
check("a gh read that fails is exit 3, never an allow", (rc, "COULD NOT TELL" in out), (3, True))


def arm():
    script = f'. "{LIB}"; automerge_arm 395 "{repo}"; echo "$AUTOMERGE_ARM_STATE|${{AUTOMERGE_ARM_HELD:-}}|$AUTOMERGE_ARM_ERR"'
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr


def arms():
    return calls.read_text().count("pr merge --auto --squash 395")


print("-- automerge_arm (linear-worker.sh, converge.sh) asks the gate first")
setup("in-progress")
state_out = arm()
check("in-progress spec -> unarmed, with the gate's line as the error",
      (state_out.split("|")[0], "gs-runtime-checkout.md reads status: in-progress" in state_out), ("unarmed", True))
check("... and gh pr merge --auto was never sent", arms(), 0)
setup("in-progress", armed=True)
state_out = arm()
check("an arm set by someone else is taken back off", (state_out.split("|")[0], "--disable-auto" in calls.read_text()),
      ("unarmed", True))
setup("closed")
check("closed spec -> armed by this call", (arm().split("|")[0], arms()), ("armed", 1))
setup("in-progress")
check("a refusal is marked HELD, so callers can tell it from a gh refusal", arm().split("|")[1], "1")
# PR #816 review finding 1: exit 3 (a gh read failed) took a correct arm back off.
setup("closed", armed=True, reads502=True)
out = arm()
check("a gh read failure (exit 3) never removes an arm: no --disable-auto, state not unarmed, not HELD",
      ("--disable-auto" in calls.read_text(), out.split("|")[0] == "unarmed", out.split("|")[1]), (False, False, ""))
check("... and it never arms either", arms(), 0)

# PR #816 review round 2: python3 exits 2 for a gate it cannot open, and that read
# as a quiet hold. A gate that cannot run is "could not tell", never HELD.
setup("closed")
lib_copy = tmp / "libcopy"
lib_copy.mkdir()
(lib_copy / "pr-verdict-lib.sh").write_text(LIB.read_text())
for f in ("repo-slug-lib.sh",):
    if (SCRIPTS / f).exists():
        (lib_copy / f).write_text((SCRIPTS / f).read_text())
p2 = subprocess.run(["bash", "-c", f'. "{lib_copy}/pr-verdict-lib.sh"; automerge_arm 395 "{repo}"; '
                     f'echo "$AUTOMERGE_ARM_STATE|${{AUTOMERGE_ARM_HELD:-}}|$AUTOMERGE_ARM_ERR"'],
                    capture_output=True, text=True, env=env)
out = (p2.stdout.strip().splitlines() or [""])[-1]
check("a gate that cannot run (python exit 2, no REFUSED line) is never HELD and never disarms",
      (out.split("|")[1] if "|" in out else out, "--disable-auto" in calls.read_text()), ("", False))

# ---------------------------------------------------------------- the worker's words
# PR #816 review finding 2: linear-worker.sh's arm_automerge paged a spec hold as
# "sits there forever. Needs a human: gh pr merge --auto --squash N", which is false
# (pr-owner.py re-asks hourly) and names the merge the gate just refused.
WORKER = SCRIPTS / "linear-worker.sh"
src = WORKER.read_text().splitlines()
start = next(i for i, l in enumerate(src) if l.startswith("arm_automerge() {"))
end = next(i for i in range(start, len(src)) if src[i] == "}")
fn = tmp / "arm_automerge.sh"
fn.write_text("\n".join(src[start:end + 1]) + "\n")
pages = tmp / "pages"
notify = tmp / "notify.sh"
notify.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{pages}"\n')
notify.chmod(0o755)


def worker_arm():
    pages.write_text("")
    script = (f'. "{LIB}"; say() {{ printf "LOG: %s\\n" "$*"; }}; page_once() {{ return 0; }}; '
              f'clear_automerge_pages() {{ :; }}; record_automerge() {{ :; }}; artifact_key() {{ echo k; }}; '
              f'NOTIFY="{notify}"; LOG=/dev/null; ISSUE=ASK-9999; REVIEWS_DIR="{tmp}"; TARGET_SLUG=s; '
              f'. "{fn}"; arm_automerge 395 "{repo}"; echo "STATE=$AUTOMERGE"')
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    return p.stdout + p.stderr, pages.read_text()


print("-- linear-worker.sh arm_automerge reports a spec hold as a hold")
setup("in-progress")
log, paged = worker_arm()
check("the worker extracted and ran (sanity)", "STATE=unarmed" in log, True)
check("a spec hold names the spec in the log", "gs-runtime-checkout.md reads status: in-progress" in log, True)
check("... never tells anyone to run the merge the gate refused", "gh pr merge --auto" in log + paged, False)
check("... never says it sits forever", "forever" in log + paged, False)
check("... and pages nobody: closeout is the expected next step", paged, "")

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("all spec-merge-gate checks passed")
