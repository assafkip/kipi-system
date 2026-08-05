#!/usr/bin/env bash
# Pairs with detect_stale_runtime_plugins in
# q-system/.q-system/scripts/fleet-health-daily.py.
#
# Scar (codex review of PR #105, blocker, 2026-08-05): runtime-plugin-freshness.py
# shipped with its own green test and NO production caller. The capability gate
# ran the checker against fixtures and nothing ever pointed it at real runtime
# state, so a detector that could never fire read as protection.
#
# test-runtime-plugin-freshness.sh already covers the CHECKER. This file covers
# the thing that one structurally cannot: that the checker is REACHED from the
# unattended daily job, and that the reaching code turns a stale runtime into a
# finding. Deleting the DETECTORS entry must make this go red -- that is the
# whole point of a wiring test, and a suite where removing the call site stays
# green is the defect this repo keeps re-finding.
#
# Hermetic: builds its own plugin root under mktemp and points the detector at it
# by monkeypatching the checker module's DEFAULT_PLUGIN_ROOT. Nothing here reads
# the real ~/.claude/plugins and nothing reaches the network.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

echo "== runtime-plugin-freshness is wired to the daily job =="

# ---------------------------------------------------------------------------
# 1. THE WIRING ITSELF. Registered in DETECTORS, with a callable detect.
# ---------------------------------------------------------------------------
WIRED="$(ROOT="$ROOT" python3 - <<'PY'
import importlib.util, os, sys
root = os.environ["ROOT"]
spec = importlib.util.spec_from_file_location(
    "fh", os.path.join(root, "q-system/.q-system/scripts/fleet-health-daily.py"))
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)
hits = [d for d in fh.DETECTORS if d.get("id") == "runtime-plugin-stale"]
if not hits:
    print("MISSING"); sys.exit(0)
d = hits[0]
if not callable(d.get("detect")):
    print("NOTCALLABLE"); sys.exit(0)
if d["detect"].__name__ != "detect_stale_runtime_plugins":
    print("WRONGFN"); sys.exit(0)
print("OK")
PY
)"
[ "$WIRED" = "OK" ] \
  && ok "runtime-plugin-stale is in DETECTORS and calls detect_stale_runtime_plugins" \
  || bad "the detector is NOT wired into the daily job (got '$WIRED') -- the checker has no production caller"

# ---------------------------------------------------------------------------
# 2. IT FIRES on a stale runtime, and 3. STAYS QUIET on a matching one.
#
# Both directions, because a detector that always fires and a detector that
# never fires are equally useless and only the pair tells them apart.
# ---------------------------------------------------------------------------
RESULT="$(ROOT="$ROOT" python3 - <<'PY'
import importlib.util, json, os, tempfile
from pathlib import Path

root = os.environ["ROOT"]
S = os.path.join(root, "q-system/.q-system/scripts")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(plugin_root, installed_version, marketplace_version):
    """A plugin root shaped like the REAL producer.

    Shapes copied from the live files rather than invented: installed_plugins.json
    keys are '<name>@<marketplace>' mapping to a LIST of {scope, version}, and
    each marketplace plugin carries .claude-plugin/plugin.json with name+version.
    A fixture whose shape the producer never emits tests nothing.
    """
    p = Path(plugin_root)
    mk = p / "marketplaces" / "kipi" / "plugins" / "prd-os" / ".claude-plugin"
    mk.mkdir(parents=True)
    (mk / "plugin.json").write_text(
        json.dumps({"name": "prd-os", "version": marketplace_version}))
    (p / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"prd-os@kipi": [{"scope": "user", "version": installed_version}]}}))


