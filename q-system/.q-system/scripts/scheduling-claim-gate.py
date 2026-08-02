#!/usr/bin/env python3
"""Stop-hook gate: refuse an answer that asserts scheduling or armed state when
the checker that could have verified it did not run this session.

WHY (ASK-292, RCA rca-specification-reported-as-state-2026-08-02). Nine claims to
the founder in one session were false, and all nine were the same shape: a
SPECIFICATION reported as an OBSERVATION. "The queue picks this up, 4 a day" (the
cap was 3 and the day's budget was spent). "The write path is closed" (merged,
wired nowhere). Per `skill-hook-pairing.md`'s own decision rule this is a
DETERMINISTIC claim class -- regex-detectable, its truth computable from state
files -- so it owes a hook, and had none. The fleet gates published content,
client numbers, handoff provenance and code claims. The surface the founder
actually reads was the only ungated one, which is why the errors accumulated
there.

The paired instrument is `will-it-run.py`. This gate does not judge the claim; it
requires that the instrument ran.

TWO CHECKS
  1. CLAIM WITHOUT A CHECK. The answer makes a scheduling/armed claim and
     `will-it-run.py` appears nowhere in this session's TOOL activity -> exit 2.
  2. CLAIM CONTRADICTING THE CHECK. The instrument ran, printed a verdict for an
     issue, and the answer makes a POSITIVE claim about that same issue anyway
     -> exit 2. Running a checker and then ignoring its answer is the failure
     mode a run-happened check alone cannot see.

Evidence for check one is read from tool_use inputs and tool_result contents ONLY,
never from my own prose. Otherwise writing the words "will-it-run.py" in the answer
would ground the answer in itself, which is the same self-certification the gate
exists to break.

HONEST BOUNDARY -- what this does NOT catch (feedback_hook_blind_spots: enumerate
coverage, do not assume a regex is complete):
  a. A claim carrying no trigger phrase. "That's handled." / "Covered." /
     "Taken care of." are semantically identical and match nothing.
  b. A claim whose SUBJECT sits in a previous sentence. Proximity to a system-actor
     token is required to keep "the landing page is live" from blocking a GTM
     instance, and that requirement is itself a miss source.
  c. Past-tense observation claims ("it ran", "it dispatched", "the review
     happened"). Different class, no instrument, deliberately out of scope.
  d. Whether the claim is TRUE. Check two only catches a contradiction with a
     verdict actually printed this session for an issue named in the answer.
  e. Claims about schedulers `will-it-run.py` does not model (the morning
     pipeline, GitHub Actions, cloud routines). The gate forces a check to run;
     it cannot force the right check.
  f. A log line quoted inline. Fenced code blocks are stripped; inline quotes
     are not.

Contract: {transcript_path, stop_hook_active} JSON on stdin. exit 0 = pass,
exit 2 = block (stderr fed back). Per-answer bypass: `scheduling-claim-skip`.
Per-line hatch: `{{UNVERIFIED}}` / `{{UNVALIDATED}}` on the claiming line -- an
inference LABELLED as one is the correct move, not a lesser one (evidence-ledger).
Self-test: `python3 scheduling-claim-gate.py --self-test`.
"""
import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "scheduling-claim-skip"
CHECKER = "will-it-run.py"
UNVERIFIED = ("{{UNVERIFIED}}", "{{UNVALIDATED}}", "{{NEEDS_PROOF}}")

# A claim only counts when a SYSTEM ACTOR is named in the same sentence. Without
# this, "the landing page is live" blocks a GTM instance -- a gate that cries wolf
# gets muted, and a muted gate is worse than none (founder-notifications.md).
ACTOR = (r"loop|dispatch\w*|worker|queue|job|cron|launchd|heartbeat|hook|gate|"
         r"guard|check\w*|lint|scanner|pipeline|routine|agent|runner|converge|"
         r"schedul\w*|ASK-\d+|sp-[0-9a-f]{6,}|PR ?#?\d+|issue")

