#!/usr/bin/env python3
"""Contract test for `linear-sync.py comments` -- the READ half of the Sana/codex
review conversation (ASK-221).

WHY THIS EXISTS: `progress` could already WRITE a comment onto a Linear issue, so
the review trail was one-way -- codex posted and Sana never saw it, because the
worker reads PR comments while the founder's directive put the conversation on the
issue. `comments` is the read verb that makes a reply possible. A read verb that
returns the wrong author, or silently returns nothing, breaks the conversation
without breaking anything loudly, which is why it gets a test rather than a manual
eyeball.

NO LIVE LINEAR. `graphql` is monkeypatched on the loaded module, so nothing here
touches the network or the founder's permanent Linear objects. That is a hard rule
for this repo's tests, not a nicety: a test that writes to a Linear object cannot
be undone, and one that READS a live issue fails whenever that issue changes.

THE NEGATIVE SELF-TEST IS BUILT IN. Every `--agent` case below was added AFTER the
bug it names was already fixed, which is the shape that produces a suite full of
assertions nobody has ever seen fail. `KIPI_TEST_LINEAR_SYNC_REF=<git-ref>` loads
the module from that ref instead of the working tree, so the claim "this case
catches that bug" stays checkable instead of being a comment:

  KIPI_TEST_LINEAR_SYNC_REF=63f81de -> the first-line anchor case must FAIL
  KIPI_TEST_LINEAR_SYNC_REF=de2a9c3 -> the delimiter case must FAIL, anchor passes
  (unset)                           -> everything passes
"""
import importlib.util
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import contextlib

HERE = pathlib.Path(__file__).resolve().parent
_REF = os.environ.get("KIPI_TEST_LINEAR_SYNC_REF", "").strip()
if _REF:
    # Read-only: `git show` to a temp file. The repo working tree is never touched,
    # so this cannot disturb a session running in the same checkout.
    _repo = HERE.parents[2]
    _blob = subprocess.run(
        ["git", "-C", str(_repo), "show", f"{_REF}:q-system/.q-system/scripts/linear-sync.py"],
        capture_output=True, text=True)
    if _blob.returncode != 0:
        print(f"FAIL: cannot read linear-sync.py at ref {_REF}: {_blob.stderr.strip()}")
        sys.exit(1)
    _tmp = pathlib.Path(tempfile.mkdtemp()) / "linear-sync.py"
    _tmp.write_text(_blob.stdout)
    TARGET = _tmp
    print(f"module under test: ref {_REF} ({len(_blob.stdout.splitlines())} lines)")
else:
    TARGET = HERE / "linear-sync.py"

FAILURES = []
PASSES = []


def ok(msg):
    PASSES.append(msg)
    print(f"  PASS {msg}")