out = {}
# label, installed, marketplace, extra source appended to the shim, corrupt-registry
CASES = (
    ("stale",  "0.1.0",  "0.16.6", "", False),
    ("fresh",  "0.16.6", "0.16.6", "", False),
    # A plugin commit that changes runtime code WITHOUT bumping a version: every
    # installed version matches, and the clone is still behind origin/main. The
    # detector dropped this signal entirely until codex round 2 caught it.
    ("behind", "0.16.6", "0.16.6",
     "\ndef clone_commits_behind(marketplace):\n    return 3\n", False),
    # Unreadable state must not read as healthy state.
    ("broken", "0.16.6", "0.16.6", "", True),
    # Installed but retired from the marketplace: still loaded at runtime.
    ("retired", "0.16.6", "0.16.6", "", False),
)
for label, inst, mkt, extra, corrupt in CASES:
    with tempfile.TemporaryDirectory() as td:
        build(td, inst, mkt)
        if corrupt:
            (Path(td) / "installed_plugins.json").write_text("{not json at all")
        if label == "retired":
            # A plugin the registry still installs but the marketplace no longer
            # ships. Same producer shape, one extra key.
            reg = Path(td) / "installed_plugins.json"
            data = json.loads(reg.read_text())
            data["plugins"]["ghost-plugin@kipi"] = [{"scope": "user", "version": "0.4.0"}]
            reg.write_text(json.dumps(data))
        fh = load("fh", os.path.join(S, "fleet-health-daily.py"))
        # THE SEAM IS fh.HERE. The detector resolves the checker as
        # `HERE / "runtime-plugin-freshness.py"` and imports it fresh, so the
        # only way to aim it at a fixture is to hand it a directory holding a
        # copy whose DEFAULT_PLUGIN_ROOT points at that fixture. Stubbing the
        # seam rather than the real path is what keeps this off the live
        # ~/.claude/plugins -- a suite that is quiet because it happened to read
        # a healthy real runtime is not isolation.
        src = open(os.path.join(S, "runtime-plugin-freshness.py")).read().replace(
            'DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"',
            f'DEFAULT_PLUGIN_ROOT = Path({td!r})')
        assert f'Path({td!r})' in src, "the DEFAULT_PLUGIN_ROOT patch did not apply"
        if extra:
            before = src
            src = src + extra
            assert src != before, "the shim override did not apply"
        shim = Path(td) / "shim"
        shim.mkdir()
        (shim / "runtime-plugin-freshness.py").write_text(src)
        fh.HERE = shim
        out[label] = fh.detect_stale_runtime_plugins(None)

# The missing-checker case needs no plugin root at all: point HERE at an empty dir.
with tempfile.TemporaryDirectory() as td:
    fh = load("fh", os.path.join(S, "fleet-health-daily.py"))
    empty = Path(td) / "empty"
    empty.mkdir()
    fh.HERE = empty
    out["nochecker"] = fh.detect_stale_runtime_plugins(None)


def sub(label):
    return out[label][0]["subject"] if out[label] else ""


print(json.dumps({
    "stale_count": len(out["stale"]),
    "stale_subject": sub("stale"),
    "stale_body_has_versions": bool(out["stale"]) and "0.16.6" in out["stale"][0]["body"] and "0.1.0" in out["stale"][0]["body"],
    "fresh_count": len(out["fresh"]),
    "behind_count": len(out["behind"]),
    "behind_subject": sub("behind"),
    "behind_body_has_count": bool(out["behind"]) and "3" in out["behind"][0]["body"],
    "broken_count": len(out["broken"]),
    "broken_subject": sub("broken"),
    "nochecker_count": len(out["nochecker"]),
    "nochecker_subject": sub("nochecker"),
    "retired_count": len(out["retired"]),
    "retired_subject": sub("retired"),
    "retired_names_ghost": bool(out["retired"]) and "ghost-plugin" in out["retired"][0]["body"],
}))
PY
)"
echo "    detector result: $RESULT"

get() { printf '%s' "$RESULT" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }

[ "$(get stale_count)" = "1" ] \
  && ok "a stale runtime produces exactly one finding" \
  || bad "a stale runtime produced $(get stale_count) findings (want 1) -- the detector cannot fire"

[ "$(get stale_subject)" = "runtime-plugin-freshness" ] \
  && ok "the finding carries the stable dedup subject" \
  || bad "subject was '$(get stale_subject)' -- an unstable subject files a new Linear issue every run"

[ "$(get stale_body_has_versions)" = "True" ] \
  && ok "the body names both the installed and the marketplace version" \
  || bad "the body does not name both versions, so the issue is not actionable"

[ "$(get fresh_count)" = "0" ] \
  && ok "a matching runtime produces NO finding" \
  || bad "a matching runtime still produced $(get fresh_count) findings -- the detector always fires, which is the same as never"

