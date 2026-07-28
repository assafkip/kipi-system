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

# CAPTURED FROM THE LIVE ASK BOARD 2026-07-27 (ASK-130..134), not invented.
#
# PR #35 review round 2, finding 1: the previous revision of this fixture built
# `"CAP-%02d rule %s: %s guardrails"` -- a tail that is the same literal word in
# every member. Byte-exact template equality matched, the suite went green, and
# the shipped detector then found ZERO families on the real 129-issue board,
# because the real producer puts the RULE'S OWN SUMMARY LINE after the colon and
# it is different prose in every member. A fixture that no producer emits is a
# suite that cannot fail on the bug it exists to catch, so these are verbatim.
#
# (cap number, rule slug, the prose tail the real producer wrote)
CAP_REAL = [
    ("01", "anti-misclassification",
     "Anti-misclassification guardrails for content generation"),
    ("02", "audhd-interaction",
     "AUDHD executive function and ADHD-aware interaction rules"),
    ("04", "coding-audhd",
     "AUDHD-adapted coding rules - structure, communication, emotional scaffolding"),
    ("05", "coding-standards",
     "Code style and naming conventions for Python, JS, Shell, and JSON"),
    ("07", "design-auto-invoke",
     "Auto-invoke design skills only for public-facing pages and assets"),
]
CAP_RULES = [slug for _, slug, _ in CAP_REAL]

# Also verbatim: the real scanner writes the entry point into a table cell with
# NO backticks, which is why 11 of the 14 real family members resolved to zero
# targets until `BARE_PATH_RE` was added.
CAP_DESC = """<!-- kipi-key: kipi-system/rule-%(slug)s -->

%(prose)s

| Field | Value |
| -- | -- |
| Repo | `kipi-system` |
| Layer | L0 Governance and rules |
| Status claimed | NEEDS_WORK |
| Entry point | .claude/rules/%(slug)s.md |
| Trigger | always-on instruction context |

## Evidence

.claude/rules/%(slug)s.md: 40 lines; claims ENFORCED but names NO executable,
so it is prompt-only."""


def cap_family():
    """The 5 real CAP-0n issues ASK-130..134, titles and bodies as filed."""
    return [issue("ASK-%d" % (130 + n),
                  "CAP-%s rule %s: %s" % (cap, slug, prose),
                  CAP_DESC % {"slug": slug, "prose": prose})
            for n, (cap, slug, prose) in enumerate(CAP_REAL)]


# CAPTURED FROM THE LIVE BOARD 2026-07-27 (ASK-6, 7, 44, 50). The `cole-gtm`
# capability registry: 45 issues that all start `CAP-NN `, share the kipi-key
# kind `cap`, and are 45 DISTINCT pieces of work. They are the over-collapse
# canary for the head-truncation fix -- if dropping the prose tail ever merges
# these, the fix has destroyed real work to find a family.
COLE_CAPS = [("06", "CAP-01 Persona and voice routing", "cap-01-persona-and-voice-routing"),
             ("07", "CAP-02 Rule registry", "cap-02-rule-registry"),
             ("44", "CAP-39 Design room and design gates", "cap-39-design-room-and-design-gates"),
             ("50", "CAP-45 Plugin fleet", "cap-45-plugin-fleet")]


def cole_cap_family():
    return [issue("ASK-%s" % n.lstrip("0"), title,
                  "<!-- kipi-key: cole-gtm/%s -->\n\n**L0 Governance.**" % key)
            for n, title, key in COLE_CAPS]

JOBS = [("ASK-151", "com.assaf/competitive-analysis:morning"),
        ("ASK-156", "com.cole/content-brain"),
        ("ASK-181", "com.kipi/launchd-health")]

def job_family():
    return [issue(ident, "migrate %s to Linear-tracked execution" % job,
                  "<!-- kipi-key: job-migration/%s -->\n\nThe plist is at "
                  "`~/Library/LaunchAgents/%s.plist`." % (job, job.replace("/", ".")))
            for ident, job in JOBS]

