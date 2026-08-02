#!/usr/bin/env python3
"""Expire a `blocked:capability` label when the capability it names now exists.

THE DEFECT THIS CLOSES (ASK-284, 2026-08-02). `blocked:capability` was terminal.
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

ANTI-THRASH, THE PROPERTY THAT MATTERS. A probe that still reads "absent" holds
the block with NO write and NO dispatch. Re-offering an issue whose block is
still real is the failure mode that would make this worse than the disease, so
the hold path is the cheap one: a read, a comparison, and silence.
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

def probe_blocks(comments):
    """Every fenced probe block on an issue, oldest first."""
    out = []
    for c in comments:
        for m in _FENCE_RE.finditer(c.get("body") or ""):
            out.append([ln.strip() for ln in m.group(1).splitlines() if ln.strip()])
    return out


def parse_probes(comments):
    """(probe tokens from the NEWEST real probe block, legacy_reoffer_spent).

    Newest wins because a re-block supersedes an earlier one: the capability that
    is missing NOW is the one that decides whether the issue is workable, and an
    older block naming an already-satisfied capability would expire it wrongly.
    """
    blocks = probe_blocks(comments)
    spent = any(LEGACY_CONSUMED in b for b in blocks)
    for block in reversed(blocks):
        tokens = [t for t in block if t != LEGACY_CONSUMED and not t.startswith("#")]
        if tokens:
            return tokens, spent
    return [], spent


# ------------------------------------------------------------------ verdict

def verdict(issue, root):
    """("expire"|"hold"|"skip", reason). Pure: no writes, no network."""
    state = (issue.get("state") or {}).get("type")
    if state in TERMINAL_STATE_TYPES:
        return "skip", "issue is %s; a closed issue keeps its labels" % state

    comments = (issue.get("comments") or {}).get("nodes", [])
    tokens, spent = parse_probes(comments)

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
    body = (
        "**`blocked:capability` expired -- the block was re-tested, not "
        "hand-cleared.**\n\n%s\n\n" % reason
    )
    if probes:
        body += "Probe re-run:\n\n```%s\n%s\n```\n\n" % (PROBE_FENCE, "\n".join(probes))
    else:
        body += (
            "```%s\n%s\n```\n\n"
            "This block predates probe-recording, so it could not be re-tested "
            "mechanically and was re-offered once. The marker above is what makes "
            "that once-ever: if the runner blocks again it must record a probe, and "
            "this issue will never take a free re-offer a second time.\n\n"
            % (PROBE_FENCE, LEGACY_CONSUMED)
        )
    body += (
        "The label is removed and the state moved back so the picker can offer it "
        "again. **Next:** the worker picks this up on its next run. No founder "
        "action is needed -- a block expiring is the loop re-testing its own "
        "verdict, not a decision."
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
            ok = ls.unblock_issue(ident, args.label, expire_note(reason, tokens))
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