# --- clone-behind drift, versions all matching (codex round 2, major) --------
[ "$(get behind_count)" = "1" ] \
  && ok "a clone behind origin/main fires even when every version matches" \
  || bad "clone-behind produced $(get behind_count) findings (want 1) -- a plugin commit that does not bump a version is invisible"

[ "$(get behind_subject)" = "runtime-plugin-freshness" ] \
  && ok "the behind finding shares the staleness subject (one issue, not two)" \
  || bad "behind subject was '$(get behind_subject)'"

# The COUNT must stay out of the body: finding_hash covers the body, so a number
# that moves on every merge rewrites the Linear issue daily.
[ "$(get behind_body_has_count)" = "False" ] \
  && ok "the behind body records the fact, not the churning commit count" \
  || bad "the behind body contains the commit count -- that rewrites the issue on every merge"

# --- unreadable state must not read as healthy state (codex round 2, major) --
[ "$(get broken_count)" = "1" ] \
  && ok "an unreadable plugin registry produces a finding, not silence" \
  || bad "malformed registry produced $(get broken_count) findings (want 1) -- silence is indistinguishable from healthy"

[ "$(get broken_subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "the cannot-run finding has its own subject, so it cannot pose as a staleness verdict" \
  || bad "broken subject was '$(get broken_subject)'"

[ "$(get nochecker_count)" = "1" ] \
  && ok "a missing checker produces a finding, not silence" \
  || bad "a missing checker produced $(get nochecker_count) findings (want 1) -- the detector would disable itself quietly"

[ "$(get nochecker_subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "the missing-checker finding uses the cannot-run subject" \
  || bad "nochecker subject was '$(get nochecker_subject)'"


# --- a retired plugin is still running code (codex round 4, major) -----------
[ "$(get retired_count)" = "1" ] \
  && ok "a plugin installed but absent from the marketplace produces a finding" \
  || bad "retired plugin produced $(get retired_count) findings (want 1) -- retired code keeps running unreported"

[ "$(get retired_names_ghost)" = "True" ] \
  && ok "the retired finding names the plugin" \
  || bad "the retired finding does not name the plugin, so it is not actionable"

# --- the detector REFRESHES the remote ref itself (codex round 4, major) -----
# clone_commits_behind reads the ALREADY-FETCHED origin/main. If nothing ever
# fetches, the clone and its cached remote ref sit at the same commit forever and
# the count is 0: PASS reported indefinitely while merged plugin code never
# arrives. The checker deliberately stays off the network (it runs in CI and
# interactively); the DETECTOR runs unattended on a networked box, so the fetch
# belongs at that call site.
#
# This fixture is the only one here with a REAL git clone and a REAL bare remote.
# The remote is advanced and the clone is deliberately NOT fetched, so the case
# can only pass if the detector fetched on its own. Local paths only, no network.
FETCHRES="$(ROOT="$ROOT" python3 - <<'PY2'
import importlib.util, json, os, subprocess, tempfile
from pathlib import Path

root = os.environ["ROOT"]
S = os.path.join(root, "q-system/.q-system/scripts")
G = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


out = {}
with tempfile.TemporaryDirectory() as td:
    root_p = Path(td)
    bare = root_p / "remote.git"
    run("git", "init", "-q", "--bare", str(bare))
    run("git", "-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main")

    seed = root_p / "seed"
    seed.mkdir()
    (seed / "plugins").mkdir()
    (seed / "plugins" / "seed.md").write_text("a\n")
    run(*G, "init", "-q", cwd=seed)
    run(*G, "add", "-A", cwd=seed); run(*G, "commit", "-qm", "base", cwd=seed)
    run(*G, "push", "-q", str(bare), "HEAD:main", cwd=seed)

    mk = root_p / "marketplaces" / "kipi"
    mk.parent.mkdir(parents=True)
    run("git", "clone", "-q", str(bare), str(mk))
    man = mk / "plugins" / "prd-os" / ".claude-plugin"
    man.mkdir(parents=True)
    (man / "plugin.json").write_text(json.dumps({"name": "prd-os", "version": "0.16.6"}))
    (root_p / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"prd-os@kipi": [{"scope": "user", "version": "0.16.6"}]}}))

    # Advance the remote with a PLUGIN commit. The clone is NOT fetched here.
    (seed / "plugins" / "new.md").write_text("b\n")
    run(*G, "add", "-A", cwd=seed); run(*G, "commit", "-qm", "plugin change", cwd=seed)
    run(*G, "push", "-q", str(bare), "HEAD:main", cwd=seed)

    # Sanity: with the STALE cached ref the count must be 0, or the case proves nothing.
    rpf_probe = load("rpf_probe", os.path.join(S, "runtime-plugin-freshness.py"))
    out["before_fetch_behind"] = rpf_probe.clone_commits_behind(mk)

    fh = load("fh", os.path.join(S, "fleet-health-daily.py"))
    src = open(os.path.join(S, "runtime-plugin-freshness.py")).read().replace(
        'DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"',
        f'DEFAULT_PLUGIN_ROOT = Path({td!r})')
    shim = root_p / "shim"; shim.mkdir()
    (shim / "runtime-plugin-freshness.py").write_text(src)
    fh.HERE = shim
    out["findings"] = len(fh.detect_stale_runtime_plugins(None))