def job_family_big(n=22):
    """`n` issues in the REAL producer's real format (linear-job-migration.py:166).

    Big enough to cross MAX_TARGETS_PER_ISSUE, because the finding-1 failure only
    bites once the ingested roster overflows the cap and evicts the survivor's own
    target. Each member names TWO targets: its launchd label and its script path.
    """
    out = []
    for i in range(1, n + 1):
        label = "com.cole.job%02d" % i
        out.append(issue(
            "ASK-%d" % (299 + i),
            "Migrate %s to Linear-tracked execution" % label,
            "<!-- kipi-key: job-migration/%s -->\n\n"
            "Migrate `%s` onto Linear-tracked execution.\n\n"
            "| Field | Value |\n| -- | -- |\n| State | loaded |\n"
            "| Runs | `q-system/.q-system/scripts/job%02d.py` |\n" % (
                label.replace(".", "-"), label, i)))
    return out

# Shares the word "migrate" AND a com.* token with job_family, different shape.
NEAR_MISS = issue("ASK-190", "migrate com.kipi/nightly-sweep off launchd entirely",
                  "<!-- kipi-key: job-migration/com.kipi/nightly-sweep -->\n\nunrelated shape")

class Fake:
    """Records the ORDER of every write, and refuses a close whose record is
    not already on disk -- that is check 6 (`sp-b5dcf944`: linear-triage.py
    --apply died mid-run after closing 32 issues with no audit file at all).

    Pass the loaded module as `c` for a writer with the same side effects the
    real one has on the board: the description gets the spliced block, a comment
    lands, a close flips the state. Without `c` it only records calls. Anything
    that spans two passes needs the side effects -- pass 2 reads what pass 1
    wrote, and both PR #35 review majors live in exactly that read.
    """
    def __init__(self, audit, c=None):
        self.log = []
        self.audit = audit
        self.batched = False
        self.c = c

    def write_survivor_block(self, iss, block):
        self.log.append(("dor", iss["identifier"]))
        if self.c:
            new = self.c.splice_block(iss.get("description") or "", block)
            if new == (iss.get("description") or ""):
                return "dor-unchanged"
            iss["description"] = new
        return "dor-written"

    def add_comment(self, iss, body):
        self.log.append(("comment", iss["identifier"]))
        if self.c:
            iss["comments"]["nodes"].append({"id": "c-new", "body": body})
        return "comment-added"

    def close_issue(self, iss):
        recs = [json.loads(l) for l in open(self.audit) if l.strip()]
        if not any(r["issue"] == iss["identifier"] and r["step"] == "commented"
                   for r in recs):
            self.batched = True
        self.log.append(("close", iss["identifier"]))
        if self.c:
            iss["state"] = {"name": "Canceled", "type": "canceled"}
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

# Same title shape, different kipi-key namespace. `cole-gtm/` and `job-migration/`
# are both real ledger namespaces; one fix does not cover both.
check "identical template from a different namespace is a separate family" '2' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
alien = [_fx.issue("ASK-400", "migrate com.x/a to Linear-tracked execution",
                   "<!-- kipi-key: cole-gtm/cap-45-plugin-fleet -->"),
         _fx.issue("ASK-401", "migrate com.x/b to Linear-tracked execution",
                   "<!-- kipi-key: cole-gtm/cap-44-code-health-scanner-suite -->")]
print(len(c.detect_families(_fx.job_family() + alien)))
PY
)"

