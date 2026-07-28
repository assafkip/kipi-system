#!/usr/bin/env bash
# Pairs with linear-collapse.py. Asserts the DETERMINISTIC slice: which issues
# group into a family, that the survivor's proposed DoR carries the UNION of
# every member's target, and that the write order is comment-then-close with a
# record on disk before each close.
#
# No network, ever. Every case drives the pure functions, or drives apply_family
# through a fake writer that records an ordered call log. `--apply` against live
# Linear closes permanent objects; a suite that could reach it is a suite that
# can destroy the board on a typo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLAPSE="$HERE/../linear-collapse.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

check() {  # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  ok   $1"
  else FAIL=$((FAIL+1)); echo "  FAIL $1: expected [$2] got [$3]"; fi
}

# The fixture set, written once and imported by every case. Modelled on the two
# real families named in ASK-226: the ~12 CAP-0n scanner issues and the 23
# job-migration issues, plus the near-misses that must NOT collapse.
cat > "$TMP/_fx.py" <<'PYFX'
import importlib.util, json, sys

def load(path):
    spec = importlib.util.spec_from_file_location("collapse", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def issue(ident, title, desc, state_type="backlog", comments=()):
    return {"id": "uuid-" + ident, "identifier": ident, "title": title,
            "description": desc,
            "state": {"name": state_type.title(), "type": state_type},
            "comments": {"nodes": [{"id": "c%d" % n, "body": b}
                                   for n, b in enumerate(comments)]}}

CAP_RULES = ["anti-misclassification", "audhd-interaction", "coding-standards",
             "design-auto-invoke", "folder-structure"]

def cap_family():
    """The 5 known-identical CAP-0n issues (ASK-130..134)."""
    out = []
    for n, rule in enumerate(CAP_RULES, start=1):
        out.append(issue(
            "ASK-%d" % (129 + n),
            "CAP-%02d rule %s: %s guardrails" % (n, rule, rule),
            "<!-- kipi-key: cap-scan/%s -->\n\n**Files:**\n\n"
            "* `.claude/rules/%s.md`\n\nClaims ENFORCED with no enforcement." % (rule, rule)))
    return out

JOBS = [("ASK-151", "com.assaf/competitive-analysis:morning"),
        ("ASK-156", "com.cole/content-brain"),
        ("ASK-181", "com.kipi/launchd-health")]

def job_family():
    return [issue(ident, "migrate %s to Linear-tracked execution" % job,
                  "<!-- kipi-key: job-migration/%s -->\n\nThe plist is at "
                  "`~/Library/LaunchAgents/%s.plist`." % (job, job.replace("/", ".")))
            for ident, job in JOBS]

# Shares the word "migrate" AND a com.* token with job_family, different shape.
NEAR_MISS = issue("ASK-190", "migrate com.kipi/nightly-sweep off launchd entirely",
                  "<!-- kipi-key: job-migration/com.kipi/nightly-sweep -->\n\nunrelated shape")

class Fake:
    """Records the ORDER of every write, and refuses a close whose record is
    not already on disk -- that is check 6 (`sp-b5dcf944`: linear-triage.py
    --apply died mid-run after closing 32 issues with no audit file at all)."""
    def __init__(self, audit):
        self.log = []
        self.audit = audit
        self.batched = False

    def write_survivor_block(self, iss, block):
        self.log.append(("dor", iss["identifier"]))
        return "dor-written"

    def add_comment(self, iss, body):
        self.log.append(("comment", iss["identifier"]))
        return "comment-added"

    def close_issue(self, iss):
        recs = [json.loads(l) for l in open(self.audit) if l.strip()]
        if not any(r["issue"] == iss["identifier"] and r["step"] == "commented"
                   for r in recs):
            self.batched = True
        self.log.append(("close", iss["identifier"]))
        return "closed"
PYFX

pyrun() { python3 - "$COLLAPSE" "$TMP"; }

echo "== detect_families: one family per template, never per issue =="

# THE CORE CASE (check 2). 5 template-identical CAP issues are ONE change.
check "the 5 CAP issues group into exactly one family" '1' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.cap_family())))
PY
)"