print(json.dumps({"before": out["before_fetch_behind"], "findings": out["findings"]}))
PY2
)"
echo "    fetch-case result: $FETCHRES"
fget() { printf '%s' "$FETCHRES" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }

# Precondition. If the cached ref already showed drift, the next assertion would
# pass without the detector ever fetching, and the case would prove nothing.
[ "$(fget before)" = "0" ] \
  && ok "precondition: the un-fetched clone reports 0 behind" \
  || bad "precondition failed: un-fetched clone reported $(fget before) behind, so the fetch assertion below would be vacuous"

[ "$(fget findings)" = "1" ] \
  && ok "the detector fetches the remote itself and then sees the merged plugin commit" \
  || bad "detector produced $(fget findings) findings (want 1) -- without its own fetch it reports PASS forever"

# --- a FAILING fetch is reported, never swallowed (codex round 5, major) -----
# Same fixture shape as the fetch case, but the remote is made unreachable after
# cloning. Swallowing the failure leaves a frozen cached ref and PASS forever.
FETCHFAIL="$(ROOT="$ROOT" python3 - <<'PY3'
import importlib.util, json, os, shutil, subprocess, tempfile
from pathlib import Path
root = os.environ["ROOT"]; S = os.path.join(root, "q-system/.q-system/scripts")
G = ["git","-c","user.email=t@t.t","-c","user.name=t","-c","commit.gpgsign=false"]
def run(*a, cwd=None): return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True)
def load(n,p):
    sp=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m); return m
with tempfile.TemporaryDirectory() as td:
    rp=Path(td); bare=rp/"remote.git"
    run("git","init","-q","--bare",str(bare)); run("git","-C",str(bare),"symbolic-ref","HEAD","refs/heads/main")
    seed=rp/"seed"; (seed/"plugins").mkdir(parents=True)
    (seed/"plugins"/"seed.md").write_text("a\n")
    run(*G,"init","-q",cwd=seed); run(*G,"add","-A",cwd=seed)
    run(*G,"commit","-qm","base",cwd=seed); run(*G,"push","-q",str(bare),"HEAD:main",cwd=seed)
    mk=rp/"marketplaces"/"kipi"; mk.parent.mkdir(parents=True)
    run("git","clone","-q",str(bare),str(mk))
    man=mk/"plugins"/"prd-os"/".claude-plugin"; man.mkdir(parents=True)
    (man/"plugin.json").write_text(json.dumps({"name":"prd-os","version":"0.16.6"}))
    (rp/"installed_plugins.json").write_text(json.dumps(
        {"plugins":{"prd-os@kipi":[{"scope":"user","version":"0.16.6"}]}}))
    # Make the remote unreachable AFTER cloning: fetch must now fail.
    shutil.rmtree(bare)
    fh=load("fh",os.path.join(S,"fleet-health-daily.py"))
    src=open(os.path.join(S,"runtime-plugin-freshness.py")).read().replace(
        'DEFAULT_PLUGIN_ROOT = Path.home() / ".claude" / "plugins"',
        f'DEFAULT_PLUGIN_ROOT = Path({td!r})')
    shim=rp/"shim"; shim.mkdir(); (shim/"runtime-plugin-freshness.py").write_text(src)
    fh.HERE=shim
    f=fh.detect_stale_runtime_plugins(None)
    print(json.dumps({"count":len(f),"subject":f[0]["subject"] if f else ""}))