# PR #35 review, finding 4, pinned rather than argued. `producer()` returns the
# kipi-key NAMESPACE, and on the real ledger 122 of 188 issues resolve to a repo
# (`kipi-system/`, `cole-gtm/`), not a scanner. So two different scanners writing
# into one namespace share a bucket and only the title template separates them.
# This case documents that residual (sp-ab2d1067): if someone strengthens the key,
# this check fails and they update it on purpose instead of by accident.
check "residual: two scanners in one namespace no longer merge on a thin head" '0' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
# left: filed by the CAP rule scanner. right: filed by the unwired-engine audit.
# Same namespace, same head template `<x> rule <x>`. This case used to expect ONE
# family and was pinned as sp-ab2d1067's residual, with a note that whoever
# strengthened the key should update it deliberately. The round-2 corroboration
# rule strengthened it: a thin head is admissible only when the kipi-key's own
# kind repeats a literal word in it, so `rule-alpha-one` corroborates and
# `unwired-engine-audit` does not. They no longer share a bucket.
#
# The residual is NOT closed. Two scanners whose kinds DO match, or any family
# whose head clears the floor on its own, still merge on namespace + template
# alone. sp-ab2d1067 stays open for that.
same_ns = [_fx.issue("ASK-500", "CAP-90 rule alpha-one: alpha-one guardrails",
                     "<!-- kipi-key: kipi-system/rule-alpha-one -->"),
           _fx.issue("ASK-501", "CAP-91 rule beta-two: beta-two guardrails",
                     "<!-- kipi-key: kipi-system/unwired-engine-audit -->")]
print(len(c.detect_families(same_ns)))
PY
)"

echo "== round-2 finding 1: the matcher against the REAL producer's titles =="

# THE REPRODUCER. Shipped code, live board, dry: "129 open issue(s) scanned; no
# duplicate-template family found." Zero, including the family this script names
# as its win. These titles are those issues, verbatim.
check "the real CAP-0n titles group into one family" '1' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.cap_family())))
PY
)"

check "the free-prose tail is not part of the family key" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
tmpls = {c.title_template(i["title"]) for i in _fx.cap_family()}
# One template for all five, and it is the HEAD: no word of any prose summary
# appears in it. (Apostrophes are banned in these heredocs -- bash matches quotes
# inside $(...) even when the heredoc delimiter is quoted, and an odd one
# swallows the rest of the file.)
print(json.dumps(tmpls == {"<x> rule <x>"}))
PY
)"

# The other half of the same fix, and the reason it is not optional: making the
# family collapse is only safe if the roster still names what each member owns.
check "every real CAP member's rule file lands in the roster, none nameless" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
fam = c.detect_families(_fx.cap_family())[0]
rows = c.family_rows(fam)
want = {".claude/rules/%s.md" % r for r in _fx.CAP_RULES}
got = {t for r in rows for t in r["targets"]}
print(json.dumps(len(rows) == 5 and want <= got
                 and all(r["targets"] for r in rows)))
PY
)"

check "the roster text names every rule file, not a sample" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
block = c.survivor_block(c.detect_families(_fx.cap_family())[0], ts="t")
print(json.dumps(all(".claude/rules/%s.md" % r in block for r in _fx.CAP_RULES)
                 and c.NO_TARGET not in block))
PY
)"

echo "== round-2 finding 1: the over-collapse canary the fix must not trip =="

# 45 real cole-gtm capability issues all begin `CAP-NN `. Dropping the prose tail
# must not turn 45 distinct capabilities into one family.
check "the cole-gtm CAP registry does not collapse" '0' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.cole_cap_family())))
PY
)"

check "the CAP registry stays apart even mixed with the rule family" '1' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
fams = c.detect_families(_fx.cap_family() + _fx.cole_cap_family())
ids = [i["identifier"] for f in fams for i in f["members"]]
print(json.dumps(len(fams)) if not [x for x in ids if x in
      [i["identifier"] for i in _fx.cole_cap_family()]] else "LEAKED")
PY
)"

# Corroboration is what lets a thin head through, and only a machine writes a
# kipi-key. Strip it and the same title is refused, so nothing a person filed can
# collapse on a one-literal-word template.
check "a thin head with no kipi-key is refused" '0' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
human = [_fx.issue(i["identifier"], i["title"], "filed by hand, no kipi-key")
         for i in _fx.cap_family()]
print(len(c.detect_families(human)))
PY
)"

check "a thin head whose kipi-key kind does not match is refused" 'false' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(json.dumps(c.is_collapsible_template("<x> rule <x>", "unwired")))
PY
)"

echo "== round-2 finding 2: --min-family measured against the roster =="

