#!/usr/bin/env python3
"""Cross-model escalation: when Opus is stuck, Fable triages (ASK-311).

Pairs with `.claude/rules/fable-escalation.md`. This script is the ONLY caller
of `claude -p --model claude-fable-5` in the fleet, and the only writer of the
escalation ledger. Two callers:

  token-guard.py  — automatic, on a Tier-A stuck BLOCK (see WHY SYNCHRONOUS)
  a human/agent   — `fable-escalate.py --trigger founder-repeat --reason "..."`
                    for the Tier-B/C judgment triggers the rule carries

Fable does NOT implement. It returns a triage packet (diagnosis / what to stop
doing / next path / the refuting check) and Opus keeps the work.

Contract with token-guard: one JSON object on stdout —
  {"triage": str|null, "escalated": bool, "capped": bool, "notified": bool,
   "delivered": bool, "failure": str|null}
`notified` means a page was ATTEMPTED; `delivered` means it could actually have
left the machine. They are separate because slack-notify.sh exits 0 having sent
nothing when no webhook resolves, so one field cannot carry both facts without
lying about one of them.
Exit is ALWAYS 0. A non-zero exit from here would turn a triage attempt into a
guard crash, and the guard's job (blocking a runaway loop) outranks this one.

WHY SYNCHRONOUS, AND ONLY FROM token-guard.py (decision D1, ASK-311).
The paired test is q-system/.q-system/tests/test_fable_escalation.py; the hook
that calls this script is token-guard.py on its PreToolUse exit-2 path.
Measured 2026-08-02: `claude -p --model claude-fable-5` answered in 5.35s, not
the 20-60s the design brief assumed. That exit-2 path is the one moment where
the session has ALREADY stopped — the agent is about to be told to give up — so
a few seconds there cost nothing that was not already lost, and the test suite
pins the ceiling at FABLE_CAP calls per actor. The same call on a warn tier, or
on UserPromptSubmit while the founder waits, would be latency with a human in
the loop; those tiers instead hand over the CLI this script exposes.

WHY THE PACKET GOES ON STDIN, NOT ARGV.
argv is world-readable through `ps`. The packet is a slice of the session
transcript, so it can carry file contents, error text and prompts. stdin is not
in the process table and has no length limit.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# The triage model. Verified reachable 2026-08-02 (`FABLE_OK`, 5.35s).
FABLE_MODEL = "claude-fable-5"

DEFAULT_TIMEOUT = 45        # seconds; the hook runner's own default is 60
DEFAULT_CAP = 2             # escalations per actor per session, then the human
TRANSCRIPT_WINDOW = 25      # trailing records fed to Fable
PER_RECORD_CHARS = 600
PACKET_CHAR_CAP = 12000
REASON_CHARS = 800          # the caller's own message, bounded at this end too

HERE = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_LEDGER_DIR = os.path.join(QROOT, "output", "fable-escalations")
DEFAULT_NOTIFY = os.path.join(HERE, "slack-notify.sh")

ASK = """You are triaging a stuck coding agent. You are NOT implementing anything.

Return exactly four labelled sections, no preamble:
DIAGNOSIS: what is actually blocking, as one falsifiable claim.
STOP: the approach that is looping, named concretely.
NEXT: one concrete action, with the command or file path that proves it.
REFUTE: the command that would show this diagnosis is wrong.

Be blunt and specific. If the packet is not enough to diagnose, say so in
DIAGNOSIS and make NEXT the command that would collect what is missing."""


# --------------------------------------------------------------------------
# packet
# --------------------------------------------------------------------------

def _render(record):
    """One transcript record as a short plain-text line, or None."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role") or record.get("type") or "?"
    content = message.get("content")
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "tool_use":
                parts.append("[tool %s] %s" % (
                    block.get("name"),
                    json.dumps(block.get("input", {}), default=str)))
            elif kind == "tool_result":
                parts.append("[result] %s" % json.dumps(
                    block.get("content", ""), default=str))
    else:
        return None
    body = " ".join(p for p in parts if p).strip()
    if not body:
        return None
    return "%s: %s" % (role, body[:PER_RECORD_CHARS])