PY3
)"
echo "    fetch-failure result: $FETCHFAIL"
ffget() { printf '%s' "$FETCHFAIL" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }
[ "$(ffget count)" = "1" ] \
  && ok "a failing fetch produces a finding, not silence" \
  || bad "failing fetch produced $(ffget count) findings (want 1) -- a frozen cached ref reports PASS forever"
[ "$(ffget subject)" = "runtime-plugin-freshness-unreadable" ] \
  && ok "the fetch-failure finding uses the cannot-run subject" \
  || bad "fetch-failure subject was '$(ffget subject)'"

# --- a tracked edit OUTSIDE plugins/ is not runtime drift (round 5, major) ---
DIRTYSCOPE="$(ROOT="$ROOT" python3 - <<'PY4'
import importlib.util, json, os, subprocess, tempfile
from pathlib import Path
root=os.environ["ROOT"]; S=os.path.join(root,"q-system/.q-system/scripts")
G=["git","-c","user.email=t@t.t","-c","user.name=t","-c","commit.gpgsign=false"]
def run(*a,cwd=None): return subprocess.run(list(a),cwd=cwd,capture_output=True,text=True)
def load(n,p):
    sp=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m); return m
out={}
for label, edit in (("outside","README.md"), ("inside","plugins/prd-os/commands.md")):
    with tempfile.TemporaryDirectory() as td:
        rp=Path(td); mk=rp/"marketplaces"/"kipi"; mk.mkdir(parents=True)
        (mk/"README.md").write_text("r\n")
        (mk/"plugins"/"prd-os").mkdir(parents=True)
        (mk/"plugins"/"prd-os"/"commands.md").write_text("c\n")
        run(*G,"init","-q",cwd=mk); run(*G,"add","-A",cwd=mk); run(*G,"commit","-qm","base",cwd=mk)
        (mk/edit).write_text("EDITED\n")   # tracked edit, uncommitted
        rpf=load("rpf",os.path.join(S,"runtime-plugin-freshness.py"))
        out[label]=rpf.clone_dirty_tracked(mk)
print(json.dumps({"outside":len(out["outside"]),"inside":len(out["inside"])}))
PY4
)"
echo "    dirty-scope result: $DIRTYSCOPE"
dsget() { printf '%s' "$DIRTYSCOPE" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }
[ "$(dsget outside)" = "0" ] \
  && ok "a tracked edit OUTSIDE plugins/ is not reported as runtime drift" \
  || bad "an edit outside plugins/ reported $(dsget outside) dirty file(s) -- permanent false finding"
[ "$(dsget inside)" = "1" ] \
  && ok "a tracked edit INSIDE plugins/ is still reported" \
  || bad "an edit inside plugins/ reported $(dsget inside) -- the scoping went too far"

# --- commit-level drift the version string cannot show (round 6, major) ------
# The producer records gitCommitSha per installed entry; we were discarding it.
# Both directions in one fixture: plugin A's files change after its installed
# sha (must fire), plugin B's do not (must stay silent even though the clone
# advanced). The second half is what stops this becoming the docs-only false
# alarm round 3 rejected.
DRIFT="$(ROOT="$ROOT" python3 - <<'PY5'
import importlib.util, json, os, subprocess, tempfile
from pathlib import Path
root=os.environ["ROOT"]; S=os.path.join(root,"q-system/.q-system/scripts")
G=["git","-c","user.email=t@t.t","-c","user.name=t","-c","commit.gpgsign=false"]
def run(*a,cwd=None): return subprocess.run(list(a),cwd=cwd,capture_output=True,text=True)
def load(n,p):
    sp=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m);return m