# The reviewer's scenario: --min-family 5, pass 1 dies right after ASK-133's
# comment, pass 2 sees only the 3 still-open members. Measuring the threshold
# against the open members drops the family to 0 and ASK-133 sits open forever
# behind a permanent "collapsed into ASK-130" comment.
check "a resumed pass below --min-family still sees the family" '1' \
  "$(pyrun <<'PY'
import sys, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "mf1.jsonl")
open(audit, "w").close()
issues = _fx.cap_family()
w = _fx.Fake(audit, c)
fam = c.detect_families(issues, min_family=5)[0]
# pass 1: roster written, two members closed, then the process dies.
class Died(Exception): pass
class Dying(_fx.Fake):
    def close_issue(self, iss):
        if len([x for x in self.log if x[0] == "close"]) >= 2:
            raise Died("simulated mid-run death")
        return _fx.Fake.close_issue(self, iss)
d = Dying(audit, c)
try:
    c.apply_family(fam, d, audit, ts="t")
except Died:
    pass
# pass 2 sees only what fetch_open() would return.
still_open = [i for i in issues if not c.is_closed(i)]
print(len(c.detect_families(still_open, min_family=5)))
PY
)"

check "the resumed pass closes the member stranded behind its own comment" 'true' \
  "$(pyrun <<'PY'
import sys, os, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "mf2.jsonl")
open(audit, "w").close()
issues = _fx.cap_family()
class Died(Exception): pass
class Dying(_fx.Fake):
    def close_issue(self, iss):
        if len([x for x in self.log if x[0] == "close"]) >= 2:
            raise Died("simulated mid-run death")
        return _fx.Fake.close_issue(self, iss)
d = Dying(audit, c)
try:
    c.apply_family(c.detect_families(issues, min_family=5)[0], d, audit, ts="t")
except Died:
    pass
stranded = [i["identifier"] for i in issues
            if c.already_absorbed(i) and not c.is_closed(i)]
still_open = [i for i in issues if not c.is_closed(i)]
fams = c.detect_families(still_open, min_family=5)
c.apply_family(fams[0], _fx.Fake(audit, c), audit, ts="t")
left = [i["identifier"] for i in issues
        if c.already_absorbed(i) and not c.is_closed(i)]
# something WAS stranded by the crash, and the resumed pass closed all of it
print(json.dumps(bool(stranded) and left == []))
PY
)"

check "a family too small even counting its roster is still skipped" '0' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
print(len(c.detect_families(_fx.cap_family()[:2], min_family=5)))
PY
)"

# A fully-absorbed family must not reappear as a no-op "family" in every dry run.
check "a family with nothing left to absorb is not reported" '0' \
  "$(pyrun <<'PY'
import sys, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "mf3.jsonl")
open(audit, "w").close()
issues = _fx.cap_family()
c.apply_family(c.detect_families(issues)[0], _fx.Fake(audit, c), audit, ts="t")
print(len(c.detect_families([i for i in issues if not c.is_closed(i)])))
PY
)"

echo "== round-2 finding 2: an in-flight write is not silent =="

# The reviewer's note: append_record runs AFTER the mutation, so a process killed
# during a comment left a permanent comment on Linear and nothing on disk.
check "a write killed in flight still left an intent row on disk" 'true' \
  "$(pyrun <<'PY'
import sys, os, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "inflight.jsonl")
open(audit, "w").close()
class Killed(Exception): pass
class Kill(_fx.Fake):
    def add_comment(self, iss, body):
        _fx.Fake.add_comment(self, iss, body)      # the permanent write lands
        raise Killed("killed after the comment reached Linear")
try:
    c.apply_family(c.detect_families(_fx.cap_family())[0],
                   Kill(audit, c), audit, ts="t")
except Killed:
    pass
recs = [json.loads(l) for l in open(audit) if l.strip()]
inflight = [r for r in recs
            if r["issue"] == "ASK-131" and r["step"] == "commented"]
# exactly the intent row: the outcome row never got written
print(json.dumps([r["outcome"] for r in inflight] == ["attempting"]))
PY
)"

check "intent rows never make a completed step look incomplete" '[]' \
  "$(pyrun <<'PY'
import sys, os, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "intent-ok.jsonl")
open(audit, "w").close()
recs = c.apply_family(c.detect_families(_fx.cap_family())[0],
                      _fx.Fake(audit, c), audit, ts="t")