def transcript_tail(path, window=TRANSCRIPT_WINDOW):
    """The last `window` renderable records of a Claude Code transcript.

    BOUNDED ON PURPOSE. The window is what makes the fresh-session property
    testable: the child sees a slice we can hash and log, not 'the session'.
    An unreadable or absent transcript yields nothing — the packet degrades to
    the trigger and the guard's own message, which still beats no triage.
    """
    if not path or not os.path.exists(path):
        return []
    lines = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                rendered = _render(record)
                if rendered:
                    lines.append(rendered)
    except OSError:
        return []
    return lines[-window:]


def build_packet(trigger, reason, transcript_path):
    """Header + as much recent tail as fits + the four-section ASK.

    THE ASK IS RESERVED BEFORE THE TAIL IS FITTED, and the tail is filled
    newest-first so the OLDEST records are the ones dropped.

    Scar (PR #75 round 1, Codex minor): this was header + tail + ASK joined and
    then sliced [:PACKET_CHAR_CAP]. A full window is TRANSCRIPT_WINDOW x
    PER_RECORD_CHARS = 25 x 600 = 15000 against a 12000 cap, so on any busy
    session the slice cut the ASK off entirely -- Fable was handed a transcript
    and never asked a question -- and what it did cut from the tail was the
    NEWEST end, which is the part describing the loop. Truncating from the end
    is backwards for both halves of the packet at once.
    """
    # Capped HERE, not only by the caller. token-guard trims the reason to 500,
    # but the CLI path (Tier B/C, a human typing --reason) has no such limit,
    # and an over-long one would push the total past the cap and put the ASK
    # back within reach of a truncation.
    header = [
        "TRIGGER: %s" % str(trigger)[:200],
        "WHAT THE GUARD SAID: %s" % ((reason or "(none)")[:REASON_CHARS]),
        "",
    ]
    label = "RECENT SESSION TAIL (%d of %d records, oldest first):"
    fixed = len("\n".join(header)) + len(ASK) + len(label % (99, 99)) + 8
    budget = max(0, PACKET_CHAR_CAP - fixed)

    tail = transcript_tail(transcript_path)
    kept = []
    for line in reversed(tail):
        if len(line) + 1 > budget:
            break
        budget -= len(line) + 1
        kept.append(line)
    kept.reverse()

    body = [label % (len(kept), len(tail))]
    body.extend(kept or ["(transcript unavailable)"])
    return "\n".join(header + body + ["", ASK])


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------

def call_fable(packet, timeout):
    """(triage, failure). Never raises, never hangs, never leaks a child.

    start_new_session + killpg, NOT subprocess.run(timeout=...). A plain run()
    kills only the direct child; a grandchild still holding the inherited stdout
    pipe keeps communicate() blocked long after the timeout fired, which is the
    exact hang this branch exists to make impossible. Scar: the same shape cost
    a full debugging session on a captured `claude -p` call earlier in this repo.
    """
    command = os.environ.get("KIPI_FABLE_CLAUDE_CMD")

    # --- fixture-run chokepoint -------------------------------------------
    # A suite must never spend a real model call. MEASURED, not assumed: adding
    # this branch turned the pre-existing tests/test_token_guard.py from 0.7s
    # into 60.9s with 6 failures, because six of its cases drive the volume
    # ceiling and every one of them started billing Fable. Per-suite stubbing
    # would have fixed those six and left the next ceiling test someone writes
    # on the live path — the same three holes as the slack-notify scar
    # (2026-08-01): only branches that carry the stub, only tests someone
    # remembered, only at write time.
    #
    # PYTEST_CURRENT_TEST is set by pytest for the duration of every test and is
    # inherited by subprocesses; nothing in production sets it. That asymmetry
    # is total in both directions, which is what makes it safe to refuse on.
    # An explicit KIPI_FABLE_CLAUDE_CMD overrides it, because a suite that
    # points at its own stub has already opted out of the live path.
    if not command and os.environ.get("PYTEST_CURRENT_TEST"):
        return None, "fixture run: refused to spend a real Fable call"

    command = command or shutil.which("claude")
    if not command or not os.path.exists(command):
        return None, "claude binary not found"

    env = dict(os.environ)
    # RECURSION GUARD. The child is itself a `claude` process, so without this
    # its own token-guard could hit a stuck block and escalate again, and each
    # escalation would fork another. One marker closes the whole tree.
    env["KIPI_FABLE_ESCALATION"] = "0"
    env.pop("KIPI_FABLE_CLAUDE_CMD", None)

    # Run OUTSIDE the project. A `claude -p` started in the repo loads the
    # repo's CLAUDE.md, rules and hooks — neither fresh nor free, and it would
    # make "the child saw only the packet" untrue.
    workdir = os.environ.get("TMPDIR") or "/tmp"

    started = time.time()
    try:
        proc = subprocess.Popen(
            [command, "-p", "--model", FABLE_MODEL],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, cwd=workdir,
            start_new_session=True)
    except OSError as exc:
        return None, "spawn failed: %s" % exc

    try:
        out, err = proc.communicate(input=packet, timeout=timeout)
    except subprocess.TimeoutExpired:
        _killpg(proc)
        return None, "timeout after %ss" % timeout
    except OSError as exc:
        _killpg(proc)
        return None, "io error: %s" % exc

    if proc.returncode != 0:
        return None, "exit %s: %s" % (proc.returncode, (err or "").strip()[:200])
    triage = (out or "").strip()
    if not triage:
        return None, "empty response after %.1fs" % (time.time() - started)
    return triage, None