with tempfile.TemporaryDirectory() as td:
    rp=Path(td); mk=rp/"marketplaces"/"kipi"; mk.mkdir(parents=True)
    for name in ("alpha","beta"):
        d=mk/"plugins"/name/".claude-plugin"; d.mkdir(parents=True)
        (d/"plugin.json").write_text(json.dumps({"name":name,"version":"1.0.0"}))
        (mk/"plugins"/name/"commands.md").write_text("v1\n")
    run(*G,"init","-q",cwd=mk); run(*G,"add","-A",cwd=mk); run(*G,"commit","-qm","base",cwd=mk)
    base=run("git","-C",str(mk),"rev-parse","HEAD").stdout.strip()
    # alpha's own files change AFTER the installed sha; beta's do not.
    (mk/"plugins"/"alpha"/"commands.md").write_text("v2\n")
    run(*G,"add","-A",cwd=mk); run(*G,"commit","-qm","alpha changes",cwd=mk)
    # Versions are IDENTICAL on both sides for both plugins.
    (rp/"installed_plugins.json").write_text(json.dumps({"plugins":{
        "alpha@kipi":[{"scope":"user","version":"1.0.0","gitCommitSha":base}],
        "beta@kipi":[{"scope":"user","version":"1.0.0","gitCommitSha":base}]}}))
    rpf=load("rpf",os.path.join(S,"runtime-plugin-freshness.py"))
    commits=rpf.installed_commits(rp/"installed_plugins.json","kipi")
    res={n: rpf.plugin_commits_since(mk,n,sha) for n,sha in commits.items()}
    print(json.dumps({"sha_read":len(commits),"alpha":res.get("alpha"),"beta":res.get("beta")}))
PY5
)"
echo "    drift result: $DRIFT"
drget() { printf '%s' "$DRIFT" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }
[ "$(drget sha_read)" = "2" ] \
  && ok "gitCommitSha is read from the producer shape (both entries)" \
  || bad "read $(drget sha_read) shas (want 2) -- the producer field is being discarded"
[ "$(drget alpha)" = "1" ] \
  && ok "a plugin whose own files changed since its installed sha reports drift" \
  || bad "alpha reported $(drget alpha) (want 1) -- commit-level drift is invisible behind an equal version string"
[ "$(drget beta)" = "0" ] \
  && ok "a plugin whose files did NOT change reports no drift, though the clone advanced" \
  || bad "beta reported $(drget beta) (want 0) -- this is the docs-only false alarm rebuilt"

# --- git failure text is NEVER echoed, only classified (round 8, blocker) ----
# r7 added a userinfo regex; r8 proved credentials in a QUERY STRING survive it
# (`?access_token=`, an OAuth `?code=`). The fix is not a better regex: nothing
# from git's output reaches the published string at all. This case feeds the
# known leak vectors AND a canary that appears in no constant we emit, so any
# future re-introduction of echoing fails here.
SAFE="$(ROOT="$ROOT" python3 - <<'PY6'
import importlib.util, json, os
S=os.path.join(os.environ["ROOT"],"q-system/.q-system/scripts")
sp=importlib.util.spec_from_file_location("fh",os.path.join(S,"fleet-health-daily.py"))
fh=importlib.util.module_from_spec(sp); sp.loader.exec_module(fh)
CANARY="ZZCANARY7788"
vectors=[
  f"fatal: unable to access 'https://host/x.git?access_token={CANARY}': Could not resolve host",
  f"fatal: unable to access 'https://user:{CANARY}@host/x.git': boom",
  f"remote: see https://host/cb?code={CANARY}&state=1",
  "remote: "+CANARY*40,
]
outs=[fh._safe_git_error(v,"",128) for v in vectors]
print(json.dumps({
  "any_canary": any(CANARY in o for o in outs),
  "max_len": max(len(o) for o in outs),
  "classified": fh._safe_git_error("fatal: Could not resolve host: x","",128),
  "unknown_falls_back": fh._safe_git_error("something totally novel","",9),
}))
PY6
)"
echo "    no-echo result: $SAFE"
sfget() { printf '%s' "$SAFE" | python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])" 2>/dev/null; }
[ "$(sfget any_canary)" = "False" ] \
  && ok "no byte of git output reaches the published string (4 leak vectors incl. query-string creds)" \
  || bad "a canary from git output survived into the published field"
[ "$(sfget max_len)" -le 80 ] 2>/dev/null \
  && ok "the published string is bounded by construction, not by truncation" \
  || bad "published string grew to $(sfget max_len) chars -- it is echoing input"
[ "$(sfget classified)" = "the host could not be resolved (git fetch exited 128)" ] \
  && ok "a recognised condition still yields a useful, self-owned classification" \
  || bad "classification wrong: $(sfget classified)"
[ "$(sfget unknown_falls_back)" = "git fetch exited 9" ] \
  && ok "an unrecognised failure reports the exit code, never the text" \
  || bad "unknown failure produced: $(sfget unknown_falls_back)"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