print(json.dumps(c.incomplete_steps(recs)))
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
# COMPLETED steps only: the write-ahead intent rows added for round-2 finding 2
# are a separate signal with their own cases, and this assertion is the original
# durability contract, unchanged in value.
recs = [json.loads(l) for l in open(audit) if l.strip()]
print(json.dumps([[r["issue"], r["step"]] for r in recs
                  if r["outcome"] != "attempting"]))
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

echo "== second pass: the survivor must not ingest the block it wrote =="

# PR #35 review, finding 1. member_targets() read title + WHOLE description, and
# after pass 1 the survivor's description CONTAINS the roster naming every other
# member's target. Pass 2 read them back as the survivor's own and the 20-target
# cap evicted the survivor's REAL target from its own row -- the exact failure the
# module docstring says the roster exists to prevent.
check "the survivor's own targets survive a read of its own roster block" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
issues = _fx.job_family_big(22)
fam = c.detect_families(issues)[0]
sur = fam["survivor"]
own = c.member_targets(sur)
sur["description"] = c.splice_block(sur["description"], c.survivor_block(fam, "t"))
print(json.dumps(c.member_targets(sur) == own))
PY
)"

check "no other member's target lands in the survivor's own row on pass 2" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
issues = _fx.job_family_big(22)
sur = issues[0]
sur["description"] = c.splice_block(
    sur["description"], c.survivor_block(c.detect_families(issues)[0], "t"))
block2 = c.survivor_block(c.detect_families(issues)[0], "t")
row = [l for l in block2.splitlines() if l.startswith("| ASK-300 ")][0]
print(json.dumps("job01.py" in row and "com.cole.job02" not in row))
PY
)"

echo "== resume: rows the previous pass closed stay on the roster =="

# PR #35 review, finding 2. Production only ever feeds detect_families() from
# fetch_open(), so pass 2 cannot see what pass 1 closed. Rebuilding the block from
# the open members alone DELETED the closed members' rows -- while their pointer
# comments still said "enumerated in ASK-130, so the family fix has to cover it".
cat > "$TMP/_resume.py" <<'PYRES'
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fx

def resumed_survivor_description(c, tmp, tag):
    """Run 1 dies after two closes; run 2 sees only what fetch_open() would."""
    audit = os.path.join(tmp, "resume-%s.jsonl" % tag)
    open(audit, "w").close()
    issues = _fx.cap_family()

    class Die(_fx.Fake):
        def close_issue(self, iss):
            out = _fx.Fake.close_issue(self, iss)
            if len([e for e in self.log if e[0] == "close"]) >= 2:
                raise RuntimeError("simulated mid-run death (sp-b5dcf944)")
            return out

    try:
        c.apply_family(c.detect_families(issues)[0], Die(audit, c), audit, ts="t1")
    except RuntimeError:
        pass
    still_open = [i for i in issues if not c.is_closed(i)]   # == fetch_open()
    c.apply_family(c.detect_families(still_open)[0], _fx.Fake(audit, c), audit, ts="t2")
    return issues[0]["description"]
PYRES

check "a resumed pass keeps the rows of the members the first pass closed" '["ASK-130", "ASK-131", "ASK-132", "ASK-133", "ASK-134"]' \
  "$(pyrun <<'PY'
import sys, json, re; sys.path.insert(0, sys.argv[2]); import _fx, _resume
c = _fx.load(sys.argv[1])
desc = _resume.resumed_survivor_description(c, sys.argv[2], "ids")
print(json.dumps(sorted(set(re.findall(r"ASK-1\d\d", desc)))))
PY
)"

check "the roster header counts the whole family, not just what is still open" '## Collapsed family — 5 issues, one change' \
  "$(pyrun <<'PY'
import sys; sys.path.insert(0, sys.argv[2]); import _fx, _resume
c = _fx.load(sys.argv[1])
desc = _resume.resumed_survivor_description(c, sys.argv[2], "hdr")
print([l for l in desc.splitlines() if l.startswith("## Collapsed family")][0])
PY
)"