def _killpg(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


# --------------------------------------------------------------------------
# ledger (single writer)
# --------------------------------------------------------------------------

def log_row(row):
    """Append one row under an exclusive lock.

    Single-writer chokepoint: two actors in one session (an orchestrator and a
    subagent) can escalate in the same second, and a bare append is only atomic
    below the pipe buffer. A packet hash plus a triage body clears it easily.
    """
    directory = os.environ.get("KIPI_FABLE_LEDGER_DIR") or DEFAULT_LEDGER_DIR
    path = os.path.join(
        directory, "escalations-%s.jsonl" % time.strftime("%Y-%m-%d"))
    try:
        os.makedirs(directory, exist_ok=True)
        import fcntl
        with open(path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass  # an unwritable ledger must never cost the caller its block


def notify_channel_configured():
    """True when a page could actually leave this machine.

    slack-notify.sh resolves its webhook from $KIPI_SLACK_WEBHOOK then
    ~/.config/kipi/slack-webhook, and its own header states: "No webhook
    configured -> silent no-op (exit 0), so callers never break." So its exit
    code cannot distinguish a delivered message from a swallowed one; the
    webhook has to be checked separately or delivery is unknowable.

    An explicit KIPI_FABLE_NOTIFY_CMD means the caller supplied its own
    notifier and owns its delivery semantics, so its channel is not ours to
    judge.
    """
    if os.environ.get("KIPI_FABLE_NOTIFY_CMD"):
        return True
    if (os.environ.get("KIPI_SLACK_WEBHOOK") or "").strip():
        return True
    path = os.path.join(os.path.expanduser("~"), ".config", "kipi",
                        "slack-webhook")
    try:
        with open(path, encoding="utf-8") as fh:
            return bool(fh.read().strip())
    except OSError:
        return False


def notify_send(message, notify=None, timeout=20):
    """Run the notifier and report what is KNOWN about delivery. Never raises.

    The one Python reader of slack-notify.sh's outcome. Both callers that need a
    delivery verdict go through it -- `notify_cap` below and `send_ping` in
    launchd-health-check.py -- for the same reason `notify_channel_configured`
    is borrowed rather than re-derived: a safety property re-implemented at each
    call site is not a chokepoint, and the copies drift exactly where they
    disagree.

    Scar (PR #134 review round 5, reproduced 2026-08-09 before the fix): both
    callers computed `delivered = rc == 0 and channel_configured`. slack-notify.sh
    exits 0 unconditionally, including after a curl that never reached Slack, so
    with a webhook pointing at a refused port BOTH recorded a delivered page that
    never left the machine. The watchdog then committed the run and stayed silent
    for the next 13 scheduled runs. A configured channel says a page COULD leave;
    it says nothing about whether this one did.

    So the verdict is read from the notifier itself (KIPI_NOTIFY_VERDICT_FILE),
    which is the only place the POST outcome exists.

    Returns: {attempted, exit, delivered, channel_configured, verdict, note}.

    HONEST BOUNDARY, unchanged from before: `delivered` means Slack accepted the
    POST, not that a human read it. Three ways it answers False for a page that
    might still be fine, all of which cost a duplicate ping and never a missed
    one -- an older slack-notify.sh that writes no verdict file, an unwritable
    verdict path, and a notifier that dies before it can report. A custom
    KIPI_FABLE_NOTIFY_CMD owns its own delivery semantics, so it is judged by its
    exit code as before; only the default notifier is held to the verdict.
    """
    notify = notify or os.environ.get("KIPI_FABLE_NOTIFY_CMD") or DEFAULT_NOTIFY
    # The verdict protocol is a property of the SCRIPT being run, not of who asked
    # for it, so this is keyed on the resolved path. A caller that points
    # KIPI_FABLE_NOTIFY_CMD at the real notifier gets the real verdict; anything
    # else is a notifier this fleet did not write and cannot make claims about.
    own_verdict = os.path.realpath(notify) == os.path.realpath(DEFAULT_NOTIFY)
    configured = notify_channel_configured()
    record = {"attempted": False, "exit": None, "delivered": False,
              "channel_configured": configured, "verdict": None, "note": None}

    if not os.path.exists(notify):
        record["note"] = "notifier not found at %s" % notify
        return record

    env = dict(os.environ)
    verdict_path = None
    if own_verdict:
        fd, verdict_path = tempfile.mkstemp(prefix="kipi-notify-verdict-")
        os.close(fd)
        os.unlink(verdict_path)  # absent until the notifier affirmatively writes
        env["KIPI_NOTIFY_VERDICT_FILE"] = verdict_path

    try:
        proc = subprocess.run(["bash", notify, message], timeout=timeout,
                              capture_output=True, text=True, env=env)
    except (subprocess.SubprocessError, OSError) as exc:
        record["note"] = "notifier failed to run: %s" % exc
        return record
    finally:
        if verdict_path and os.path.exists(verdict_path):
            try:
                record["verdict"] = (
                    open(verdict_path, encoding="utf-8").read().strip())
            except OSError:
                pass
            try:
                os.unlink(verdict_path)
            except OSError:
                pass

    record["attempted"] = True
    record["exit"] = proc.returncode

    if not own_verdict:
        # The caller supplied the notifier and owns its semantics.
        record["delivered"] = bool(proc.returncode == 0 and configured)
    else:
        record["delivered"] = record["verdict"] == "delivered"

    if not record["delivered"]:
        record["note"] = ("exit %s, verdict %s, channel_configured=%s"
                          % (proc.returncode, record["verdict"] or "none",
                             configured))
    return record


def notify_cap(trigger, count):
    """Page the founder once when cross-model triage did not unstick the run.

    Returns a record of what is KNOWN, never a bare claim of success.

    Scar (PR #75 round 1, Codex major): this returned True whenever the notifier
    process merely STARTED, and the caller wrote that straight into the ledger
    as `notified` AND used it to suppress every later page. With no webhook
    configured slack-notify.sh sends nothing and exits 0, so the row asserted a
    page that never happened and then guaranteed no further attempt would be
    made -- the founder was never reached at all, and the record said otherwise.
    Same class as rca-specification-reported-as-state-2026-08-02: a receipt for
    an action that did not occur.

    The one-arg legacy form on purpose: main's slack-notify.sh takes the message
    as $1, and the ASK-294 decision gate (unmerged at time of writing) keeps
    that caller working through its fail-open-loudly branch. Passing --kind to
    the version on main would make the flag the message body.
    """
    message = ("agent stuck after %d Fable escalations (last trigger: %s). "
               "Cross-model triage did not unstick it; a human call is next."
               % (count, trigger))
    # The verdict is READ from the notifier, not inferred from its exit code.
    # `notify_send` carries the scar; this function only renames its keys into
    # the ledger's `notify_*` namespace, which is already written to disk.
    sent = notify_send(message)
    return {"notify_attempted": sent["attempted"],
            "notify_exit": sent["exit"],
            "notify_delivered": sent["delivered"],
            "notify_channel_configured": sent["channel_configured"],
            "notify_verdict": sent["verdict"],
            "notify_note": sent["note"]}


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def write_pending(path, trigger, triage):
    """Hand the triage back to the guard, atomically.

    tmp + rename in the SAME directory, so a hook reading concurrently sees
    either no file or the whole file. A plain open("w") would expose a window
    where the reader gets half a JSON object and silently discards the triage
    (json.load raises, the guard's except returns None) -- a loss that looks
    exactly like "the model had nothing to say".
    """
    if not path:
        return
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"trigger": trigger, "triage": triage, "ts": _now()}, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def escalate(trigger, reason, transcript_path, count, capped_notified,
             pending_file=""):
    result = {"triage": None, "escalated": False, "capped": False,
              "notified": False, "delivered": False, "failure": None}

    cap = _int_env("KIPI_FABLE_CAP", DEFAULT_CAP)
    if count >= cap:
        result["capped"] = True
        result["failure"] = "cap reached (%d)" % cap
        row = {"ts": _now(), "trigger": trigger, "capped": True,
               "fable_ok": False, "failure": result["failure"],
               "call_timeout_s": 0, "next_path_taken": None}
        if not capped_notified:
            record = notify_cap(trigger, count)
            row.update(record)
            # `notified` now means ATTEMPTED, and delivery is its own field.
            # Collapsing the two is what made the old row a false receipt.
            result["notified"] = record["notify_attempted"]
            result["delivered"] = record["notify_delivered"]
        else:
            configured = notify_channel_configured()
            row.update({"notify_attempted": False, "notify_exit": None,
                        "notify_delivered": False,
                        "notify_channel_configured": configured,
                        "notify_note": "already paged for this episode"})
        log_row(row)
        return result

    packet = build_packet(trigger, reason, transcript_path)
    started = time.time()
    triage, failure = call_fable(packet, _int_env("KIPI_FABLE_TIMEOUT",
                                                  DEFAULT_TIMEOUT))
    duration = round(time.time() - started, 2)

    log_row({
        "ts": _now(),
        "trigger": trigger,
        "reason": (reason or "")[:300],
        "packet_sha256": hashlib.sha256(packet.encode()).hexdigest(),
        "packet_bytes": len(packet.encode()),
        "fable_ok": triage is not None,
        "failure": failure,
        "duration_s": duration,
        "diagnosis": (triage or "")[:1500],
        # Filled by nothing today. A field with no writer is a lie, so it is
        # recorded as unknown rather than as a claim about what Opus did next.
        "next_path_taken": None,
        "capped": False,
    })
    result["triage"] = triage
    result["escalated"] = triage is not None
    result["failure"] = failure
    if triage:
        write_pending(pending_file, trigger, triage)
    return result


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def report():
    """Print every escalation on record, newest file last.

    The ledger's reader. A JSONL file with a producer and no consumer is an
    artifact nobody checks, and this one carries the only evidence that the
    escalation fired at all, what it cost, and whether the model answered.
    """
    directory = os.environ.get("KIPI_FABLE_LEDGER_DIR") or DEFAULT_LEDGER_DIR
    if not os.path.isdir(directory):
        print("no escalations recorded (%s)" % directory)
        return
    total = 0
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        for line in open(os.path.join(directory, name), encoding="utf-8"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            total += 1
            status = "ok" if row.get("fable_ok") else (
                row.get("failure") or "failed")
            print("%s  %-16s %-6.6ss  %s" % (
                row.get("ts", "?"), row.get("trigger", "?"),
                str(row.get("duration_s", "")), status))
            first = (row.get("diagnosis") or "").splitlines()
            if first:
                print("    %s" % first[0][:110])
            # The cap row is the one a human needs to trust, so it never prints
            # a bare "notified". It prints whether the page could have LEFT the
            # machine, and why not when it could not.
            if row.get("capped"):
                print("    page: attempted=%s exit=%s channel=%s delivered=%s%s"
                      % (row.get("notify_attempted"), row.get("notify_exit"),
                         row.get("notify_channel_configured"),
                         row.get("notify_delivered"),
                         " (%s)" % row["notify_note"]
                         if row.get("notify_note") else ""))
    print("%d escalation(s) in %s" % (total, directory))


def main():
    if "--report" in sys.argv[1:]:
        report()
        sys.exit(0)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--transcript", default="")
    parser.add_argument("--count", type=int, default=0,
                        help="escalations already spent by this actor")
    parser.add_argument("--capped-notified", action="store_true")
    parser.add_argument("--pending-file", default="",
                        help="where to drop the triage for the guard to collect")
    parser.add_argument("--json", action="store_true",
                        help="machine output (the token-guard contract)")
    args = parser.parse_args()

    if os.environ.get("KIPI_FABLE_ESCALATION") == "0":
        out = {"triage": None, "escalated": False, "capped": False,
               "notified": False, "delivered": False, "failure": "disabled"}
    else:
        out = escalate(args.trigger, args.reason, args.transcript,
                       args.count, args.capped_notified, args.pending_file)

    if args.json:
        print(json.dumps(out))
    else:
        print(out["triage"] or ("no triage: %s" % out["failure"]))
    sys.exit(0)


if __name__ == "__main__":
    main()
