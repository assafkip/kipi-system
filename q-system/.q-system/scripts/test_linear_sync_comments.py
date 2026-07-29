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
"""
import importlib.util
import io
import pathlib
import sys
import contextlib

HERE = pathlib.Path(__file__).resolve().parent
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
    rc, out, _ = run_comments(mod, Args("ASK-221"), make_issue([C_SANA, C_CODEX]))
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
                              make_issue([C_SANA, C_CODEX]))
    if "sana" in out.replace("codex-reviewer", ""):
        fail(f"--agent codex-reviewer returned Sana's comment too. Got:\n{out}")
    elif "APPROVE WITH NITS" not in out:
        fail(f"--agent codex-reviewer dropped the reviewer's own comment. Got:\n{out}")
    else:
        ok("--agent filters on the comment body, not the API author")

    # --- a speaker who has not spoken yet says so, and does not error ----------
    rc, out, _ = run_comments(mod, Args("ASK-221", agent="nobody-here"),
                              make_issue([C_SANA, C_CODEX]))
    if rc != 0:
        fail(f"an empty filter result exited {rc}; a reviewer who has not commented "
             "yet is a normal state, not a failure")
    elif "no comments match" not in out:
        fail(f"an empty filter result did not say so explicitly. Got:\n{out}")
    else:
        ok("a filter matching nothing says 'no comments match' and exits 0")

    # --- --last N keeps the MOST RECENT, not the oldest ------------------------
    rc, out, _ = run_comments(mod, Args("ASK-221", last=1),
                              make_issue([C_SANA, C_CODEX]))
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