# Each entry is (name, pattern). Named so a blocked turn can say WHICH shape fired
# and a future reader can audit coverage entry by entry rather than reading one
# 400-character alternation.
CLAIM_SHAPES = [
    ("picked-up", r"\b(will be|gets?|going to be) picked up\b|\bpicks? (it|this|that|them) up\b"),
    ("queued", r"\b(is|are|it'?s|now) queued\b|\bqueued (for|up)\b|\bin the queue\b"),
    ("next-run", r"\bnext (run|tick|heartbeat|dispatch|cycle|sweep|pass)\b|\bon the next\b"),
    ("dispatched", r"\b(will be|gets?|going to be) dispatched\b|\bwill dispatch\b"),
    ("actor-will", r"\bthe \w+ (will|should) (run|fire|pick|dispatch|trigger|catch|block|start)\b"),
    ("will-run", r"\bwill run\b|\bwill fire\b|\bwill trigger\b|\bwill kick off\b|\bruns (tonight|today|tomorrow|overnight|next)\b"),
    ("scheduled", r"\bscheduled to\b|\bset to (run|fire|go)\b|\bslated to\b"),
    ("armed", r"\b(is|now|it'?s) armed\b|\barmed and\b"),
    ("wired", r"\b(is|now|it'?s|fully) wired\b|\bwired (up|in)\b"),
    ("live", r"\b(is|now|it'?s|goes?) live\b|\bgone live\b"),
    ("enforced", r"\b(is|now) (enforced|enforcing|active|in effect)\b"),
]
COMPILED = [(n, re.compile(p, re.I)) for n, p in CLAIM_SHAPES]
ACTOR_RE = re.compile(ACTOR, re.I)
ISSUE_RE = re.compile(r"\bASK-\d+\b")
# will-it-run.py's own answer lines: "ASK-291: NEVER" / "ASK-287: NOT TODAY".
VERDICT_RE = re.compile(r"^\s*(ASK-\d+):\s*(NEVER|UNKNOWN|NOT TODAY|BLOCKED)", re.M | re.I)
FENCE_RE = re.compile(r"```.*?```", re.S)


def _load_records(transcript_path):
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _final_assistant_text(records):
    text = ""
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        parts = [i.get("text", "") for i in msg.get("content", [])
                 if isinstance(i, dict) and i.get("type") == "text"]
        if parts:
            text = "\n".join(parts)
    return text


