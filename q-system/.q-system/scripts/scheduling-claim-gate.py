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

THREE CHECKS
  1. CLAIM WITHOUT A CHECK. The answer makes a scheduling/armed claim and
     `will-it-run.py` appears nowhere in this session's TOOL activity -> exit 2.
  2. CLAIM CONTRADICTING THE CHECK. The instrument ran, printed a verdict for an
     issue, and the answer makes a POSITIVE claim about that same issue anyway
     -> exit 2. Running a checker and then ignoring its answer is the failure
     mode a run-happened check alone cannot see.
  3. CLAIM ABOUT AN ISSUE THE CHECK NEVER COVERED. The instrument answered, but
     about a DIFFERENT issue than the one the answer names -> exit 2. Evidence
     is per-issue, because the verdict is: ASK-287 being dispatchable today says
     nothing whatever about ASK-291 (round 2, major 1).

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
     CAPTURED as sp-b852db3e, not dropped -- it needs a did-it-run checker
     before a gate can demand anything answerable.  # spillover-skip
  d. Whether the claim is TRUE. Check two only catches a contradiction with a
     verdict actually printed this session for an issue named in the answer.
  e. Claims about schedulers `will-it-run.py` does not model (the morning
     pipeline, GitHub Actions, cloud routines) are still DISPATCH-class, so the
     remedy names a checker that cannot answer them. Narrowed but not closed:
     wiring claims now route to a wiring surface instead (major 1), and the
     dispatch remedy is at least runnable, but a morning-pipeline claim still
     gets pointed at the Linear dispatch job.
  g. Wiring evidence is a SURFACE TOUCH, not a verdict. Reading the real hook
     registration satisfies a "wired" claim even if that file says the OPPOSITE
     of the claim; only the dispatch class has a machine verdict to contradict.
  h. A dispatch claim naming NO issue ("the loop picks it up on the next run")
     is still armed by any real answer, because the header it prints (lane, cap,
     spend, budget day) genuinely is a lane-wide fact and there is no subject to
     attribute the claim to. Check three needs a named issue to bite.
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

# TWO CLASSES, BECAUSE THEY NEED DIFFERENT EVIDENCE AND DIFFERENT REMEDIES
# (codex round 1, major 1). Every shape used to demand a `will-it-run.py` run --
# including "the Stop hook is wired in settings.json", which is a sentence a
# /wiring-check WIRING REPORT is supposed to contain and which was verified by
# reading the file. The instrument models one launchd job and says nothing about
# hooks, so the remedy printed next to that block could not answer it. The only
# exits were an irrelevant command, an {{UNVERIFIED}} label on a VERIFIED
# statement, or the whole-answer skip marker -- which switches off the true
# positives too. A gate whose remedy cannot be followed trains its own bypass,
# so each class now asks for evidence its own remedy can actually produce.
DISPATCH_SHAPES = [
    ("picked-up", r"\b(will be|gets?|going to be) picked up\b|\bpicks? (it|this|that|them) up\b"),
    ("queued", r"\b(is|are|it'?s|now) queued\b|\bqueued (for|up)\b|\bin the queue\b"),
    ("next-run", r"\bnext (run|tick|heartbeat|dispatch|cycle|sweep|pass)\b|\bon the next\b"),
    ("dispatched", r"\b(will be|gets?|going to be) dispatched\b|\bwill dispatch\b"),
    ("actor-will", r"\bthe \w+ (will|should) (run|fire|pick|dispatch|trigger|catch|block|start)\b"),
    ("will-run", r"\bwill run\b|\bwill fire\b|\bwill trigger\b|\bwill kick off\b|\bruns (tonight|today|tomorrow|overnight|next)\b"),
    ("scheduled", r"\bscheduled to\b|\bset to (run|fire|go)\b|\bslated to\b"),
]
WIRING_SHAPES = [
    ("armed", r"\b(is|now|it'?s) armed\b|\barmed and\b"),
    ("wired", r"\b(is|now|it'?s|fully) wired\b|\bwired (up|in)\b"),
    ("live", r"\b(is|now|it'?s|goes?) live\b|\bgone live\b"),
    ("enforced", r"\b(is|now) (enforced|enforcing|active|in effect)\b"),
]
COMPILED = [(n, re.compile(p, re.I), "dispatch") for n, p in DISPATCH_SHAPES] + \
           [(n, re.compile(p, re.I), "wiring") for n, p in WIRING_SHAPES]