check "every member's target is still enumerated after the resumed pass" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx, _resume
c = _fx.load(sys.argv[1])
desc = _resume.resumed_survivor_description(c, sys.argv[2], "targets")
print(json.dumps(all(".claude/rules/%s.md" % r in desc for r in _fx.CAP_RULES)))
PY
)"

check "a prior row for an issue no longer in the family is preserved" '["ASK-130", "ASK-131", "ASK-199"]' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
fam = c.detect_families(_fx.cap_family()[:2])[0]
prior = [{"identifier": "ASK-199", "title": "closed by an earlier pass",
          "targets": [".claude/rules/gone.md"]}]
print(json.dumps([r["identifier"] for r in c.family_rows(fam, prior)]))
PY
)"

# The merge only works if the block this script writes can be read back exactly.
# A title carrying a pipe is the one character that can break the table parse.
check "the roster round-trips: parse_block_rows reads back what survivor_block wrote" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
fam = c.detect_families(_fx.cap_family())[0]
fam["members"][1]["title"] = "CAP-02 rule a | b: pipes in titles guardrails"
back = c.parse_block_rows(c.survivor_block(fam, "t"))
want = [{"identifier": m["identifier"], "title": m["title"],
         "targets": c.member_targets(m)} for m in fam["members"]]
print(json.dumps(back == want))
PY
)"

check "a pass that adds no row does not rewrite the survivor description" 'dor-unchanged' \
  "$(pyrun <<'PY'
import sys, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "noop.jsonl"); open(audit, "w").close()
issues = _fx.cap_family()
c.apply_family(c.detect_families(issues)[0], _fx.Fake(audit, c), audit, ts="t1")
recs = c.apply_family(c.detect_families(issues)[0], _fx.Fake(audit, c), audit, ts="t2")
print([r["outcome"] for r in recs if r["step"] == "survivor-dor"][0])
PY
)"

echo "== a step that did not happen is never counted as applied =="

# PR #35 review, finding 3. close_issue() returned the STRING "NOT-CLOSED (...)",
# apply_family recorded it as an outcome, and main() did done += 1 regardless --
# so a run that commented on 49 permanent issues and closed none printed
# "1/1 family/families applied." and exited 0.
check "close_issue with no canceled-type state raises instead of returning a string" 'true' \
  "$(pyrun <<'PY'
import sys, json; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
try:
    c.LinearWriter(None, None).close_issue({"id": "x", "identifier": "ASK-1"})
    print(json.dumps(False))
except RuntimeError:
    print(json.dumps(True))
PY
)"

check "a step whose outcome is not a real write makes the family incomplete" '[["ASK-131", "closed", "NOT-CLOSED (stubbed)"]]' \
  "$(pyrun <<'PY'
import sys, json, os; sys.path.insert(0, sys.argv[2]); import _fx
c = _fx.load(sys.argv[1])
audit = os.path.join(sys.argv[2], "incomplete.jsonl"); open(audit, "w").close()
class Stub(_fx.Fake):
    def close_issue(self, iss):
        _fx.Fake.close_issue(self, iss)
        return "NOT-CLOSED (stubbed)"
recs = c.apply_family(c.detect_families(_fx.cap_family()[:2])[0],
                      Stub(audit), audit, ts="t")
print(json.dumps(c.incomplete_steps(recs)))
PY
)"

check "the offline fixture seam refuses --apply instead of crashing on a None client" '1' \
  "$(pyrun <<'PY'
import sys, os, subprocess, json
sys.path.insert(0, sys.argv[2]); import _fx
env = dict(os.environ, KIPI_COLLAPSE_FIXTURE=os.path.join(sys.argv[2], "fx2.json"))
json.dump(_fx.cap_family(), open(env["KIPI_COLLAPSE_FIXTURE"], "w"))
r = subprocess.run([sys.executable, sys.argv[1], "--apply"], env=env,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
assert "Traceback" not in r.stderr, r.stderr
assert "KIPI_COLLAPSE_FIXTURE" in r.stderr, r.stderr
print(r.returncode)
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