def _tool_blob(records):
    """Tool inputs and tool results ONLY. Assistant prose is deliberately excluded:
    a claim must not be able to certify itself by naming the checker."""
    parts = []
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict):
            continue
        for item in msg.get("content", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use":
                parts.append(json.dumps(item.get("input", {})))
            elif item.get("type") == "tool_result":
                c = item.get("content", "")
                if isinstance(c, list):
                    parts.extend(s.get("text", "") for s in c if isinstance(s, dict))
                elif isinstance(c, str):
                    parts.append(c)
    return "\n".join(parts)


def find_claims(final_text):
    """[(shape_name, line)] for every unexcused scheduling/armed claim."""
    if not final_text or SKIP_MARKER in final_text:
        return []
    body = FENCE_RE.sub(" ", final_text)
    hits = []
    for line in body.splitlines():
        if any(m in line for m in UNVERIFIED):
            continue
        # Sentence-scoped so an actor three sentences away cannot license a claim.
        for sentence in re.split(r"(?<=[.!?;])\s+", line):
            if not ACTOR_RE.search(sentence):
                continue
            for name, rx in COMPILED:
                if rx.search(sentence):
                    hits.append((name, sentence.strip()))
                    break
    return hits


def checker_ran(tool_blob):
    return CHECKER in (tool_blob or "")


def observed_verdicts(tool_blob):
    """{ASK-N: VERDICT} for every verdict the instrument printed this session."""
    return {m.group(1).upper(): m.group(2).upper()
            for m in VERDICT_RE.finditer(tool_blob or "")}


def contradictions(final_text, claims, verdicts):
    """Positive claims about an issue the instrument said would NOT happen."""
    if not claims or not verdicts:
        return []
    body = FENCE_RE.sub(" ", final_text)
    out = []
    for _name, sentence in claims:
        for ident in ISSUE_RE.findall(sentence):
            v = verdicts.get(ident.upper())
            if v in ("NEVER", "NOT TODAY", "BLOCKED", "UNKNOWN"):
                out.append((ident.upper(), v, sentence))
    # A claim naming no issue can still contradict a lone NEVER verdict, but
    # attributing it would be a guess, so it is deliberately not reported here.
    del body
    return out


def evaluate(final_text, tool_blob):
    """(exit_code, message). Pure -- the whole decision, no I/O."""
    claims = find_claims(final_text)
    if not claims:
        return 0, ""
    verdicts = observed_verdicts(tool_blob)
    clash = contradictions(final_text, claims, verdicts)
    if clash:
        detail = "\n".join(
            f"  {ident}: the checker printed {v} this session, and you wrote:\n"
            f"      \"{s[:160]}\"" for ident, v, s in clash[:5])
        return 2, (
            "SCHEDULING CLAIM GATE (blocked): your answer contradicts the checker "
            "you ran.\n" + detail + "\n\n"
            "Report the verdict the instrument gave, not the one you expected. "
            "Scar 2026-08-02: an issue was described to the founder as queued when "
            "the day's budget was spent, so he believed a machine was going to act "
            "when no actor existed.\n")
    if not checker_ran(tool_blob):
        listed = "\n".join(f"  [{n}] \"{s[:150]}\"" for n, s in claims[:8])
        return 2, (
            "SCHEDULING CLAIM GATE (blocked): your answer asserts that something is "
            "scheduled, armed, wired or live, and " + CHECKER + " did not run this "
            "session:\n" + listed + "\n\n"
            "Run it, then answer with what it said:\n"
            "  python3 q-system/.q-system/scripts/" + CHECKER + " <ASK-N>\n"
            "  python3 q-system/.q-system/scripts/" + CHECKER + " --all\n\n"
            "Nine claims of this shape were false in one session (RCA "
            "rca-specification-reported-as-state-2026-08-02). Every one substituted "
            "what the code is DESIGNED to do for what the running system IS doing, "
            "and each was refuted by one command available the whole time.\n"
            "Not a scheduling claim, or deliberately unverified? Label the line "
            "{{UNVERIFIED}}, or add '" + SKIP_MARKER + "' to the answer.\n")
    return 0, ""


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    if payload.get("stop_hook_active"):
        sys.exit(0)
    records = _load_records(payload.get("transcript_path", ""))
    if not records:
        sys.exit(0)
    final_text = _final_assistant_text(records)
    code, message = evaluate(final_text, _tool_blob(records))
    if code:
        sys.stderr.write(message)
    sys.exit(code)


# prompt-only-enforcement-skip
# ^ the strings below are ASSERTIONS UNDER TEST -- sentences a model might say, fed
# to evaluate() to prove the gate fires. The blocker is this file's own exit 2.
def _self_test():
    cases = []

    def check(name, got, want):
        cases.append((name, got == want, got, want))

    NO_TOOLS = "some unrelated tool output"
    RAN = 'ran python3 q-system/.q-system/scripts/will-it-run.py ASK-291'

    # --- check one: claim without a check ------------------------------------
    check("queued claim with no checker run blocks",
          evaluate("ASK-291 is queued, it'll go out today.", NO_TOOLS)[0], 2)
    check("same claim passes once the checker ran",
          evaluate("ASK-291 is queued, it'll go out today.",
                   RAN + "\nASK-291: TODAY")[0], 0)
    check("armed claim about a hook blocks",
          evaluate("The write-path guard is armed.", NO_TOOLS)[0], 2)
    check("wired claim about a hook blocks",
          evaluate("The dispatch hook is now wired.", NO_TOOLS)[0], 2)
    check("next-run claim blocks",
          evaluate("The loop will grab it on the next run.", NO_TOOLS)[0], 2)
    check("will-dispatch claim blocks",
          evaluate("It gets dispatched tonight by the worker.", NO_TOOLS)[0], 2)

    # --- the false-positive class that would have made this unshippable ------
    check("'the landing page is live' does NOT block (no system actor)",
          evaluate("The landing page is live at ktlyst.com.", NO_TOOLS)[0], 0)
    check("'the deal is live' does NOT block",
          evaluate("The deal is live and Chris signed.", NO_TOOLS)[0], 0)
    check("plain conversational answer passes",
          evaluate("I read the file and it does what you said.", NO_TOOLS)[0], 0)
    check("past-tense observation is out of scope by design",
          evaluate("The loop dispatched ASK-289 at 17:57.", NO_TOOLS)[0], 0)

    # --- hatches -------------------------------------------------------------
    check("{{UNVERIFIED}} on the line excuses it",
          evaluate("The loop will pick it up {{UNVERIFIED}}", NO_TOOLS)[0], 0)
    check("skip marker excuses the whole answer",
          evaluate(f"The loop will pick it up. {SKIP_MARKER}", NO_TOOLS)[0], 0)
    check("a fenced code block is not a claim",
          evaluate("Here:\n```\nthe loop will run\n```\ndone.", NO_TOOLS)[0], 0)

    # --- self-certification must not work ------------------------------------
    check("naming the checker in PROSE does not count as running it",
          evaluate("I ran will-it-run.py. ASK-291 is queued.", NO_TOOLS)[0], 2)

    # --- check two: contradicting the checker --------------------------------
    NEVER_OUT = RAN + "\nASK-291: NEVER\n    project is UNSET"
    check("claiming queued when the checker said NEVER blocks",
          evaluate("ASK-291 is queued and runs tonight.", NEVER_OUT)[0], 2)
    check("the block names the verdict the checker gave",
          "NEVER" in evaluate("ASK-291 is queued.", NEVER_OUT)[1], True)
    check("a claim about a DIFFERENT issue is not a contradiction",
          evaluate("ASK-287 is queued.", NEVER_OUT + "\nASK-287: TODAY")[0], 0)

    # --- shape naming --------------------------------------------------------
    check("the blocked message names which shape fired",
          "[queued]" in evaluate("ASK-291 is queued.", NO_TOOLS)[1], True)
    check("find_claims reports the shape name",
          [n for n, _ in find_claims("The hook is armed.")], ["armed"])

    # --- NEGATIVE SELF-TEST: prove the harness can go red --------------------
    # A suite of 19 assertions that have never been seen to fail is
    # indistinguishable from 19 that cannot. This mutates the detector in memory,
    # asserts a previously-blocking case now passes (so the mutant really applied),
    # and restores it. If the harness were inert, `mutant_passes` would stay 2.
    global COMPILED
    saved = COMPILED
    COMPILED = []                                   # the mutant: detect nothing
    mutant_passes = evaluate("ASK-291 is queued.", NO_TOOLS)[0]
    COMPILED = saved
    restored_blocks = evaluate("ASK-291 is queued.", NO_TOOLS)[0]
    negative_ok = (mutant_passes == 0 and restored_blocks == 2)
    cases.append(("NEGATIVE: gutting the detector flips a blocking case to pass "
                  "(mutant applied AND observed)", negative_ok,
                  (mutant_passes, restored_blocks), (0, 2)))

    ok = True
    for name, passed, got, want in cases:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        if not passed:
            print(f"      got={got!r}\n      want={want!r}")
        ok = ok and passed
    print(f"\n{sum(1 for c in cases if c[1])}/{len(cases)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    main()
