#!/usr/bin/env python3
"""voice_refresh.py — Stage 2-3 orchestrator for the monthly voice refresh.

PRD prd-voice-refresh-monthly-2026-07-04, issue voice-refresh-orchestrator.

Repo-root automation (NOT the synced q-system/ tree). WRAPS the existing harness
scripts (granola-voice-synthesize.py, granola-voice-fingerprint.py); it never
modifies them. Headless-safe: Stage 1 harvest (the MCP-dependent pull) is done
upstream by the interactive /voice-refresh command, so this orchestrator runs on
a corpus that already exists.

Enforced contract:
- Contamination gate (ENFORCING): refuse to run if the corpus contains a
  review-flagged (>700-word turn) meeting. The harvest warn-flag becomes a block.
- Headless dependency: stop with an environmental-trigger diagnosis if `claude`
  is not on PATH (Stage 2 synthesize needs it). Never emit a stale merge silently.
- Idempotent: a second run on an unchanged corpus is a no-op.
- Every run that processes the corpus ENDS STAMPED (ASK-3405). The stamp used to
  be step 6 of the founder-gated /voice-refresh command, so it waited on his
  merge and never landed: measured 2026-10-29, .voice-refresh-last did not exist,
  the corpus hash was dated Jul 23, and the 2026-10-22 delta sat unreviewed. With
  no stamp the lookback falls back to "last 30 days" every run and the same
  meetings are re-harvested forever. A REFUSED run does not stamp: advancing the
  lookback past meetings that were never processed loses them silently.
- Splits the delta (ASK-3405): routine patterns merge through a reviewed PR,
  personal ones (layoffs, a mental-health leave) get one founder yes/no, because
  voice-dna.md fans out to every instance.
- Logs each step. Emits voice-delta.md (a proposal); NEVER writes voice-dna.md.

Usage: voice_refresh.py <corpus_dir>   |   voice_refresh.py --stale-check
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.environ.get(
    "VOICE_REFRESH_SCRIPTS",
    os.path.join(_HERE, "..", "q-system", ".q-system", "scripts"),
)
# Hardcoded to match the CLI that granola-voice-synthesize.py actually invokes.
# A configurable preflight binary could pass here and then fail inside Stage 2,
# defeating the promised environmental-trigger stop.
CLAUDE = "claude"

# An unanswered personal half becomes visible after this many days (ASK-3405).
STALE_DAYS = 7

# Terms that make a mined pattern HIS CALL rather than a style change. The list
# is deliberately broad: a false "personal" costs one yes/no, a false "routine"
# fans a personal disclosure to every instance in the fleet. Multi-word where the
# bare stem would misfire -- bare "leave" hits "leaves slight ESL flow
# unpolished", and bare "breakdown" hits "a breakdown of the argument", which are
# both ordinary style patterns.
#
# TWO groups, because one boundary rule gets one of them wrong (review round 2,
# ASK-3405). The earlier single tuple matched a LEADING boundary only while its
# comment claimed both, so it over-matched; adding a trailing \b to all of it
# would have been the expensive repair in the other direction.
#
# PERSONAL_STEMS: leading boundary, any continuation. One entry covers the
#   inflections -- "alcoholic" catches "alcoholics", "lawsuit" catches
#   "lawsuits", "psychiatr" catches psychiatrist/psychiatric/psychiatry. All four
#   of those classified personal before this change and a blanket trailing \b
#   would have silently stopped them (measured 2026-10-30), which is the
#   under-matching direction the asymmetry above says to avoid.
# PERSONAL_WORDS: BOTH boundaries. Only the entries whose open continuation
#   swallows an unrelated ordinary word live here: "chronic" inside "chronicle",
#   "debt" inside "debtor", "sober" inside "sobering", "visa" inside "visage".
#   Each of those four is ordinary English in a style description ("a sobering
#   number in the opener") and each classified personal before this change. The
#   real inflections that matter are listed explicitly beside them, so closing
#   the boundary does not cost "chronically" or "debts".
#
# An intra-term space or hyphen matches either spelling, so "mental-health leave"
# and "laid-off" classify the same as the spaced form. Hyphenated is the common
# spelling in writing and it matched nothing at all before this change.
PERSONAL_STEMS = (
    "layoff", "laid off", "let go", "fired", "severance", "redundancy",
    "mental health", "therapy", "therapist", "psychiatr", "antidepress",
    "depression", "depressed", "anxiety", "panic attack", "burnout", "burned out",
    "nervous breakdown", "suicid", "self-harm",
    "leave of absence", "medical leave", "sick leave", "stress leave", "fmla",
    "diagnosis", "diagnosed", "illness", "surgery", "medication",
    "disability", "disabled", "adhd", "audhd", "autism", "autistic",
    "neurodivergent",
    "divorce", "custody", "separated", "breakup", "marriage counsel",
    "miscarriage", "pregnan", "fertility", "ivf",
    "died", "death", "passed away", "funeral", "grief", "bereave",
    "addiction", "sobriety", "alcoholic", "drinking problem",
    "immigration", "green card", "deportation",
    "salary", "compensation package", "equity grant", "net worth",
    "bankrupt", "foreclos", "eviction",
    "lawsuit", "litigation", "settlement", "harassment", "discrimination",
    "retaliation",
)
PERSONAL_WORDS = (
    "chronic", "chronically", "debt", "debts", "sober", "visa", "visas",
    # review round 3: "hospital" swallowed "hospitality", "rehab" "rehabilitation".
    "hospital", "hospitals", "hospitalized", "hospitalised", "hospitalization",
    "rehab", "rehabs",
)

_WORD_SEP = re.compile(r"[\s\-]+")


def _term_pattern(term):
    """Term as a regex whose internal separators match a space OR a hyphen."""
    return r"[\s\-]+".join(re.escape(w) for w in _WORD_SEP.split(term) if w)


_PERSONAL_RE = re.compile(
    "|".join(
        [r"\b" + _term_pattern(t) for t in PERSONAL_STEMS]
        + [r"\b" + _term_pattern(t) + r"\b" for t in PERSONAL_WORDS]
    ),
    re.IGNORECASE,
)

# name -> env override. The single registry of repo-root state files: _state()
# resolves through it and the suite derives its isolation from it, so a new state
# file is isolated by adding one row here rather than by every future test
# remembering to patch a fixture.
STATE_FILES = {
    ".voice-refresh-last": "VOICE_REFRESH_STAMP",
    ".voice-delta-pending": "VOICE_DELTA_PENDING",
    ".voice-delta-answered": "VOICE_DELTA_ANSWERED",
    ".voice-delta-alerted": "VOICE_DELTA_ALERTED",
}


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(name):
    """Resolve a repo-root automation state file, env-overridable for tests.

    Read at CALL time, never at import: the suite sets these after importing the
    module, and a module-level default would pin the real founder's state files
    into a test run (fable-discipline: verify against a copy, never live state).

    FAIL-CLOSED under pytest (review round 2, ASK-3405). Reading at call time was
    not enough, because a test that simply never set the override still resolved
    to the real automation/ dir. test_idempotent_noop did exactly that: it ran
    refresh() on a temp corpus and stamped THIS checkout's live
    .voice-refresh-last while the suite reported 24 passed. Measured 2026-10-30,
    the stamp advanced 15:36:11Z -> 15:48:58Z on a run with no real refresh
    behind it. Step 1 of /voice-refresh reads that stamp as its lookback bound
    (plugins/kipi-core/commands/voice-refresh.md:14), so a fabricated stamp
    silently skips every meeting since the last real run -- the exact data loss
    this issue exists to prevent, caused by the issue's own tests. The same run
    rewrote .voice-delta-pending, which is what the 7-day nudge reads, so it also
    armed an alert about a delta that never existed.

    Raising beats quietly redirecting to a temp path: a redirect would let a test
    assert on a state file it never named, and the next reader of that test could
    not tell which file it meant.
    """
    env = STATE_FILES[name]
    override = os.environ.get(env)
    if override:
        return override
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            f"refusing to resolve {name} to the live automation/ dir under pytest. "
            f"Set {env} to a temp path. Every test in "
            f"automation/test_voice_refresh.py gets this from the autouse "
            f"_isolate_state_files fixture; a test outside it must set it itself."
        )
    return os.path.join(_HERE, name)


class RefreshError(Exception):
    """Carries an rca-taxonomy cause_type (environmental-trigger | latent-defect)."""

    def __init__(self, cause_type, msg):
        super().__init__(msg)
        self.cause_type = cause_type


def log(step, msg):
    print(f"[voice-refresh] {step}: {msg}")


def contamination_gate(corpus_dir):
    """Raise RefreshError if any meeting in talk-ranking.json is review-flagged."""
    rank_path = os.path.join(corpus_dir, "talk-ranking.json")
    if not os.path.exists(rank_path):
        raise RefreshError("latent-defect", f"missing {rank_path}; run Stage 1 harvest first")
    data = json.load(open(rank_path))
    flagged = [r for r in data.get("ranking", []) if "review_flag" in r]
    if flagged:
        titles = ", ".join(r.get("title", "?") for r in flagged)
        raise RefreshError(
            "latent-defect",
            f"contamination gate: {len(flagged)} review-flagged meeting(s) [{titles}]. "
            "Exclude or hand-rescue them before Stage 2.",
        )
    return True


def claude_available():
    return shutil.which(CLAUDE) is not None


def corpus_hash(corpus_dir):
    p = os.path.join(corpus_dir, "me-corpus.txt")
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else ""


def _run(script, corpus_dir):
    subprocess.run(["python3", os.path.join(SCRIPTS, script), corpus_dir], check=True)


def classify_finding(finding):
    """"personal" if the pattern is his call, else "routine" (ASK-3405).

    Reads the quotes and the rationale, not only the one-line pattern text: the
    extractor writes that line itself and it can be neutral ("rhythm of a long
    explanation") while the cited speech carries the disclosure. Measured shape
    from granola-voice-synthesize.py: category, pattern, evidence_quotes,
    why_distinctive.
    """
    haystack = " ".join([
        str(finding.get("category", "")),
        str(finding.get("pattern", "")),
        str(finding.get("why_distinctive", "")),
        " ".join(str(q) for q in finding.get("evidence_quotes") or []),
    ])
    return "personal" if _PERSONAL_RE.search(haystack) else "routine"


def _split_kept(corpus_dir):
    fp = os.path.join(corpus_dir, "voice-findings.json")
    kept = json.load(open(fp)).get("durable_kept", []) if os.path.exists(fp) else []
    buckets = {"routine": [], "personal": []}
    for f in kept:
        buckets[classify_finding(f)].append(f.get("pattern", ""))
    return buckets


def emit_delta(corpus_dir):
    """Write voice-delta.md, split routine vs personal. Never touches voice-dna.md."""
    buckets = _split_kept(corpus_dir)
    routine, personal = buckets["routine"], buckets["personal"]
    generated_at = _now_iso()
    lines = [
        "# Voice delta proposal\n",
        f"\nGenerated: {generated_at}\n",
        f"\n## Routine ({len(routine)})\n",
        "\nStyle patterns. These merge through a reviewed PR and do not wait on him.\n\n",
    ]
    lines += [f"- {p}\n" for p in routine] or ["- (none)\n"]
    lines += [
        f"\n## Personal ({len(personal)})\n",
        "\nOne yes/no from the founder for the whole block. voice-dna.md fans out to\n"
        "every instance, so a pattern mined from a personal disclosure is his call.\n\n",
    ]
    lines += [f"- {p}\n" for p in personal] or ["- (none)\n"]
    lines.append(
        "\nMerge an approved pattern via the commit + plugin-version-bump + "
        "marketplace-pull flow. This file never writes voice-dna.md itself.\n"
    )
    open(os.path.join(corpus_dir, "voice-delta.md"), "w").write("".join(lines))
    _write_pending(generated_at, routine, personal)


def _write_pending(generated_at, routine, personal):
    """Record that a personal block is waiting on him, so a 7-day silence is visible.

    Only the personal half can go unanswered. A routine-only delta waits on
    nobody, so marking it pending would raise an alert about work that is already
    moving through a PR.
    """
    pending = _state(".voice-delta-pending")
    if not personal:
        if os.path.exists(pending):
            os.remove(pending)
        return
    json.dump({"generated_at": generated_at, "personal": len(personal),
               "routine": len(routine)}, open(pending, "w"), indent=2)


def _parse_iso(text):
    try:
        return datetime.datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (ValueError, AttributeError):
        return None


def stale_delta_line(pending=None, answered=None, alerted=None):
    """One alert line when a personal block has gone STALE_DAYS unanswered, else "".

    Answered is a marker the merge flow writes; an answer older than the current
    delta belongs to the previous one and does not count. Fires once per
    generation: a monitor that repeats on every run teaches people to ignore it
    (founder-notifications: alert on state change, once).
    """
    pending = pending or _state(".voice-delta-pending")
    answered = answered or _state(".voice-delta-answered")
    alerted = alerted or _state(".voice-delta-alerted")
    if not os.path.exists(pending):
        return ""
    try:
        rec = json.load(open(pending))
    except (ValueError, OSError):
        return ""
    born = _parse_iso(rec.get("generated_at", ""))
    if born is None:
        return ""
    if os.path.exists(answered):
        ans = _parse_iso(open(answered).read())
        if ans is not None and ans >= born:
            return ""
    age = (datetime.datetime.now(datetime.timezone.utc) - born).days
    if age < STALE_DAYS:
        return ""
    if os.path.exists(alerted) and open(alerted).read().strip() == rec.get("generated_at"):
        return ""
    open(alerted, "w").write(rec.get("generated_at", ""))
    return (
        f"Voice delta unanswered for {age} days: {rec.get('personal', 0)} personal "
        f"pattern(s) need one yes/no before they can reach voice-dna.md. "
        f"See q-system/output/voice-corpus/voice-delta.md"
    )


def refresh(corpus_dir):
    log("start", corpus_dir)

    # Contamination gate runs FIRST, before any idempotency short-circuit, so a
    # contaminated corpus can never be silently declared "unchanged and fine."
    contamination_gate(corpus_dir)
    log("contamination", "clean")

    h = corpus_hash(corpus_dir)
    stamp = os.path.join(corpus_dir, ".voice-refresh-hash")
    outputs = ("voice-findings.json", "voice-fingerprint.json", "voice-delta.md")
    outputs_present = all(os.path.exists(os.path.join(corpus_dir, f)) for f in outputs)
    if h and outputs_present and os.path.exists(stamp) and open(stamp).read().strip() == h:
        log("idempotent", "corpus unchanged and all outputs present; no-op")
        _stamp_run()
        return "noop"

    if not claude_available():
        raise RefreshError(
            "environmental-trigger",
            f"'{CLAUDE}' not on PATH; Stage 2 synthesize needs it. Not producing a stale merge.",
        )

    log("stage2", "synthesize")
    _run("granola-voice-synthesize.py", corpus_dir)
    log("stage3", "fingerprint")
    _run("granola-voice-fingerprint.py", corpus_dir)
    emit_delta(corpus_dir)
    if h:
        open(stamp, "w").write(h)
    _stamp_run()
    log("done", "delta emitted")
    return "refreshed"


def _stamp_run():
    """Write .voice-refresh-last. The SINGLE writer of the lookback bound.

    Reached only from the two completed-run paths in refresh(). It is deliberately
    NOT reached from the RefreshError paths, and never from the /voice-refresh
    command: making the merge write it is the ASK-3405 defect, because the merge
    is founder-gated and a delta can sit for weeks.
    """
    path = _state(".voice-refresh-last")
    open(path, "w").write(_now_iso() + "\n")
    log("stamp", path)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--stale-check":
        line = stale_delta_line()
        if line:
            print(line)
        return
    if len(sys.argv) != 2:
        sys.exit("usage: voice_refresh.py <corpus_dir> | voice_refresh.py --stale-check")
    try:
        print(json.dumps({"result": refresh(sys.argv[1])}))
    except RefreshError as e:
        log("STOP", f"[{e.cause_type}] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
