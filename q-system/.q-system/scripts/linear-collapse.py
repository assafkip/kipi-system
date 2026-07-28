#!/usr/bin/env python3
"""Collapse duplicate-template issues into one issue per family.

WHY THIS EXISTS

Measured on the ASK board 2026-07-28 (`q-system/output/triage-applied-2026-07-28.log`,
106 issues classified): 56 issues triaged `batch`, and 49 of those 56 are the same
machine-filed template repeated -- 23 near-identical job-migration issues, the
CAP-0n rule family, and a handful of other scanner output. The triage reasons say
it outright ("First of five identical CAP-0n rule issues", "Runs the identical
script as ASK-156").

So a ~200-issue board is not 200 pieces of work. It is roughly 20 real changes
wearing 200 hats. The lever is collapsing duplicates, not throughput.

WHY COLLAPSE AND NOT "JUST CLOSE THEM"

Closing 49 issues deletes the record of what each one actually named. Some carry a
distinct path or job label that the family fix has to cover, and a family fix that
silently drops one member's target is exactly how a job stays dark. So: ONE
surviving issue per family whose description enumerates EVERY member's specific
target, and every absorbed issue closed with a comment pointing at the survivor.
`survivor_block()` builds the union; `test-linear-collapse.sh` asserts the union
rather than a sample, because a sample assertion passes on the bug.

WHY THE DETECTOR IS DETERMINISTIC AND STRICT

No model call. Two issues collapse only when their titles normalise to the
BYTE-IDENTICAL template and they were filed by the same producer. That under-
collapses in the tail (a hand-edited title drops out of its family) and that is
the safe direction: under-collapse leaves an issue on the board for a human to
look at, over-collapse closes real distinct work behind a fix that never covers
it. `is_collapsible_template()` refuses a template with no literal content, so
two titles that are nothing but identifiers cannot collide into a family.

WHY DRY BY DEFAULT

Same reason as `linear-triage.py`: Linear objects are permanent, `mcp__linear__
*delete*` is blocked by `~/.claude/hooks/destructive-op-deny.sh`, and an agent
cannot set ALLOW_DESTRUCTIVE=1 for itself. Closing is reversible; 49 wrong
comments are not. The first run prints the plan and writes nothing.

WHY THE RECORD IS APPENDED PER ISSUE, NOT AT THE END

sp-b5dcf944: `linear-triage.py --apply` died mid-run on 2026-07-28 after closing
32 issues and left no audit file at all, because the verdict file was written
after the loop. Here every write appends its record and fsyncs before the next
write starts, so a run that dies at issue 20 still says what happened to issues
1..20. `test-linear-collapse.sh` drives a fake writer that FAILS the suite if a
close happens before its own record is on disk.

EXIT CODES -- this script never lies about failure
  0  ran; every family in the plan was fully applied (or it was a dry run)
  1  usage error
  9  the run could not finish what it started (a write raised). Partial results
     are printed and the audit file holds every write that did land, but the
     exit code says the pass is incomplete.

Usage:
  linear-collapse.py                          # dry, prints the plan
  linear-collapse.py --apply                  # writes: survivor DoR, comments, closes
  linear-collapse.py --min-family 5           # only collapse families this big
  linear-collapse.py --out path.jsonl         # override the audit file location
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent

# Delimits the block this script owns inside the survivor's description. Every
# rewrite replaces what is BETWEEN these markers and never touches a byte outside
# them: the survivor is a real issue somebody wrote, not a scratch object.
BLOCK_OPEN = "<!-- kipi-collapse-family -->"
BLOCK_CLOSE = "<!-- /kipi-collapse-family -->"

# Written into every comment posted on an absorbed issue. A second pass finds it
# and skips the comment, so re-running cannot stack 49 duplicate comments on
# permanent objects.
ABSORB_MARKER = "<!-- kipi-collapse-absorbed -->"

DEFAULT_AUDIT = "q-system/output/linear-collapse-{date}.jsonl"

# Linear WorkflowState.type values that mean the issue is already off the board.
CLOSED_STATE_TYPES = ("completed", "canceled")

ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
  nodes{id identifier title description createdAt
        state{name type} project{name}
        comments{nodes{id body}}}
  pageInfo{hasNextPage endCursor}}}"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- template normalisation ------------------------------------------------
# The whole detector rests on this function, so it is deliberately boring: a
# token is VARIABLE if it carries any mark of an identifier, and everything else
# is literal sentence. `com.cole/content-brain`, `CAP-01`, `linear-tracked` and
# `anti-misclassification:` are all variable; `migrate`, `rule`, `execution` and
# `guardrails` are the sentence that makes two issues the same issue.

# Internal hyphen counts, because the CAP family varies ONLY in a hyphenated rule
# name ("CAP-01 rule anti-misclassification: ..." vs "... audhd-interaction: ...").
# Without it those five never group and the largest easy win on the board is
# invisible. It also swallows constant hyphenated words like `linear-tracked`,
# which is harmless: they are swallowed identically in every member.
VARIABLE_MARK_RE = re.compile(r"[./_:@]|\d|(?<=[a-z0-9])-(?=[a-z0-9])")

# Stripped from the ENDS of a token only. Internal punctuation is the signal.
TOKEN_EDGE = " \t()[]{}\"'`,;.!?*"

# Function words carry no discriminating power, so they do not count toward the
# literal-content floor below. Without this, "migrate <x> to <x>" would read as
# having two literal words when it has one real one.
STOPWORDS = {"a", "an", "and", "the", "to", "for", "of", "in", "on", "off", "at",
             "with", "from", "by", "or", "its", "it", "this", "that", "is",
             "are", "be", "as", "into", "so", "no", "not", "all", "any"}

# A template needs enough shape to mean something. "<x>" matches every
# identifier-only title on the board; collapsing on it would be a collision, not
# a family. Two literal words in a four-token sentence is the floor both real
# families clear ("migrate <x> to <x> execution", "<x> rule <x> <x> guardrails").
MIN_TEMPLATE_TOKENS = 4
MIN_LITERAL_WORDS = 2

KIPI_KEY_RE = re.compile(r"kipi-key:\s*([^\s/]+)/")

# launchd labels (`com.cole/content-brain`, `com.assaf/competitive-analysis:morning`)
# and backticked repo paths. These are the "specific target" the survivor's DoR
# must enumerate -- the thing that goes dark if the family fix skips a member.
JOB_LABEL_RE = re.compile(r"\bcom\.[A-Za-z0-9][A-Za-z0-9._:/-]*")
PATH_RE = re.compile(r"`(~?[A-Za-z0-9_./-]+\.(?:py|sh|md|json|yml|yaml|plist))`")
MAX_TARGETS_PER_ISSUE = 20


def title_template(title: str) -> str:
    """The title with every identifier replaced by `<x>`.

    Two issues are the same issue iff this string matches exactly. Exact match,
    not similarity: a similarity threshold is a knob nobody can calibrate before
    it has already closed the wrong issue.
    """
    out = []
    for raw in re.split(r"\s+", (title or "").strip().lower()):
        tok = raw.strip(TOKEN_EDGE)
        if not tok:
            continue
        out.append("<x>" if VARIABLE_MARK_RE.search(tok) else tok)
    return " ".join(out)


def literal_words(template: str) -> list:
    return [t for t in template.split() if t != "<x>" and t not in STOPWORDS]


def is_collapsible_template(template: str) -> bool:
    """False for a template too generic to identify a family."""
    tokens = template.split()
    return (len(tokens) >= MIN_TEMPLATE_TOKENS
            and len(literal_words(template)) >= MIN_LITERAL_WORDS)


def producer(issue: dict) -> str:
    """Which scanner filed this, from its kipi-key marker, or "" if a human did.

    Part of the family key: two scanners emitting the same sentence are two
    families, and one fix does not cover both.
    """
    m = KIPI_KEY_RE.search(issue.get("description") or "")
    return m.group(1) if m else ""


def issue_number(identifier: str) -> int:
    m = re.search(r"-(\d+)$", identifier or "")
    return int(m.group(1)) if m else 10 ** 9


def member_targets(issue: dict) -> list:
    """Every distinct thing this issue names: job labels, then repo paths.

    Read from the title AND the description, because the job-migration family
    carries its only distinguishing token in the title.
    """
    text = (issue.get("title") or "") + "\n" + (issue.get("description") or "")
    out: list = []
    for hit in JOB_LABEL_RE.findall(text) + PATH_RE.findall(text):
        if hit not in out:
            out.append(hit)
        if len(out) >= MAX_TARGETS_PER_ISSUE:
            break
    return out


def detect_families(issues: list, min_family: int = 2) -> list:
    """Group issues into families. Returns [] when nothing is duplicated.

    The survivor is the lowest-numbered member, always. Deterministic on purpose:
    a survivor that moves between passes makes the pointer comments on already-
    absorbed issues point at the wrong place.
    """
    groups: dict = {}
    for issue in issues:
        template = title_template(issue.get("title"))
        if not is_collapsible_template(template):
            continue
        groups.setdefault((producer(issue), template), []).append(issue)

    families = []
    for (prod, template), members in sorted(groups.items()):
        if len(members) < max(2, min_family):
            continue
        members = sorted(members, key=lambda i: issue_number(i["identifier"]))
        families.append({
            "producer": prod,
            "template": template,
            "members": members,
            "survivor": members[0],
            "absorbed": members[1:],
        })
    # Biggest family first: it is the biggest reduction in board size, and if a
    # run is interrupted the work that landed is the work that mattered most.
    families.sort(key=lambda f: (-len(f["members"]), f["survivor"]["identifier"]))
    return families


# --- the text this script writes -------------------------------------------

def survivor_block(family: dict, ts: str | None = None) -> str:
    """The roster that makes the collapse safe: every member, every target.

    This is the artifact the DoR of ASK-226 is about. If a member's target is
    missing here, the family fix will not cover it, the issue that named it is
    closed, and nothing on the board remembers it existed.
    """
    ts = ts or _now()
    survivor = family["survivor"]["identifier"]
    rows = []
    for m in family["members"]:
        targets = member_targets(m)
        cell = ", ".join("`%s`" % t for t in targets) if targets else "_(no explicit target)_"
        label = m["identifier"] + (" (this issue)" if m["identifier"] == survivor else "")
        rows.append("| %s | %s | %s |" % (label, (m.get("title") or "").replace("|", "\\|"), cell))

    return "\n".join([
        BLOCK_OPEN,
        "## Collapsed family — %d issues, one change" % len(family["members"]),
        "",
        "These %d issues are the same machine-filed template with a different "
        "target in each. They are ONE change, not %d. Every member's specific "
        "target is enumerated below; a fix that covers the shape but skips one "
        "of these rows leaves that target dark, which is the whole reason these "
        "were collapsed instead of closed."
        % (len(family["members"]), len(family["members"])),
        "",
        "| issue | title | target(s) |",
        "|---|---|---|",
        *rows,
        "",
        "Filed by: `%s`. Title template: `%s`." % (family["producer"] or "(human)", family["template"]),
        "",
        "<sub>`linear-collapse.py` %s. The absorbed issues are closed with a "
        "comment pointing here. Wrong call? Reopen any of them — nothing was "
        "deleted.</sub>" % ts,
        BLOCK_CLOSE,
    ])


def absorb_comment(family: dict, member: dict, ts: str | None = None) -> str:
    ts = ts or _now()
    targets = member_targets(member)
    mine = ", ".join("`%s`" % t for t in targets) if targets else "this issue's target"
    return "\n".join([
        ABSORB_MARKER,
        "**Collapsed into %s** — one of %d template-identical issues filed by "
        "`%s`." % (family["survivor"]["identifier"], len(family["members"]),
                   family["producer"] or "a human"),
        "",
        "%s is enumerated in %s, so the family fix has to cover it. Closing here "
        "is bookkeeping, not a decision to skip the work."
        % (mine, family["survivor"]["identifier"]),
        "",
        "<sub>`linear-collapse.py` %s. If the family fix does not cover this "
        "target, reopen this issue — that is what the pointer is for.</sub>" % ts,
    ])


def splice_block(description: str, block: str) -> str:
    """Put `block` into `description`, replacing a previous one if present.

    Never edits a byte outside the markers. Returns the input unchanged when the
    block is already exactly right, so the caller can skip the write entirely.
    """
    desc = description or ""
    start = desc.find(BLOCK_OPEN)
    end = desc.find(BLOCK_CLOSE)
    if start != -1 and end != -1 and end > start:
        return desc[:start] + block + desc[end + len(BLOCK_CLOSE):]
    return (desc.rstrip() + "\n\n" + block) if desc.strip() else block


# --- writing ---------------------------------------------------------------

def already_absorbed(issue: dict) -> bool:
    for c in ((issue.get("comments") or {}).get("nodes") or []):
        if ABSORB_MARKER in (c.get("body") or ""):
            return True
    return False


def is_closed(issue: dict) -> bool:
    return ((issue.get("state") or {}).get("type") or "") in CLOSED_STATE_TYPES


def append_record(audit_path: str, record: dict) -> dict:
    """One JSON line, flushed and fsynced BEFORE the caller writes anything else.

    sp-b5dcf944. The point is not tidiness: a run that dies at issue 20 of 49
    must still be able to say what happened to the first 20 permanent objects it
    touched. Batching this to the end is how that record was lost once already.
    """
    if audit_path:
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return record


class LinearWriter:
    """The only thing here that mutates a permanent Linear object."""

    def __init__(self, ls, close_state_id: str | None):
        self.ls = ls
        self.close_state_id = close_state_id

    def write_survivor_block(self, issue: dict, block: str) -> str:
        desc = issue.get("description") or ""
        new = splice_block(desc, block)
        if new == desc:
            return "dor-unchanged"
        self.ls.graphql(self.ls.ISSUE_UPDATE,
                        {"id": issue["id"], "input": {"description": new}})
        return "dor-written"

    def add_comment(self, issue: dict, body: str) -> str:
        self.ls.graphql(self.ls.COMMENT_CREATE,
                        {"input": {"issueId": issue["id"], "body": body}})
        return "comment-added"

    def close_issue(self, issue: dict) -> str:
        # 'canceled', never 'completed': marking an absorbed issue Done would
        # claim work was finished that nobody did, and that lie outlives the board.
        if not self.close_state_id:
            return "NOT-CLOSED (no canceled-type state on this team)"
        self.ls.graphql(self.ls.ISSUE_UPDATE,
                        {"id": issue["id"], "input": {"stateId": self.close_state_id}})
        return "closed"


def apply_family(family: dict, writer, audit_path: str, ts: str | None = None) -> list:
    """Write one family. Survivor roster first, then per member: comment, close.

    The order is the contract. A close with no pointer is an orphan: the issue is
    off the board and nothing links it to the survivor that inherited its target.
    So the comment always precedes the close, and each step's record hits disk
    before the next step runs.
    """
    ts = ts or _now()
    survivor = family["survivor"]
    base = {"ts": ts, "survivor": survivor["identifier"],
            "template": family["template"], "producer": family["producer"],
            "family_size": len(family["members"])}
    records = []

    out = writer.write_survivor_block(survivor, survivor_block(family, ts))
    records.append(append_record(audit_path, dict(
        base, issue=survivor["identifier"], step="survivor-dor", outcome=out)))

    for member in family["absorbed"]:
        # Resume, do not skip: a member commented by a run that died before its
        # close must still get closed, or it stays open forever behind a pointer
        # that says it was collapsed.
        if already_absorbed(member):
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="commented",
                outcome="already-present")))
        else:
            out = writer.add_comment(member, absorb_comment(family, member, ts))
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="commented", outcome=out)))

        if is_closed(member):
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="closed",
                outcome="already-closed")))
        else:
            out = writer.close_issue(member)
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="closed", outcome=out)))
    return records


# --- fetching --------------------------------------------------------------

def fetch_open(ls, team_id: str, project: str | None) -> list:
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    out = [i for i in issues if not is_closed(i)]
    if project:
        out = [i for i in out if ((i.get("project") or {}).get("name") or "") == project]
    return out


def closed_state_id(ls, team_id: str) -> str | None:
    states = (((ls.graphql(ls.TEAM_STATES_QUERY, {"teamId": team_id}) or {})
               .get("team") or {}).get("states") or {}).get("nodes") or []
    for s in states:
        if s.get("type") == "canceled":
            return s["id"]
    return None


def load_issues(args):
    """(issues, ls, team_id). KIPI_COLLAPSE_FIXTURE is the offline seam.

    Same shape as KIPI_GH in linear-triage.py: the suite drives the real entry
    point with real argv and no network, so "dry run writes nothing" is asserted
    against the shipped code path rather than a reimplementation of it.
    """
    fixture = os.environ.get("KIPI_COLLAPSE_FIXTURE")
    if fixture:
        return json.loads(Path(fixture).read_text()), None, None
    ls = _load(HERE / "linear-sync.py", "ls")
    team_id = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % args.team,
                         {})["teams"]["nodes"][0]["id"]
    project = None if args.project == "all" else args.project
    return fetch_open(ls, team_id, project), ls, team_id


# --- main ------------------------------------------------------------------

def print_plan(families: list, total: int) -> None:
    absorbed = sum(len(f["absorbed"]) for f in families)
    print("%d open issue(s) scanned; %d family/families found covering %d issue(s)."
          % (total, len(families), sum(len(f["members"]) for f in families)))
    print("collapsing them takes the open count from %d to %d.\n"
          % (total, total - absorbed))
    for f in families:
        print("FAMILY  %-10s survivor, %d absorbed   template: %s"
              % (f["survivor"]["identifier"], len(f["absorbed"]), f["template"]))
        print("        filed by: %s" % (f["producer"] or "(human)"))
        for m in f["members"]:
            targets = member_targets(m)
            mark = "SURVIVOR" if m is f["survivor"] else "absorb  "
            print("        %s %-10s %s" % (mark, m["identifier"],
                                           ", ".join(targets) or "(no explicit target)"))
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default="ASK", help="Linear team key (default ASK)")
    ap.add_argument("--project", default="kipi-system",
                    help="only this project, or 'all' (default kipi-system)")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE: survivor roster, absorb comments, close absorbed")
    ap.add_argument("--min-family", type=int, default=2,
                    help="smallest family to collapse (default 2)")
    ap.add_argument("--out", default="", help="audit JSONL path (default under q-system/output/)")
    args = ap.parse_args()

    issues, ls, team_id = load_issues(args)
    if not issues:
        print("no open issues to scan")
        return 0

    families = detect_families(issues, min_family=args.min_family)
    if not families:
        print("%d open issue(s) scanned; no duplicate-template family found."
              % len(issues))
        return 0

    print_plan(families, len(issues))

    if not args.apply:
        print("dry run — nothing was written. Re-run with --apply to collapse.")
        print("Read the roster above first: --apply closes %d permanent Linear "
              "objects." % sum(len(f["absorbed"]) for f in families))
        return 0

    audit = args.out or str(REPO / DEFAULT_AUDIT.format(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    Path(audit).parent.mkdir(parents=True, exist_ok=True)
    writer = LinearWriter(ls, closed_state_id(ls, team_id))

    done, failed = 0, None
    try:
        for f in families:
            apply_family(f, writer, audit)
            done += 1
            print("applied %s (+%d absorbed)" % (f["survivor"]["identifier"],
                                                 len(f["absorbed"])))
    except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
        failed = "%s: %s" % (type(exc).__name__, exc)

    print("\naudit -> %s" % audit)
    if failed:
        print("INCOMPLETE: %d/%d family/families applied before the run stopped "
              "(%s). Every write that landed is in the audit file; re-running is "
              "safe and resumes." % (done, len(families), failed), file=sys.stderr)
        return 9
    print("%d/%d family/families applied." % (done, len(families)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