# A wiring claim is answerable by having actually TOUCHED a wiring surface this
# session. Reading the settings file IS the check for "is it wired", the way a
# will-it-run answer is the check for "will it dispatch".
#
# EVIDENCE IS THE FILE'S BODY, NOT ITS NAME (round 2, major 2). The old check was
# `"settings.json" in tool_blob`, so an `ls`, a grep PATTERN, or a Read of any
# source file that merely mentions the filename armed every wiring claim for the
# rest of the session -- including a Read of THIS file, whose own remedy text
# names all six surfaces. That is the identical substitution round 1 major 2
# found on the dispatch side: presence of the name accepted as proof of the act.
# So the signature is the registration itself -- a hook block, or a workflow's
# job body -- which only appears when the surface was actually opened or written.
WIRING_BODY_RE = re.compile(
    r'"(PreToolUse|PostToolUse|Stop|SubagentStop|SessionStart|SessionEnd|'
    r'UserPromptSubmit|PreCompact|PostCompact|Notification)"\s*:\s*\['
    r'|"hooks"\s*:\s*[\[{]'
    r'|"type"\s*:\s*"command"'
    r'|"capabilities"\s*:\s*\['
    r'|^\s*(?:jobs|runs-on|uses)\s*:',
    re.M)

# PROOF THE INSTRUMENT RAN AND ANSWERED, not that its NAME appeared (major 2).
# The old check was `CHECKER in tool_blob`, so `ls` of the scripts directory, a
# Read of the file, or a run that exited 3 saying "No scheduling claim is
# supported by this run" all disarmed the gate for the whole session. That is
# artifact-presence accepted as proof of behaviour -- the exact substitution the
# RCA this file cites is about, committed by the gate built to stop it. These
# match will-it-run.py's real OUTPUT: a rendered header with a live timestamp,
# or the --json body (minor 1). A refusal prints neither, so it cannot arm.
ANSWER_HEADER_RE = re.compile(
    r"^OBSERVED \d{4}-\d\d-\d\dT[\d:]+\s+lane=\S+\s+cap=", re.M)
JSON_ANSWER_RE = re.compile(r'"observed_at"\s*:\s*"\d{4}-|"answers"\s*:\s*\[')
JSON_VERDICT_RE = re.compile(r'\{[^{}]*?"issue":\s*"(ASK-\d+)"[^{}]*?\}', re.S)

# An answer that RESTATES a negative verdict is the correct report, not a
# contradiction (major 4). DELIBERATE DECISION, not an accident: the gate keys on
# the verdict WORD, so "ASK-287 is not today, it lands 2026-08-03" passes while
# "ASK-287 is queued for tomorrow" blocks even though both describe 2026-08-03.
# Reporting the instrument's own verdict token is what the gate is for; a
# paraphrase that drops it is how "not today" became "queued" in the first place.
NEGATIVE_ECHO = re.compile(
    r"\b(never|not today|blocked|unknown|will not|won'?t|cannot|can'?t|"
    r"no slot|nothing dispatch\w*|budget[^.]{0,15}spent)\b", re.I)