check "the survivor is the lowest-numbered member" '"ASK-130"' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(json.dumps(c.detect_families(_fx.cap_family())[0]["survivor"]["identifier"]))
PY
)"

check "every other member is absorbed, none dropped" '["ASK-131", "ASK-132", "ASK-133", "ASK-134"]' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.cap_family())[0]
print(json.dumps([i["identifier"] for i in f["absorbed"]]))
PY
)"

check "the 3 job-migration issues group into one family" '1' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.job_family())))
PY
)"

echo "== over-collapse guards: destroying real work is the worse failure =="

# THE OTHER CORE CASE (check 4). Sharing "migrate" and a com.* token is not a
# family. Over-collapse closes real distinct work behind a fix that never covers it.
check "a near-miss sharing a word is not absorbed" '1' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
fams = c.detect_families(_fx.job_family() + [_fx.NEAR_MISS])
print(len(fams))
PY
)"

check "the near-miss stays out of the family roster" 'false' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.job_family() + [_fx.NEAR_MISS])[0]
print(json.dumps("ASK-190" in [i["identifier"] for i in f["members"]]))
PY
)"

# Same title shape, different scanner. Two producers filing the same sentence are
# two families; one fix does not cover both.
check "identical template from a different producer is a separate family" '2' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
alien = [_fx.issue("ASK-300", "migrate com.x/a to Linear-tracked execution",
                   "<!-- kipi-key: other-scan/a -->"),
         _fx.issue("ASK-301", "migrate com.x/b to Linear-tracked execution",
                   "<!-- kipi-key: other-scan/b -->")]
print(len(c.detect_families(_fx.job_family() + alien)))
PY
)"

# A title that is nothing but an identifier normalises to "<x>", which would
# match any other such title. That is not a family, it is a collision.
check "a template with no literal content is refused" 'false' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(json.dumps(c.is_collapsible_template(c.title_template("com.a/x"))))
PY
)"

check "a lone issue is not a family" '0' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.cap_family()[:1])))
PY
)"

echo "== survivor DoR: the union of targets, not a sample =="

# THE FAILURE MODE THIS ISSUE EXISTS TO PREVENT (check 3). A family fix that
# silently drops one member's path is how a job stays dark. Assert EVERY target
# of EVERY member, not that the block looks plausible.
check "every CAP member's rule file is named in the survivor DoR" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.cap_family())[0]
block = c.survivor_block(f, "2026-07-27T00:00:00Z")
want = {t for m in f["members"] for t in c.member_targets(m)}
print(json.dumps(len(want) == 5 and all(t in block for t in want)))
PY
)"

check "every job-migration label is named in the survivor DoR" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.job_family())[0]
block = c.survivor_block(f, "2026-07-27T00:00:00Z")
print(json.dumps(all(job in block for _, job in _fx.JOBS)))
PY
)"

check "every member identifier is named in the survivor DoR" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.cap_family())[0]
block = c.survivor_block(f, "2026-07-27T00:00:00Z")
print(json.dumps(all(m["identifier"] in block for m in f["members"])))
PY
)"

check "the absorb comment names the survivor" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.cap_family())[0]
body = c.absorb_comment(f, f["absorbed"][0], "2026-07-27T00:00:00Z")
print(json.dumps("ASK-130" in body and c.ABSORB_MARKER in body))
PY
)"

echo "== apply_family: comment before close, record before both =="

# check 5. A close with no pointer is an orphan: the record of what that issue
# named is gone from the board with nothing linking it to the survivor.
check "each member is commented before it is closed" 'true' \
  "$(pyrun <<'PY'
import sys, json, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a1.jsonl"); open(audit, "w").close()
w = _fx.Fake(audit)
f = c.detect_families(_fx.cap_family())[0]
c.apply_family(f, w, audit, ts="2026-07-27T00:00:00Z")
ok = True
for m in f["absorbed"]:
    i = w.log.index(("comment", m["identifier"]))
    j = w.log.index(("close", m["identifier"]))
    ok = ok and i < j
print(json.dumps(ok))
PY
)"

check "every absorbed member is both commented and closed" '8' \
  "$(pyrun <<'PY'
