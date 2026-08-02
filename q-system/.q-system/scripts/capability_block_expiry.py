#!/usr/bin/env python3
"""Expire a `blocked:capability` label when the capability it names now exists.

THE DEFECT THIS CLOSES (ASK-288, 2026-08-02). `blocked:capability` was terminal.
It records a point-in-time verdict about the ENVIRONMENT -- "this runner is not
equipped" -- and nothing ever re-tested it. The environment is exactly the thing
that changes underneath a verdict: ASK-140 was parked on "no safe write route
into .claude/", and `apply-claude-changes.sh` shipped on 2026-08-01. The block
was stale within a day and would have sat forever, because the picker refuses to
offer a labelled issue (linear_pick.HOLD_LABELS) and nothing un-labels it.

Inflow is automated and outflow was manual, so blocks only accumulated. Measured
2026-08-02: ten open issues carried the label, not the four anybody remembered.

WHY A PROBE AND NOT A TTL. A TTL expires on the calendar, which is not the thing
that caused the block. It would re-offer a still-blocked issue every N days --
burning a dispatch each time to re-learn a fact nobody changed -- and it would
also sit on an EXPIRED block for the rest of its window. The cause is what has to
be re-tested, so the refusal has to record the cause in a form a machine can
re-run. Prose cannot be re-run; that was the real root cause, one layer under the
label.

WHY THE PROBE VOCABULARY IS ENUMERATED AND NEVER EXECUTED. The obvious design is
"let the refusing agent write a shell command and run it at pick time". That
persists agent-authored shell to be executed later, unattended, with the
founder's privileges -- a new code-execution path of exactly the kind ASK-282 was
opened to CLOSE. So a probe is a token from a fixed vocabulary, evaluated by the
functions below. Nothing here shells out. An unparseable probe is a refusal to
guess, not a best-effort exec.

WHY AN UNVERIFIABLE BLOCK GETS ONE RE-OFFER. Every block written before this
mechanism existed carries no probe, and hand-editing ten issues to backfill one
is the manual outflow this is meant to delete. A block nobody can re-test is not
evidence the block is still real -- it is an absence of evidence either way, and
the only instrument left is to try. So it is re-offered EXACTLY ONCE, and the
attempt is recorded on the issue so it can never repeat. If the runner blocks
again, that refusal writes a probe, and the issue is probe-gated from then on.
The population of unverifiable blocks is finite and strictly shrinking; it
converges to zero and cannot thrash.

THE GUARANTEE, STATED EXACTLY (revised after the PR #69 review found the first
version false). Per issue, forever:

  1. A block whose NEWEST refusal records a probe that still reads "absent" is
     held with NO write and NO dispatch. Only the newest refusal's probe is
     consulted; an older fence never answers for a newer block.
  2. A block whose newest refusal records NO probe is re-offered AT MOST ONCE,
     ever. The re-offer is recorded by the REOFFERED_LABEL, written in the same
     mutation that removes the block, so the count cannot drift.

The first version claimed "a still-real block never burns a pick" and that was
false: a probe-less refusal emitted no fence, could not supersede an older
PASSING fence, and so re-expired the same real block on every worker tick --
unbounded, one runner dispatch per cycle. Both the anti-thrash claim and the
"exactly one re-offer" bound rode on that. What makes them true now is that
every refusal emits a fence (`no-probe` when it has nothing better), plus a
staleness backstop for any producer that forgets.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sys

EXIT_OK = 0
EXIT_ERROR = 1

HERE = pathlib.Path(__file__).resolve().parent

# The fence an agent writes its probe into, and the marker this tool writes back
# when it spends an unverifiable block's single re-offer. Both live in Linear
# comments because that is where the LABEL lives: a machine-local state file
# would disagree with the board the moment the checkout is rebuilt, and the
# disagreement would silently re-spend a re-offer that was already used.
PROBE_FENCE = "kipi-capability-probe"
LEGACY_CONSUMED = "legacy-reoffer-consumed"

# Written by a refusal that could not name a probe. It exists so the NEWEST
# refusal always wins: without an explicit token, a probe-less refusal emitted no
# fence at all and therefore could not supersede an older PASSING fence, so a
# still-real block re-expired on every tick -- one runner dispatch burned per
# cycle, forever (codex review of PR #69, reproduced 2026-08-02). The claim that
# "missing probes degrade, they do not wedge" was true; the claim that a still-
# real block never burns a pick was NOT, and this is what makes it true.
NO_PROBE = "no-probe"

# The label that records a spent re-offer. It is a LABEL and not a comment marker
# because it is written in the SAME issueUpdate that removes blocked:capability,
# so the two cannot disagree. The comment-marker version had an ordering hazard
# with no safe answer: post first and a failed update spends the re-offer while
# the block stays on (permanently wedged), post second and a failed comment
# re-arms the re-offer forever. One atomic write has neither failure.
REOFFERED_LABEL = "capability:reoffered"

# Producer text from linear-worker.sh's capability REFUSE_NOTE. Used only to date
# the newest refusal, never to parse one -- see stale-fence handling below.
REFUSAL_MARKER = "Blocked on a missing capability"

# States that mean nobody is waiting on this issue. A closed issue keeps its
# labels, so the live board hands back a `blocked:capability` issue that is
# already Done (ASK-281 is one). Un-blocking it would reopen finished work.
TERMINAL_STATE_TYPES = ("completed", "canceled")

_FENCE_RE = re.compile(
    r"^```" + re.escape(PROBE_FENCE) + r"[ \t]*\n(.*?)^```",
    re.DOTALL | re.MULTILINE,
)


# ------------------------------------------------------------------ probes

def probe_file(arg, root):
    """A capability that is a script or tool checked into this repo."""
    target = os.path.join(root, arg)
    # Reject traversal rather than resolving it. A probe is agent-authored text
    # and the honest answer to "../../etc/passwd" is that it is not a repo path,
    # not a helpful normalisation of it.
    if os.path.isabs(arg) or ".." in pathlib.PurePosixPath(arg).parts:
        return False, "not a repo-relative path: %s" % arg
    return os.path.isfile(target), target


def probe_exec(arg, root):
    """A capability that is a binary on PATH."""
    found = shutil.which(arg)
    return bool(found), found or ("not on PATH: %s" % arg)


def probe_env(arg, root):
    """A capability that is a credential or setting in the environment."""
    val = os.environ.get(arg)
    return bool(val), ("set" if val else "unset") + ": $" + arg


def probe_manifest_test(arg, root):
    """A capability declared in the fleet capability manifest."""
    manifest = os.path.join(root, "q-system", ".q-system", "capability-manifest.json")
    if not os.path.isfile(manifest):
        return False, "no capability-manifest.json"
    try:
        with open(manifest) as fh:
            data = json.load(fh)
    except ValueError:
        return False, "capability-manifest.json does not parse"
    paths = {e.get("path") for e in (data.get("expected_tests") or []) if isinstance(e, dict)}
    return arg in paths, "declared" if arg in paths else "not declared: %s" % arg


PROBES = {
    "file": probe_file,
    "exec": probe_exec,
    "env": probe_env,
    "manifest_test": probe_manifest_test,
}


def evaluate_probe(token, root):
    """(ok, detail) for one probe token. Never executes the token."""
    token = token.strip()
    if not token or token.startswith("#"):
        return None, "comment"
    if token == LEGACY_CONSUMED:
        return None, "marker"
    kind, sep, arg = token.partition(":")
    if not sep or kind not in PROBES:
        # Fail CLOSED. An unrecognised probe is not a passing probe: treating a
        # typo as "capability present" would un-block on a malformed refusal.
        return False, "unknown probe kind: %s" % token
    return PROBES[kind](arg.strip(), root)


# ------------------------------------------------------------------ parsing

def _ordered(comments):
    """Comments oldest-first by createdAt, with a stable fallback.

    Never trust arrival order for a recency decision. Sorting on the field the
    decision actually rests on is the difference between "the newest fence" and
    "whichever fence the API happened to hand back last".
    """
    return sorted(comments, key=lambda c: (c.get("createdAt") or "", ))


def probe_blocks(comments):
    """(createdAt, tokens) for every fenced probe block, oldest first."""
    out = []
    for c in _ordered(comments):
        for m in _FENCE_RE.finditer(c.get("body") or ""):
            out.append((c.get("createdAt") or "",
                        [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]))
    return out


def parse_probes(comments):
    """(tokens of the NEWEST fence, reoffer_spent). [] means unverifiable.

    THE NEWEST FENCE ANSWERS, AND ONLY THE NEWEST (codex review of PR #69). The
    first version walked backwards until it found a fence with tokens, so a fence
    with no tokens -- or no fence at all -- silently deferred to an OLDER one. An
    issue that once recorded a passing probe then re-expired forever, because the
    stale fence kept answering for a block it never described. "The newest fence
    anywhere in history" and "this block's probe" are different claims, and
    reading the first as the second is the whole defect.

    STALENESS BACKSTOP. Fence-ordering alone only works if every refusal emits a
    fence. The worker now does, but a producer that forgets (or any comment
    written before this existed) would put the newest FENCE behind the newest
    REFUSAL, and the stale fence would answer again. So a fence older than the
    most recent refusal is discarded as stale. Belt and braces on purpose: a
    false expiry costs a runner dispatch every cycle, which is far dearer than
    the ten lines that prevent it.
    """
    blocks = probe_blocks(comments)
    spent = any(LEGACY_CONSUMED in toks for _, toks in blocks)
    if not blocks:
        return [], spent

    fence_at, tokens = blocks[-1]
    refusals = [c.get("createdAt") or "" for c in _ordered(comments)
                if REFUSAL_MARKER in (c.get("body") or "")]
    # Strict >: a refusal and the fence it carries share one comment and one
    # timestamp, and that fence is the current one, not a stale one.
    if refusals and refusals[-1] > fence_at:
        return [], spent

    tokens = [t for t in tokens if t != LEGACY_CONSUMED and not t.startswith("#")]
    if tokens == [NO_PROBE]:
        return [], spent
    return tokens, spent


# ------------------------------------------------------------------ verdict

def verdict(issue, root):
    """("expire"|"hold"|"skip", reason). Pure: no writes, no network."""
    state = (issue.get("state") or {}).get("type")
    if state in TERMINAL_STATE_TYPES:
        return "skip", "issue is %s; a closed issue keeps its labels" % state

    comments = (issue.get("comments") or {}).get("nodes", [])
    tokens, marker_spent = parse_probes(comments)

    # The label is authoritative (atomic with the un-block). The comment marker
    # is still honoured because ten issues were expired on 2026-08-02 under the
    # marker-only design; dropping it would hand every one of them a second
    # "first" re-offer.
    labels = {n["name"] for n in (issue.get("labels") or {}).get("nodes", [])}
    spent = REOFFERED_LABEL in labels or marker_spent

    if not tokens:
        if spent:
            return "hold", (
                "no probe recorded and its single re-offer is already spent; "
                "the next refusal must record a probe"
            )
        return "expire", (
            "no probe recorded (blocked before probes existed), so the block is "
            "UNVERIFIABLE -- spending its one re-offer"
        )

    failed = []
    for token in tokens:
        ok, detail = evaluate_probe(token, root)
        if ok is None:
            continue
        if not ok:
            failed.append("%s (%s)" % (token, detail))
    if failed:
        return "hold", "still missing: " + "; ".join(failed)
    return "expire", "every recorded probe now passes: " + ", ".join(tokens)


# ------------------------------------------------------------------ io

def load_sync():
    spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}} comments{nodes{body createdAt}}}
 pageInfo{hasNextPage endCursor}}}"""


def fetch_issues(team_key):
    ls = load_sync()
    tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % team_key, {})
    tid = tid["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues


def blocked_issues(issues, repo_project, label):
    out = []
    for i in issues:
        names = {n["name"] for n in (i.get("labels") or {}).get("nodes", [])}
        if label not in names:
            continue
        if repo_project and (i.get("project") or {}).get("name") != repo_project:
            continue
        out.append(i)
    return out


def expire_note(reason, probes):
    """The comment recording an expiry.

    IT NEVER EMITS A PROBE FENCE. The first version re-posted the probes it had
    just re-run, which put a PASSING fence at the top of the history -- so the
    next real block inherited a fence saying its capability was present and
    re-expired forever. The expiry was manufacturing the stale fence that broke
    it (codex review of PR #69). Probes are recorded by REFUSALS; the expiry only
    reports.

    IT ALSO DOES NOT CLAIM THE LABEL IS ALREADY OFF. It is posted before the
    update, so on a failed update the old wording left a permanent comment on an
    undeletable object asserting something that never happened.
    """
    body = (
        "**`blocked:capability` is being expired -- the block was re-tested, not "
        "hand-cleared.**\n\n%s\n\n" % reason
    )
    if probes:
        body += "Probes re-run, all passing: %s\n\n" % ", ".join("`%s`" % p for p in probes)
    else:
        body += (
            "This block records no probe, so it could not be re-tested "
            "mechanically and is being re-offered **once**. The `%s` label "
            "applied with this change is what makes that once-ever: if the runner "
            "blocks again it must record a probe, and this issue will never take a "
            "free re-offer a second time.\n\n" % REOFFERED_LABEL
        )
    body += (
        "The label removal and state move are being applied now. **If you can "
        "still see `blocked:capability` on this issue, the update did not land** "
        "and the block still stands -- the run logs a `FAIL` line in that case.\n\n"
        "**Next:** the worker picks this up on its next run. No founder action is "
        "needed -- a block expiring is the loop re-testing its own verdict, not a "
        "decision."
    )
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default="ASK")
    ap.add_argument("--repo-project", default=os.environ.get("REPO_PROJECT", ""))
    ap.add_argument("--label", default="blocked:capability")
    ap.add_argument("--root", default=str(HERE.parent.parent.parent),
                    help="repo root the probes resolve against (test seam)")
    ap.add_argument("--fixture", default="",
                    help="read issues from a frozen JSON instead of Linear (test seam)")
    ap.add_argument("--apply", action="store_true",
                    help="actually remove labels; without it this only reports")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if args.fixture:
        with open(args.fixture) as fh:
            issues = json.load(fh)["issues"]
    else:
        issues = fetch_issues(args.team)

    held = blocked_issues(issues, args.repo_project, args.label)
    expired, holds, skips, failures = [], [], [], []

    for issue in held:
        call, reason = verdict(issue, root)
        ident = issue["identifier"]
        if call == "skip":
            skips.append((ident, reason))
            continue
        if call == "hold":
            holds.append((ident, reason))
            continue

        tokens, _ = parse_probes((issue.get("comments") or {}).get("nodes", []))
        if not args.apply:
            expired.append((ident, reason))
            continue

        # SINGLE WRITER. Every mutation goes through linear-sync's `unblock`,
        # which removes the label and moves the state in one verified step. Two
        # writers to one issue is how a half-applied un-block happens: label
        # gone, state still `started`, picker still silent, and the tool
        # reporting success.
        ls = load_sync()
        try:
            # The re-offer marker rides in the SAME mutation that removes the
            # block, so a partial write cannot leave the two disagreeing. Only an
            # unverifiable block (no probe) spends a re-offer; a probe-verified
            # expiry needs no marker because its probe can simply be re-run.
            ok = ls.unblock_issue(ident, args.label, expire_note(reason, tokens),
                                  add_label="" if tokens else REOFFERED_LABEL)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            ok, exc_detail = False, str(exc)[:200]
            failures.append((ident, exc_detail))
        if ok:
            expired.append((ident, reason))
        elif not failures or failures[-1][0] != ident:
            failures.append((ident, "unblock did not apply"))

    for ident, reason in skips:
        print("SKIP   %s: %s" % (ident, reason))
    for ident, reason in holds:
        print("HOLD   %s: %s" % (ident, reason))
    for ident, reason in expired:
        print("EXPIRE %s: %s" % (ident, reason))
    for ident, reason in failures:
        print("FAIL   %s: %s" % (ident, reason), file=sys.stderr)

    verb = "expired" if args.apply else "would expire"
    print("capability-block-expiry: %d held, %d %s, %d still blocked, %d failed"
          % (len(held), len(expired), verb, len(holds), len(failures)))
    return EXIT_ERROR if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