def fail(msg):
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def load_module():
    """Load linear-sync.py by path. The filename has a hyphen, so `import` cannot
    reach it and importlib is the only way in."""
    spec = importlib.util.spec_from_file_location("linear_sync_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Args:
    def __init__(self, issue, agent=None, last=0):
        self.issue = issue
        self.agent = agent
        self.last = last


def make_issue(nodes):
    return {"issue": {"id": "uuid-1", "identifier": "ASK-221",
                      "title": "codex reviews every PR",
                      "comments": {"nodes": nodes}}}


C_SANA = {"id": "c1", "createdAt": "2026-07-28T01:00:00.000Z",
          "body": "**sana** · 2026-07-28 01:00 UTC\n\nPicked up by the worker.",
          "user": {"name": "Assaf Kipnis"}, "botActor": None}
C_CODEX = {"id": "c2", "createdAt": "2026-07-29T02:00:00.000Z",
           "body": "**codex-reviewer** · 2026-07-29 02:00 UTC\n\nVerdict: APPROVE WITH NITS",
           "user": {"name": "Assaf Kipnis"}, "botActor": None}
C_BOT = {"id": "c3", "createdAt": "2026-07-29T03:00:00.000Z",
         "body": "**codex-reviewer** · bot-written",
         "user": None, "botActor": {"name": "kipi-bot"}}

# THE REAL REVIEWER COMMENT, not a convenient one. pr-review-agent.sh writes the
# literal sentence "Sana: reply to this comment on THIS issue" into the body of the
# REVIEWER's own comment. The first cut of --agent matched a bare substring, so
# `--agent sana` returned THIS comment as if Sana had authored it. Codex caught it
# on 2026-07-29 while the suite was green, because the old fixture never put the
# word "sana" inside a reviewer comment. Fixtures built from the same mental model
# as the code test nothing -- this one is copied from what the code actually emits.
C_CODEX_MENTIONS_SANA = {
    "id": "c4", "createdAt": "2026-07-29T04:00:00.000Z",
    "body": ("**codex-reviewer** · 2026-07-29 04:00 UTC\n\n"
             "Review of PR #35 complete (codex engine). Verdict: REQUEST CHANGES.\n\n"
             "Sana: reply to this comment on THIS issue. For each finding, either "
             "the file:line that already handles it, or what you changed."),
    "user": {"name": "Assaf Kipnis"}, "botActor": None}

# THE SHAPE CODEX FOUND, 2026-07-30. The case above covers the bare text "Sana:".
# It does NOT cover the attribution MARKER appearing in prose, so anchoring the
# filter on `**sana**` anywhere in the body still passed it while misattributing
# this comment. A reviewer discussing attribution writes the marker verbatim, and
# so does any comment quoting `progress` output -- several in this very thread do.
# Fixture copied from Codex's executed reproducer, not invented.
C_CODEX_QUOTES_MARKER = {
    "id": "c5", "createdAt": "2026-07-29T05:00:00.000Z",
    "body": ("**codex-reviewer** · 2026-07-29 05:00 UTC\n\n"
             "The fix preserves **sana** attribution on the first line."),
    "user": {"name": "Assaf Kipnis"}, "botActor": None}


# CODEX'S SECOND REPRO ON THE SAME BUG, 2026-07-30. First-line anchoring on the
# bold marker alone still reads prose that OPENS with a bold mention as authorship.
# `progress` always emits the delimiter, so the delimiter is the contract.
C_PROSE_OPENS_WITH_MARKER = {
    "id": "c6", "createdAt": "2026-07-29T06:00:00.000Z",
    "body": ("**sana** please review this note\n\n"
             "Not emitted by progress and not authored by Sana."),
    "user": {"name": "Codex"}, "botActor": None}

# Guards the prefix-collision case codex explicitly tried and found SOUND, so a
# future "simplification" that drops the closing delimiter cannot pass unnoticed.
C_SIMILAR_AGENT = {
    "id": "c7", "createdAt": "2026-07-29T07:00:00.000Z",
    "body": "**sana-ops** · 2026-07-29 07:00 UTC\n\nDifferent agent entirely.",
    "user": {"name": "Assaf Kipnis"}, "botActor": None}


def run_comments(mod, args, payload=None, raise_exc=None):
    """Drive cmd_comments with graphql stubbed. Returns (rc, stdout, stderr)."""
    def stub(_query, _vars):
        if raise_exc:
            raise raise_exc
        return payload
    mod.graphql = stub
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.cmd_comments(args)
    return rc, out.getvalue(), err.getvalue()


def main():
    if not TARGET.exists():
        print(f"FAIL: {TARGET} does not exist")
        return 1
    mod = load_module()

    if not hasattr(mod, "cmd_comments"):
        print("FAIL: linear-sync.py has no cmd_comments; the read half of the review "
              "conversation does not exist, so Sana cannot see what codex said")
        return 1
    ok("linear-sync.py exposes cmd_comments")

    # --- the whole thread comes back, both speakers, in order ------------------
    # FIXTURE ORDER IS DESCENDING ON PURPOSE, because that is what Linear actually
    # returns (verified live on ASK-221, 2026-07-29). The first cut of this test fed
    # an ascending fixture, matching the author's assumption rather than the
    # producer, so it passed while `--last N` returned the OLDEST N and hid a Codex
    # reply for two turns. Every case below now feeds newest-first, so the sort in
    # cmd_comments is what the assertions actually exercise.
    rc, out, _ = run_comments(mod, Args("ASK-221"), make_issue([C_CODEX, C_SANA]))
    if rc != 0:
        fail(f"reading a good issue exited {rc}, expected 0")
    elif "sana" not in out or "codex-reviewer" not in out:
        fail(f"the thread dropped a speaker. Got:\n{out}")
    elif out.index("sana") > out.index("codex-reviewer"):
        fail("the thread is not in chronological order, so it does not read as a "
             f"conversation. Got:\n{out}")
    else:
        ok("the full thread reads back in order with both speakers")

    # --- the count is stated so a truncated read is visible --------------------
    if "2 comment(s)" not in out:
        fail(f"the comment COUNT is not printed, so a partial read looks complete. Got:\n{out}")
    else:
        ok("the comment count is stated")

    # --- --agent filters on the BODY, because the API author is the token ------
    # Verified live 2026-07-29: user.name is the TOKEN OWNER ("Assaf Kipnis") for
    # every agent-written comment, so filtering on the API author cannot separate
    # Sana from the reviewer. The agent name only exists in the body.
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="codex-reviewer"),
                              make_issue([C_CODEX, C_SANA]))
    if "sana" in out.replace("codex-reviewer", ""):
        fail(f"--agent codex-reviewer returned Sana's comment too. Got:\n{out}")
    elif "APPROVE WITH NITS" not in out:
        fail(f"--agent codex-reviewer dropped the reviewer's own comment. Got:\n{out}")
    else:
        ok("--agent filters on the comment body, not the API author")

    # --- a speaker who has not spoken yet says so, and does not error ----------
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="nobody-here"),
                              make_issue([C_CODEX, C_SANA]))
    if rc != 0:
        fail(f"an empty filter result exited {rc}; a reviewer who has not commented "
             "yet is a normal state, not a failure")
    elif "no comments match" not in out:
        fail(f"an empty filter result did not say so explicitly. Got:\n{out}")
    else:
        ok("a filter matching nothing says 'no comments match' and exits 0")

    # --- --last N keeps the MOST RECENT, not the oldest ------------------------
    rc, out, _ = run_comments(mod, Args("ASK-221", last=1),
                              make_issue([C_CODEX, C_SANA]))
    if "APPROVE WITH NITS" not in out:
        fail(f"--last 1 returned the OLDEST comment. Reading the last N is how an "
             f"agent finds the newest review; returning the oldest means it answers "
             f"a review from three rounds ago. Got:\n{out}")
    elif "Picked up by the worker" in out:
        fail(f"--last 1 returned more than one comment. Got:\n{out}")
    else:
        ok("--last N returns the most recent N")

    # --- botActor is the fallback when there is no user -----------------------
    rc, out, _ = run_comments(mod, Args("ASK-221"), make_issue([C_BOT]))
    if "kipi-bot" not in out:
        fail(f"a comment with user=null printed no author from botActor. Got:\n{out}")
    elif "unknown" in out:
        fail(f"a bot-written comment printed 'unknown' instead of the bot name. Got:\n{out}")
    else:
        ok("botActor names the author when user is null")

    # --- a missing issue BLOCKS and exits non-zero ----------------------------
    rc, out, err = run_comments(mod, Args("ASK-999999"), {"issue": None})
    if rc == 0:
        fail("reading a non-existent issue exited 0. A caller would treat an absent "
             "thread as an empty one and answer a review it never read.")
    elif "BLOCK" not in err:
        fail(f"a missing issue did not say BLOCK on stderr. Got stderr:\n{err}")
    else:
        ok("a missing issue BLOCKs on stderr and exits non-zero")

    # --- an API error BLOCKS rather than raising ------------------------------
    rc, out, err = run_comments(mod, Args("ASK-221"),
                                raise_exc=mod.LinearAPIError("rate limited"))
    if rc == 0:
        fail("a Linear API error exited 0, so a failed read is indistinguishable "
             "from an empty thread")
    elif "BLOCK" not in err:
        fail(f"a Linear API error did not say BLOCK. Got stderr:\n{err}")
    else:
        ok("a Linear API error BLOCKs and exits non-zero")

    # --- REGRESSION: --agent must match the AUTHOR, not a mention -------------
    # The live bug Codex found. `--agent sana` against a thread where the REVIEWER
    # addressed Sana by name must return Sana's comment only. Getting this wrong
    # means Sana reads the reviewer's own comment as her prior reply, concludes she
    # already answered, and the review round silently does nothing.
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="sana"),
                              make_issue([C_CODEX_MENTIONS_SANA, C_SANA]))
    if "codex-reviewer" in out:
        fail("THE BUG CODEX FOUND: --agent sana returned the REVIEWER's comment, because "
             "the reviewer's body contains 'Sana: reply to this comment'. --agent must "
             f"match the '**author**' attribution marker, not any mention. Got:\n{out}")
    elif "Picked up by the worker" not in out:
        fail(f"--agent sana dropped Sana's own comment. Got:\n{out}")
    else:
        ok("--agent matches the '**author**' marker, not a mention of that agent")

    # --- REGRESSION: the marker must anchor to the FIRST LINE ------------------
    # Codex's finding, 2026-07-30. Anchoring on `**sana**` anywhere in the body is
    # not enough: a reviewer comment whose PROSE contains that marker is still
    # misattributed. Only the first line is the attribution.
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="sana"),
                              make_issue([C_CODEX_QUOTES_MARKER, C_SANA]))
    if "codex-reviewer" in out:
        fail("THE BUG CODEX FOUND ON THE FIX ITSELF: --agent sana returned a comment "
             "AUTHORED by codex-reviewer because its prose contains the marker "
             f"'**sana**'. Only the first line is the attribution. Got:\n{out}")
    elif "Picked up by the worker" not in out:
        fail(f"--agent sana dropped Sana's own comment. Got:\n{out}")
    else:
        ok("--agent anchors the marker to the first line, not anywhere in the prose")

    # --- REGRESSION: prose OPENING with the marker is not authorship ------------
    # Codex's second reproducer on this same bug. Anchoring to the first line is not
    # enough; the producer's delimiter is what distinguishes attribution from a bold
    # mention at the start of a sentence.
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="sana"),
                              make_issue([C_PROSE_OPENS_WITH_MARKER, C_SANA]))
    if "please review this note" in out:
        fail("THE BUG CODEX FOUND TWICE: --agent sana returned a comment whose first line "
             "merely OPENS with '**sana**' as prose. progress always emits '**sana** · ', so "
             f"the delimiter is the contract. Got:\n{out}")
    elif "Picked up by the worker" not in out:
        fail(f"--agent sana dropped Sana's real progress comment. Got:\n{out}")
    else:
        ok("--agent requires the full '**author** · ' attribution prefix, not a bold opener")

    # --- a similarly-named agent must not collide (codex tried this, found sound) --
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="sana"),
                              make_issue([C_SIMILAR_AGENT, C_SANA]))
    if "Different agent entirely" in out:
        fail(f"--agent sana matched '**sana-ops** · '. The closing '**' must prevent the "
             f"prefix collision. Got:\n{out}")
    else:
        ok("--agent sana does not match **sana-ops** (closing delimiter blocks collision)")

    # --- REGRESSION: progress must not claim success on a rejected mutation ----
    # The other live bug: commentCreate's result was discarded, so a rejected
    # mutation still printed "progress noted" and exited 0. The review CONVERSATION
    # runs on this call; a silent drop means the reviewer reports that its findings
    # reached the issue when no comment exists.
    if not hasattr(mod, "cmd_progress"):
        fail("linear-sync.py has no cmd_progress")
    else:
        class PArgs:
            issue = "ASK-221"; note = "n"; agent = "sana"; evidence = None

        def stub_reject(query, _vars):
            if "commentCreate" in query:
                return {"commentCreate": {"success": False, "comment": None}}
            return {"issue": {"id": "uuid-1", "identifier": "ASK-221",
                              "state": {"name": "In Progress"}}}
        mod.graphql = stub_reject
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.cmd_progress(PArgs())
        if rc == 0:
            fail("THE BUG CODEX FOUND: a REJECTED commentCreate exited 0, so a dropped "
                 "comment is indistinguishable from a delivered one on the channel the "
                 "review conversation depends on")
        elif "BLOCK" not in err.getvalue():
            fail(f"a rejected commentCreate did not say BLOCK. stderr:\n{err.getvalue()}")
        elif "progress noted" in out.getvalue():
            fail(f"a rejected commentCreate still printed success. stdout:\n{out.getvalue()}")
        else:
            ok("progress BLOCKs when Linear does not actually create the comment")

    # --- the verb is REGISTERED, not just defined ----------------------------
    # A cmd_ function nothing routes to is dead code: `comments` has to be reachable
    # from the CLI, because the only caller is a prompt telling an agent to run it.
    src = TARGET.read_text()
    if 'add_parser("comments"' not in src:
        fail("cmd_comments is defined but never registered with add_parser, so "
             "`linear-sync.py comments` is not a command and the prompt telling "
             "Sana to run it would fail")
    elif "func=cmd_comments" not in src:
        fail("the comments subparser does not route to cmd_comments")
    else:
        ok("the comments verb is registered on the CLI")

    print(f"\n== {len(PASSES)} passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