import sys, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a2.jsonl"); open(audit, "w").close()
w = _fx.Fake(audit)
c.apply_family(c.detect_families(_fx.cap_family())[0], w, audit, ts="t")
print(len([e for e in w.log if e[0] in ("comment", "close")]))
PY
)"

# check 6. sp-b5dcf944: the triage run died mid-pass after closing 32 issues and
# left no audit file at all, because the record was batched to the end.
check "the record is on disk before the close that follows it" 'false' \
  "$(pyrun <<'PY'
import sys, json, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a3.jsonl"); open(audit, "w").close()
w = _fx.Fake(audit)
c.apply_family(c.detect_families(_fx.cap_family())[0], w, audit, ts="t")
print(json.dumps(w.batched))
PY
)"

check "a crash after the first close still leaves the completed steps" '[["ASK-130", "survivor-dor"], ["ASK-131", "commented"]]' \
  "$(pyrun <<'PY'
import sys, json, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a4.jsonl"); open(audit, "w").close()
class Boom(_fx.Fake):
    def close_issue(self, iss):
        out = _fx.Fake.close_issue(self, iss)
        raise RuntimeError("simulated mid-run death")
w = Boom(audit)
try:
    c.apply_family(c.detect_families(_fx.cap_family())[0], w, audit, ts="t")
except RuntimeError:
    pass
# The close record is what the crash ate. Everything BEFORE it is on disk --
# batching to the end would leave an empty file and no idea what was touched.
recs = [json.loads(l) for l in open(audit) if l.strip()]
print(json.dumps([[r["issue"], r["step"]] for r in recs]))
PY
)"

echo "== idempotency: a second --apply must not double-write =="

# check 7. Linear objects are permanent; a second comment on 49 issues cannot be
# taken back.
check "an already-absorbed, already-closed member is not touched again" '0' \
  "$(pyrun <<'PY'
import sys, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a5.jsonl"); open(audit, "w").close()
issues = _fx.cap_family()
for m in issues[1:]:                      # what run 1 left behind
    m["comments"]["nodes"].append({"id": "cx", "body": c.ABSORB_MARKER + "\nsee ASK-130"})
    m["state"] = {"name": "Canceled", "type": "canceled"}
w = _fx.Fake(audit)
c.apply_family(c.detect_families(issues)[0], w, audit, ts="t")
print(len([e for e in w.log if e[0] in ("comment", "close")]))
PY
)"

# The half-done case: run 1 commented, then died before the close. Resuming must
# close it -- skipping the whole member would leave it open forever.
check "a commented-but-open member is still closed on resume" "$(printf '[["close", "ASK-131"]]')" \
  "$(pyrun <<'PY'
import sys, json, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "a6.jsonl"); open(audit, "w").close()
issues = _fx.cap_family()[:2]
issues[1]["comments"]["nodes"].append({"id": "cx", "body": c.ABSORB_MARKER + "\nsee ASK-130"})
w = _fx.Fake(audit)
c.apply_family(c.detect_families(issues)[0], w, audit, ts="t")
print(json.dumps([list(e) for e in w.log if e[0] in ("comment", "close")]))
PY
)"

check "re-splicing an unchanged survivor block is a no-op" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
f = c.detect_families(_fx.cap_family())[0]
block = c.survivor_block(f, "t")
once = c.splice_block("original text", block)
print(json.dumps(c.splice_block(once, block) == once and "original text" in once))
PY
)"

echo "== dry by default: --apply is the only thing that writes =="

check "no --apply writes nothing and says so" '0' \
  "$(pyrun <<'PY'
import sys, os, subprocess, json
sys.path.insert(0, sys.argv[2]); import _fx
env = dict(os.environ, KIPI_COLLAPSE_FIXTURE=os.path.join(sys.argv[2], "fx.json"))
json.dump(_fx.cap_family() + _fx.job_family(), open(env["KIPI_COLLAPSE_FIXTURE"], "w"))
r = subprocess.run([sys.executable, sys.argv[1]], env=env,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
sys.stderr.write(r.stderr)
assert "dry run" in r.stdout.lower(), r.stdout
assert "ASK-130" in r.stdout and "ASK-151" in r.stdout, r.stdout
print(r.returncode)
PY
)"

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