ACTOR_RE = re.compile(ACTOR, re.I)
ISSUE_RE = re.compile(r"\bASK-\d+\b")
# will-it-run.py's own answer lines: "ASK-291: NEVER" / "ASK-287: NOT TODAY".
VERDICT_RE = re.compile(
    r"^\s*(ASK-\d+):\s*(NEVER|UNKNOWN|NOT TODAY|TODAY|BLOCKED)", re.M | re.I)
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
    """[(shape_name, sentence, class)] for every unexcused claim."""
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
            for name, rx, kind in COMPILED:
                if rx.search(sentence):
                    hits.append((name, sentence.strip(), kind))
                    break
    return hits


def checker_answered(tool_blob):
    """True only when will-it-run.py actually RAN and PRODUCED an answer."""
    blob = tool_blob or ""
    return bool(ANSWER_HEADER_RE.search(blob) or JSON_ANSWER_RE.search(blob))


def wiring_evidence(tool_blob):
    """True when a wiring surface's BODY was actually seen this session."""
    return bool(WIRING_BODY_RE.search(tool_blob or ""))


def unbacked_issue_claims(claims, verdicts):
    """Dispatch claims naming an issue the instrument never answered for.

    The gate's whole premise is that a scheduling claim is only as good as the
    observation behind it, and the observation is PER ISSUE: pickability, pool
    position and project all differ issue by issue, which is exactly why one run
    printed TODAY for ASK-287 and NEVER for ASK-291 on the same day. Treating a
    single successful run as session-wide arming let the one answer license every
    other claim -- a run-happened check wearing a per-issue check's clothes.

    A NEGATIVE_ECHO sentence is NOT excused here (it is, in contradictions()).
    That exemption exists so an accurate RESTATEMENT of a printed verdict passes;
    with no verdict for that issue there is nothing being restated, and "ASK-291
    will never be dispatched" is then just as unobserved as the positive form.
    """
    out = []
    for name, sentence, _kind in claims:
        idents = [i.upper() for i in ISSUE_RE.findall(sentence)]
        if idents and not any(i in verdicts for i in idents):
            out.append((name, sentence, idents))
    return out


def observed_verdicts(tool_blob):
    """{ASK-N: VERDICT} for every verdict the instrument printed this session.

    Both renderings: the human table and --json (minor 1). A contradiction check
    blind to --json would silently pass whenever the tool was run the machine way.
    """
    blob = tool_blob or ""
    out = {m.group(1).upper(): m.group(2).upper() for m in VERDICT_RE.finditer(blob)}
    for m in JSON_VERDICT_RE.finditer(blob):
        vm = re.search(r'"verdict":\s*"([^"]+)"', m.group(0))
        if vm:
            out.setdefault(m.group(1).upper(), vm.group(1).upper())
    return out


def contradictions(final_text, claims, verdicts):
    """Positive claims about an issue the instrument said would NOT happen."""
    if not claims or not verdicts:
        return []
    out = []
    for _name, sentence, _kind in claims:
        # An ACCURATE restatement is the outcome this gate wants, not a
        # contradiction (major 4). Blocking "ASK-291 will never be dispatched"
        # for contradicting a NEVER verdict punished the correct report and left
        # no way to state a negative result at all.
        if NEGATIVE_ECHO.search(sentence):
            continue
        for ident in ISSUE_RE.findall(sentence):
            v = verdicts.get(ident.upper())
            if v in ("NEVER", "NOT TODAY", "BLOCKED", "UNKNOWN"):
                out.append((ident.upper(), v, sentence))
    # A claim naming no issue can still contradict a lone NEVER verdict, but
    # attributing it would be a guess, so it is deliberately not reported here.
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
    # ROUTED BY CLASS so the remedy is one the author can actually carry out.
    dispatch = [c for c in claims if c[2] == "dispatch"]
    wiring = [c for c in claims if c[2] == "wiring"]
    scar = ("Nine claims of this shape were false in one session (RCA "
            "rca-specification-reported-as-state-2026-08-02). Every one substituted "
            "what the code is DESIGNED to do for what the running system IS doing, "
            "and each was refuted by one command available the whole time.\n"
            "Not such a claim, or deliberately unverified? Label the line "
            "{{UNVERIFIED}}, or add '" + SKIP_MARKER + "' to the answer.\n")
    if dispatch and not checker_answered(tool_blob):
        listed = "\n".join(f"  [{n}] \"{t[:150]}\"" for n, t, _ in dispatch[:8])
        return 2, (
            "SCHEDULING CLAIM GATE (blocked): your answer says work is scheduled, "
            "queued or about to run, and " + CHECKER + " produced no answer this "
            "session:\n" + listed + "\n\n"
            "Run it, then report what it said:\n"
            "  python3 q-system/.q-system/scripts/" + CHECKER + " <ASK-N>\n"
            "  python3 q-system/.q-system/scripts/" + CHECKER + " --all\n\n"
            "The NAME appearing in a command is not enough, deliberately: a run "
            "that refused to answer proves nothing, and neither does an `ls`.\n"
            + scar)
    # CHECK THREE: it answered, but about a different issue (round 2, major 1).
    unbacked = unbacked_issue_claims(dispatch, verdicts)
    if unbacked:
        missing = sorted({i for _n, _s, ids in unbacked for i in ids
                          if i not in verdicts})
        listed = "\n".join(f"  [{n}] \"{t[:150]}\"" for n, t, _ in unbacked[:8])
        return 2, (
            "SCHEDULING CLAIM GATE (blocked): " + CHECKER + " answered this "
            "session, but not about " + ", ".join(missing) + ":\n" + listed +
            "\n\nIt printed a verdict for: " +
            (", ".join(sorted(verdicts)) or "no issue at all") + ".\n"
            "Evidence is per-issue. Pickability, pool position and project "
            "differ issue by issue -- one 2026-08-02 run printed TODAY for one "
            "issue and NEVER for another. Run it for the issue you are "
            "claiming:\n"
            "  python3 q-system/.q-system/scripts/" + CHECKER + " " +
            missing[0] + "\n" + scar)
    if wiring and not wiring_evidence(tool_blob):
        listed = "\n".join(f"  [{n}] \"{t[:150]}\"" for n, t, _ in wiring[:8])
        return 2, (
            "SCHEDULING CLAIM GATE (blocked): your answer says something is armed, "
            "wired, live or enforced, and no wiring surface was opened this "
            "session:\n" + listed + "\n\n"
            "Open the surface that actually decides it, then say what it showed:\n"
            "  .claude/settings.json / settings-template.json / a plugin hooks.json\n"
            "  or run the hook and report its exit code.\n\n"
            "Text in a repo file is not wiring: the runtime may load a different "
            "copy (wiring-check.md, load-path proof).\n" + scar)
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
    # A REAL will-it-run answer, which is what now counts as evidence.
    RAN = ("$ python3 q-system/.q-system/scripts/will-it-run.py ASK-287\n"
           "OBSERVED 2026-08-02T11:32:16  lane=production  cap=3  spent=3  "
           "budget_day=2026-08-02\nASK-287: TODAY")
    # Wiring evidence is now the SURFACE'S BODY, not its name (round 2, major 2).
    # ASSEMBLED, never written contiguously: a literal hook-registration blob
    # sitting in this file would mean that merely READING this gate's source arms
    # every wiring claim for the session -- the same name-is-not-proof hole the
    # finding reports, reintroduced by its own test fixture. `_body` keeps the
    # signature out of the source text while still producing it at runtime.
    def _body(*parts):
        return "".join(parts)

    REAL_SETTINGS = _body('read .claude/settings.json\n{"hoo', 'ks": {"St',
                          'op": [{"ty', 'pe": "comm', 'and", "command": '
                          '"scheduling-claim-gate.py"}]}}')
    REAL_HOOKS_JSON = _body('{"hoo', 'ks": {"PostToolU', 'se": [{"matcher": '
                            '"Write|Edit", "command": "voice-lint.py"}]}}')
    REAL_WORKFLOW = _body('cat .github/workflows/ci.yml\njo', 'bs:\n  check:\n'
                          '    runs-on: ubuntu-latest')
    WIRED_EV = REAL_SETTINGS

    # --- check one: dispatch claim without a real run ------------------------
    check("queued claim with no checker run blocks",
          evaluate("ASK-291 is queued, it'll go out today.", NO_TOOLS)[0], 2)
    # RAN answers about ASK-287, so ASK-287 is the claim it can back. The same
    # sentence about ASK-291 is check three's case below, not this one.
    check("same claim passes once the checker actually answered",
          evaluate("ASK-287 is queued, it'll go out today.", RAN)[0], 0)
    check("next-run claim blocks",
          evaluate("The loop will grab it on the next run.", NO_TOOLS)[0], 2)
    check("will-dispatch claim blocks",
          evaluate("It gets dispatched tonight by the worker.", NO_TOOLS)[0], 2)

    # --- major 2 (codex): the NAME is not proof of a RUN ---------------------
    check("MAJOR2: an `ls` listing the filename does NOT arm the gate",
          evaluate("ASK-291 is queued.",
                   "capability-gate.py\nwill-it-run.py\nlinear_pick.py")[0], 2)
    check("MAJOR2: a Read of the file does NOT arm the gate",
          evaluate("ASK-291 is queued.",
                   '{"file_path": "q-system/.q-system/scripts/will-it-run.py"}')[0], 2)
    check("MAJOR2: a run that REFUSED to answer does NOT arm the gate",
          evaluate("ASK-291 is queued.",
                   "python3 will-it-run.py ASK-291\nCANNOT ANSWER: Linear query "
                   "failed (HTTP 401). No scheduling claim is supported by this "
                   "run.")[0], 2)
    check("MAJOR2: a real rendered answer DOES arm it",
          evaluate("ASK-287 is queued for today.", RAN)[0], 0)
    # Pin WHICH check fired. Since check three also blocks an issue the run never
    # covered, an rc of 2 alone would no longer prove check one is still alive.
    check("MAJOR2: the block is check ONE (no answer), not check three",
          "produced no answer this session" in evaluate(
              "ASK-291 is queued.",
              "capability-gate.py\nwill-it-run.py\nlinear_pick.py")[1], True)

    # --- minor 1 (codex): --json output must count and be readable -----------
    JSON_OUT = ('{"observed_at": "2026-08-02T11:32:16", "cap": 3, "answers": '
                '[{"issue": "ASK-291", "verdict": "NEVER", "position": null},'
                ' {"issue": "ASK-287", "verdict": "TODAY", "position": 1}]}')
    check("MINOR1: --json output arms the gate",
          evaluate("ASK-287 is queued for today.", JSON_OUT)[0], 0)
    check("MINOR1: --json verdicts are visible to the contradiction check",
          evaluate("ASK-291 is queued for today.", JSON_OUT)[0], 2)

    # --- major 1 (codex): wiring claims get a remedy they can follow ---------
    check("MAJOR1: a wiring claim with a surface opened passes",
          evaluate("The Stop hook is now wired in settings.json.", WIRED_EV)[0], 0)
    check("MAJOR1: a wiring claim with NO surface opened blocks",
          evaluate("The Stop hook is now wired.", NO_TOOLS)[0], 2)
    check("MAJOR1: a wiring claim does NOT demand a dispatch check",
          evaluate("The voice-lint hook is enforced on every Write.",
                   WIRED_EV)[0], 0)
    check("MAJOR1: the wiring block names a wiring surface, not the dispatcher",
          "settings.json" in evaluate("The hook is now wired.", NO_TOOLS)[1], True)

    # --- round 2, major 1: an answer for ONE issue is not an answer for ALL ---
    RAN_287 = RAN  # a real, rendered answer -- but only about ASK-287
    check("R2MAJOR1: a run for ASK-287 does NOT back a claim about ASK-291",
          evaluate("ASK-291 is queued, it goes out today.", RAN_287)[0], 2)
    check("R2MAJOR1: the block names the unanswered issue",
          "ASK-291" in evaluate("ASK-291 is queued.", RAN_287)[1], True)
    check("R2MAJOR1: the issue the checker DID answer still passes",
          evaluate("ASK-287 is queued for today.", RAN_287)[0], 0)
    check("R2MAJOR1: --json answers back only the issues they name",
          evaluate("ASK-999 is queued for today.", JSON_OUT)[0], 2)

    # --- round 2, major 2: a wiring FILENAME is not an opened wiring surface --
    check("R2MAJOR2: a grep pattern naming settings.json does NOT arm wiring",
          evaluate("The Stop hook is now wired.",
                   '{"pattern": "settings.json", "path": "."}')[0], 2)
    check("R2MAJOR2: an ls listing settings.json does NOT arm wiring",
          evaluate("The Stop hook is now wired.",
                   "settings.json\nsettings.local.json\nCLAUDE.md")[0], 2)
    check("R2MAJOR2: reading a SOURCE file that merely mentions the surface "
          "does NOT arm wiring",
          evaluate("The Stop hook is now wired.",
                   'WIRING_SURFACES = ("settings.json", "hooks.json")')[0], 2)
    check("R2MAJOR2: the real content of settings.json DOES arm wiring",
          evaluate("The Stop hook is now wired in settings.json.",
                   REAL_SETTINGS)[0], 0)
    check("R2MAJOR2: a plugin hooks.json body arms wiring",
          evaluate("The lint is now enforced on every Write.",
                   REAL_HOOKS_JSON)[0], 0)
    check("R2MAJOR2: a workflow body arms wiring",
          evaluate("The required check is now live.", REAL_WORKFLOW)[0], 0)

    # --- major 4 (codex): an accurate restatement is the desired report ------
    NEVER_OUT = (RAN + "\nASK-291: NEVER\n    project is UNSET"
                 "\nASK-285: NOT TODAY")
    check("MAJOR4: restating NEVER accurately is allowed",
          evaluate("ASK-291 is never going to be dispatched, its project is unset.",
                   NEVER_OUT)[0], 0)
    check("MAJOR4: restating NOT TODAY accurately is allowed",
          evaluate("ASK-285 is queued, but not today, it lands 2026-08-03.",
                   NEVER_OUT)[0], 0)
    check("MAJOR4: a positive claim against NOT TODAY still blocks",
          evaluate("ASK-285 is queued for today.", NEVER_OUT)[0], 2)
    check("MAJOR4: a POSITIVE claim against a NEVER verdict still blocks",
          evaluate("ASK-291 is queued and runs tonight.", NEVER_OUT)[0], 2)
    check("the block names the verdict the checker gave",
          "NEVER" in evaluate("ASK-291 is queued.", NEVER_OUT)[1], True)
    check("a claim about a DIFFERENT issue is not a contradiction",
          evaluate("ASK-287 is queued.", NEVER_OUT)[0], 0)

    # --- the false-positive class that would make this unshippable ----------
    check("'the landing page is live' does NOT block (no system actor)",
          evaluate("The landing page is live at ktlyst.com.", NO_TOOLS)[0], 0)
    check("'the deal is live' does NOT block",
          evaluate("The deal is live and Chris signed.", NO_TOOLS)[0], 0)
    check("plain conversational answer passes",
          evaluate("I read the file and it does what you said.", NO_TOOLS)[0], 0)
    check("past-tense observation is out of scope by design (sp-b852db3e)",  # spillover-skip
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

    # --- shape naming --------------------------------------------------------
    check("the blocked message names which shape fired",
          "[queued]" in evaluate("ASK-291 is queued.", NO_TOOLS)[1], True)
    check("find_claims reports the shape name and its class",
          [(n, k) for n, _, k in find_claims("The hook is armed.")],
          [("armed", "wiring")])

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
