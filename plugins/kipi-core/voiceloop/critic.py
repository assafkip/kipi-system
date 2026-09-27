#!/usr/bin/env python3
"""The second stage: judge ONE constraint per model call, then revise what failed.

why this exists (2026-08-12, ASK-699, plan `two-stage-writer-critic-2026-08-12.md`):
`build_prompt` rendered 25 to 40 constraints into a single instruction. Compliance
research (arXiv 2608.02639) measures obedience collapsing past roughly 20 stacked
constraints, and the drops are SILENT -- each draft obeys a different random subset. That
is the mechanism behind three rounds of the founder rejecting batches on properties the
prompt demonstrably carried: rendering the prompt proved the WORDS were there, which is
exactly the evidence RULE-2026-08-12-H says never tests the behaviour.

DeCRIM (arXiv 2410.06458) is the shape used here: decompose, critique, refine. So the
writer carries six constraints and everything else is judged HERE, one constraint per
call, against the draft the deterministic gates already passed.

## Where this sits, and why not one step earlier or later

`cycle.run_slot` calls this AFTER `decide_slot` returns a SHIPPABLE verdict. Two rejected
placements, kept so the choice is not re-derived:

- inside `decide._violations`: the gate census is counted from the AST and must stay
  honest at 15 deterministic checks. A model verdict in that list muddies both.
- before the gates in `prepare_candidate`: spends model calls on drafts the free
  deterministic gates may discard anyway, and gate REPAIR can alter text after the
  critic passed it, so the critic would have judged something that never shipped.

## The two fail directions, deliberately asymmetric

A malformed critic answer must not silently pass a QUALITY question (does it tell a
story, is he in it, is there something to catch the reader) -- those are the three the
founder's read fails on, so an unparseable verdict there fails CLOSED. On a STYLE row it
fails OPEN with a warn row, because a style constraint that cannot be parsed must not
kill supply; `decide_slot` raising IndexError on an empty supply is a dead slot, and a
dead slot is the founder-facing terminal state `decide.py` exists to forbid.

## One judgment per row (the checklist owner's standing rule, addendum 4, 2026-08-12)

A row states ONE positive fact required, as a yes/no, with no escape clause riding
along inside it. No compound "does the draft do X, rather than Y" and no required
positive test sharing a row with a prohibition.

The measurement behind it: banked draft `070c04d8` passed 13 of 13 rows and the founder
refused it, and three of those rows shared that compound shape. A model can satisfy the
weak half (no pitch, some kind of stance) and return a pass with the hard half never
present. That is the stacking failure this whole stage exists to escape, recreated one
level down inside a single row. Interpretive, so it lives here and not in a lint: the
tightened rows still use "rather than" to NAME a failure mode, which is fine, and a
regex cannot tell that from an escape hatch.

## The checklist is data, read every render

The checklist file is the operator's, verbatim, and it is READ on every review
rather than held as constants -- RULE-2026-08-12-F's corollary, the same wiring
`config/channel-guidance.json` has, so an edit provably changes what is judged. A missing
file degrades LOUD AND OPEN: nothing is judged, one warn row lands in the log, and the
notify sink is told. It cannot become the quiet normal because
`test_critic.py::TestTheLiveChecklistIsPresentAndPopulated` fails the suite when the real
file goes missing -- the same blocker `post_jobs` carries for the same reason.
"""
from __future__ import annotations

import concurrent.futures as _futures
import datetime as _dt
import fcntl
import json
import os
import re

from . import content_key, prompt_render

# THE TWO PATHS ARE NOT HERE, and that is the whole shape of this module's extraction
# (2026-09-06, VoiceLoop package extraction, slice 6b). The checklist a critic judges
# against and the ledger it writes to are the OPERATOR'S: one is a named person's list
# of constraints, the other is that person's receipt log. A fleet package that resolved
# either from its own __file__ would point every instance at whichever machine the
# package happened to be installed on.
#
# So every function that used to fall back to a module constant now REQUIRES the path,
# and `pipeline/critic.py` is the adapter that supplies both. The engine raising is
# deliberate and is the opposite of what the old default did: `load_checklist` answers
# [] on a read failure, which means "nothing was judged", and a moved path used to
# arrive as that same silent []. A missing argument is a wiring bug, not a data
# outcome, and it says so.
#
# An ADAPTER is safe here where `revise` needed an alias: nothing resolves a patched
# module-global through a closure in this file. The only monkeypatch the suite aims at
# critic is the model chokepoint, which is `prompt_render.run_model` and lives in
# neither namespace. `test_adapter_surface.py` holds both halves.

# Bounded, and the bound is the point. An unbounded critique/revise loop against a
# constraint the model cannot satisfy is the capitalization scar with a model on both
# ends: `decide.py` already carries the measurement (a gate the repair ladder cannot
# satisfy does not reject a post, it kills the slot after 1083 model calls).
CRITIC_MAX_ATTEMPTS = 3

#: How many constraints are judged at once. The 13 rows are INDEPENDENT judgments -- that
#: independence is the whole DeCRIM premise -- so they parallelise without changing any
#: verdict.
#:
#: why bounded and why this number (measured 2026-08-13): a sequential run took 67 minutes
#: for 3 drafts, and the founder's words were "this is taking a very long time". 13 serial
#: model calls per candidate dominated. At 5 workers the 13 rows land in 3 waves. Bounded
#: rather than unbounded because each worker is a `claude -p` subprocess, and 13 at once
#: is 13 processes competing for the same machine, which is how a speedup becomes a stall.
CRITIC_WORKERS = 5

# WHICH MODEL JUDGES, by tier (2026-08-13, founder-directed: the token spend is the
# problem, not the wall clock). Ids come from `.claude/rules/model-allocation.md`.
#
# The asymmetry is the point. A QUALITY row decides whether a draft lives, and its three
# questions are the ones the founder's read keeps failing on, so it gets the analysis
# tier. A STYLE row is a comparison against a stated rule, which is exactly the
# structured-extraction work the cheap tier is for, and it fails OPEN anyway so a wrong
# answer costs a warn rather than a post.
MODEL_QUALITY = "claude-sonnet-5"
MODEL_STYLE = "claude-haiku-4-5"

#: Model calls this module has made, by tier. Read by `run` into a cost row so the spend
#: per candidate is a number in the log rather than an impression.
CALL_COUNTS = {}

QUALITY = "quality"
STYLE = "style"

PASS = "pass"
FAIL = "fail"
WARN = "warn"

ACCEPTED = "accepted"
DISCARDED = "discarded"

# Log stages, so a row says which part of the loop produced it without a reader
# inferring it from the other fields.
STAGE_CRITIQUE = "critique"      # a constraint verdict on a draft
STAGE_REGATE = "regate"          # the 15 deterministic gates re-judging a revision
STAGE_CHECKLIST = "checklist"    # the checklist itself could not be read
STAGE_FORMAT = "format"          # the answer did not follow the strict contract
STAGE_COST = "cost"              # how many model calls this candidate cost, by tier
STAGE_CAPTURE = "capture"        # the caller's draft capture failed; the run continued


class Outcome:
    """What the critic did to ONE candidate. Never a hold, matching `decide.Verdict`."""

    __slots__ = ("status", "text", "rows", "reasons", "attempts")

    def __init__(self, status, text="", rows=None, reasons=None, attempts=1):
        self.status = status
        self.text = text
        self.rows = rows or []
        self.reasons = reasons or []
        self.attempts = attempts


def _required(value, what):
    """The engine has no default for an operator's file. Say so loudly."""
    if not value:
        raise ValueError(
            f"the voiceloop critic needs {what}; the engine has no default because a "
            f"default would be one operator's file resolved from wherever the package "
            f"is installed. The deployment adapter supplies it.")
    return value


def load_checklist(path):
    """The operator's constraint rows, or [] on any read failure.

    [] is a complete answer and it is the degraded one: it means nothing is judged. The
    caller distinguishes it from a genuinely empty list by the fact that the live file is
    pinned present by a test, so [] in production means the file moved.

    A MISSING `path` IS NOT THAT CASE and raises instead. The two used to be the same
    answer, because `path or CHECKLIST_PATH` turned an unwired caller into a readable
    file; here it would turn one into [], and "nothing was judged" is exactly the
    outcome that must never be reachable by accident.
    """
    try:
        with open(_required(path, "a checklist path"), encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def rows_for(channel, path):
    """The checklist rows that apply to this channel, in file order.

    Scoped by the row's own `channel_scope`, never by a table in this module: a scope
    living in code beside a scope living in data is the derivation split this package
    has a named scar for.
    """
    out = []
    for row in load_checklist(path):
        if not isinstance(row, dict) or not row.get("id") or not row.get("text"):
            continue
        scope = row.get("channel_scope") or []
        if channel is not None and scope and channel not in scope:
            continue
        out.append(row)
    return out


def build_prompt(text, row):
    """ONE constraint, one call. The decomposition IS the mechanism.

    Stacking two constraints into one call reproduces the collapse this stage exists to
    escape, so this function takes a single row and there is no batching entry point.

    THE VACUOUS-PRECONDITION LINE (2026-08-13), and it is a measured fix rather than a
    tidy one. On the first live batch, two of two candidates were failed by
    `tenure-naturalness` because no tenure appeared in the post at all. That row asks
    what must be true WHEN his tenure appears; a post with none satisfies it. Failing it
    inverts the rule into "every post must carry a credential", the opposite of what
    RULE-2026-08-12-F ruled, and candidate 2 passed 11 of 13 and died on it.

    FOUR rows are conditional, not three: `tenure-naturalness`, both external-incident
    rows, and `ending-discipline` ("If the ending reaches for..."), which the first count
    here missed. The live batch only hit the tenure one; the other three were latent, and
    `ending-discipline` is a style row so its false FAIL would have been quieter still.
    The constraint TEXT is correct as written; the scaffolding never said what an
    inapplicable requirement means, which is a defect in this function.

    THE FIX IS GENERIC, not a row list. One sentence in the instruction below governs
    every constraint, including ones nobody has written yet. `CONDITIONAL_ROWS` in
    `test_critic.py` names today's four only so a NEW conditional row cannot be added
    without someone noticing, and a self-enumerating guard there rescans the checklist
    for precondition openers and fails if it finds one the list does not name.

    The constraint sentence is the operator's, verbatim from the checklist. Everything around it
    is scaffolding and shows no worked sentence, because a quoted finished sentence here
    is one a reviser can copy into a post. The executable that catches it is
    `pipeline/tests/test_critic.py::test_the_critic_prompt_shows_no_worked_example`, which
    renders this function and searches for a quoted capital-initial period-terminal span.
    """
    return f"""You are reviewing ONE post against ONE requirement. Nothing else.

THE REQUIREMENT:
{row['text']}

Answer in exactly two lines, in this order and this format:

EVIDENCE: the specific thing in the post that decides it, or its absence. Quote nothing.
VERDICT: PASS or FAIL, one word, nothing else on the line.

The EVIDENCE line comes FIRST and the VERDICT follows FROM it. Do not state a verdict
the evidence line does not support.

If the requirement is conditional and its condition does not apply to this post,
answer PASS. A requirement about what a post must do WHEN it does something is
satisfied by a post that never does that thing.

Judge only the requirement above. Do not judge spelling, length, formatting or any
other rule. Do not rewrite the post. Do not suggest wording.

THE POST:
{text}
"""


#: The strict answer contract. `VERDICT: PASS` on its own line, nothing else.
VERDICT_LINE = re.compile(r"^\s*VERDICT\s*:\s*\**\s*(PASS|FAIL)\b", re.I | re.M)

#: The loose fallback: a bare PASS/FAIL as the first non-empty line, the shape the
#: contract used before 2026-08-13.
_BARE_HEAD = re.compile(r"^[\s*#]*(PASS|FAIL)\b", re.I)

FORMAT_OK = "ok"
FORMAT_LOOSE = "loose"
FORMAT_UNPARSEABLE = "unparseable"


def parse_answer(answer, tier):
    """(verdict, detail, format_state). The parser behind `parse_verdict`.

    THREE STATES, not two, and the middle one is the point (sp-a55d1ffb, 2026-08-13).
    A strict-only parser would fail-closed every quality row whenever the model dropped
    the prefix, which is a supply cliff. An accept-anything parser measures nothing. So a
    readable-but-non-conforming answer is HONOURED and RECORDED, which makes the
    contract-violation rate a number someone can look at instead of a suspicion.

    Only a genuinely unreadable answer takes the fail-closed path, keeping the existing
    asymmetry: closed on quality, open with a warn on style.

    What this does NOT do: decide whether the EVIDENCE line agrees with the VERDICT.
    That is semantic and needs a classifier; a word-list one is refused under
    RULE-2026-08-12-D. Residual captured as sp-a55d1ffb. What the reordered prompt does
    is attack it at the source, by making the model write the evidence BEFORE committing
    to a token rather than after it.
    """
    text = answer or ""
    detail = " ".join(text.split())[:300]
    strict = VERDICT_LINE.findall(text)
    if len(strict) == 1:
        return (PASS if strict[0].upper() == "PASS" else FAIL), detail, FORMAT_OK
    if len(strict) > 1:
        # Two verdict lines is the model contradicting itself in the machine-readable
        # half. Never guess which one it meant.
        if tier == QUALITY:
            return (FAIL, f"{len(strict)} VERDICT lines, failing closed: {detail}",
                    FORMAT_UNPARSEABLE)
        return (WARN, f"{len(strict)} VERDICT lines, passing open on style: {detail}",
                FORMAT_UNPARSEABLE)
    for line in text.splitlines():
        if line.strip():
            head = _BARE_HEAD.match(line.strip())
            if head:
                return ((PASS if head.group(1).upper() == "PASS" else FAIL), detail,
                        FORMAT_LOOSE)
            break
    if tier == QUALITY:
        return (FAIL,
                f"unparseable critic answer, failing closed on a quality row: {detail}",
                FORMAT_UNPARSEABLE)
    return (WARN,
            f"unparseable critic answer, passing open on a style row: {detail}",
            FORMAT_UNPARSEABLE)


def parse_verdict(answer, tier):
    """(verdict, detail) from the model's reply. Fails CLOSED on quality, OPEN on style.

    why the split (the plan, and it is the asymmetry that matters): an unparseable answer
    on `tells-a-story` must not become a pass, because that is the exact property the
    founder's read fails on. An unparseable answer on a style row must not become a
    block, because a style row cannot be worth starving a slot for.
    """
    verdict, detail, _state = parse_answer(answer, tier)
    return verdict, detail


def model_for(row):
    """The tier this row is judged at. Quality rows decide life; style rows compare."""
    return MODEL_QUALITY if (row.get("tier") or STYLE) == QUALITY else MODEL_STYLE


def judge(text, row, runner=None, claude_bin=None, timeout=prompt_render.TIMEOUT_SECONDS,
          counts=None):
    """One constraint, one model call, through the ONE chokepoint.

    `prompt_render.run_model` is reused rather than reimplemented (founder-directed
    2026-08-06:
    the comment writer grew its own subprocess call, its own timeout and its own test
    guard, which is how two callers drift until one is reading the wrong files). That also
    means `PYTEST_CURRENT_TEST` applies here: a suite that forgets to inject `runner=`
    raises instead of spending a real call.
    """
    tier = row.get("tier") or STYLE
    if counts is not None:
        counts[tier] = counts.get(tier, 0) + 1
    answer = prompt_render.run_model(build_prompt(text, row), claude_bin=claude_bin,
                                     timeout=timeout, runner=runner,
                                     caller="critic.judge()", model=model_for(row))
    # A failed call (timeout, missing binary, non-zero exit) takes the same posture as an
    # unparseable answer: closed on quality, open on style.
    return parse_answer(answer or "", row.get("tier") or STYLE)


def review(text, channel, runner=None, path=None, order=None, workers=None,
           counts=None, **kwargs):
    """Judge every applicable constraint. Returns [(row, verdict, detail, format)].

    `order` is a list of constraint ids to judge FIRST. Used by the revision loop: a
    revision is re-critiqued failed-constraints-first, then the rest, because a revision
    aimed at one constraint can break one that had already passed.

    CONCURRENT, bounded at `CRITIC_WORKERS` (2026-08-13). The rows are independent
    judgments by construction, so running them together changes no verdict; it only stops
    13 serial model calls from being the wall clock. THE RETURNED ORDER IS ALWAYS ROW
    ORDER, never completion order, because the log's readability and the failed-first
    re-critique both depend on it -- `executor.map` preserves input order.

    NO EARLY EXIT on the first failure, deliberately. The full trail IS the product: the
    founder's review reads which rules a draft failed, and a short-circuited run would
    report one failure and hide four.
    """
    rows = rows_for(channel, path)
    if order:
        rank = {cid: i for i, cid in enumerate(order)}
        rows = sorted(rows, key=lambda r: (rank.get(r["id"], len(rank)),))
    if not rows:
        return []

    def _wave(batch):
        if not batch:
            return []
        limit = max(1, min(workers or CRITIC_WORKERS, len(batch)))
        if limit == 1:
            return [(row,) + judge(text, row, runner=runner, counts=counts, **kwargs)
                    for row in batch]

        def _one(row):
            return (row,) + judge(text, row, runner=runner, counts=counts, **kwargs)

        with _futures.ThreadPoolExecutor(max_workers=limit) as pool:
            return list(pool.map(_one, batch))

    # QUALITY FIRST, THEN STYLE ONLY IF QUALITY HELD (2026-08-13). A candidate that fails
    # a quality row is dead: the loop will revise or discard it, and the style verdicts
    # are spend on a body nobody will read.
    #
    # The cut is between WAVES, never inside one. Every quality row still runs, so the
    # founder's review keeps the full quality trail and the reviser gets every failure at
    # once instead of one per attempt. Short-circuiting inside the quality wave would
    # report one failure and hide four, which is the thing the trail exists to prevent.
    quality = [r for r in rows if (r.get("tier") or STYLE) == QUALITY]
    style = [r for r in rows if (r.get("tier") or STYLE) != QUALITY]
    results = _wave(quality)
    if any(verdict == FAIL for _row, verdict, _detail, _fmt in results):
        return results
    return results + _wave(style)


def _row(at, channel, text, constraint_id, verdict, detail, attempt, stage):
    return {
        "at": at,
        "channel": channel,
        # The SAME sha function the postbook and the queue use. Two functions answering
        # "is this the same post" is the derivation split that published one body on two
        # channels six minutes apart.
        "draft_sha": content_key.text_sha(text or ""),
        "constraint_id": constraint_id,
        "verdict": verdict,
        "detail": (detail or "")[:400],
        "attempt": attempt,
        "stage": stage,
    }


def _cost_row(at, channel, text, counts, attempt):
    """One row per candidate saying what judging it cost, by tier."""
    total = sum(counts.values())
    detail = ", ".join(f"{tier}={n}" for tier, n in sorted(counts.items())) or "none"
    return _row(at, channel, text, "calls", str(total),
                f"critic model calls for this candidate: {detail}", attempt, STAGE_COST)


def append(rows, path=None):
    """THE single writer of the critic log. Append-only, never rewritten.

    Everything that logs a critic verdict comes through here, so there is one place that
    knows the row shape and one place that opens the file. `test_critic.py` greps the
    package to prove no other module writes `critic-log.jsonl`.
    """
    if not rows:
        return 0
    # A SUITE MUST NEVER TOUCH THE LIVE LEDGER, and this guard exists because it did.
    #
    # Measured 2026-08-12, ASK-699, within an hour of wiring the critic into
    # `cycle.run_slot`: `output/critic-log.jsonl` held 490 rows that no run produced.
    # They came from the 37 pre-existing run_slot call sites, which do not pass
    # `critic_log_path` and had no reason to -- the conftest stub answers their critic
    # calls, and `append` then resolved `path=None` to the production file. Three
    # fixture bodies, all PASS, all stamped with a test's frozen timestamp, sitting in
    # the ledger the founder's review batch renders from.
    #
    # Same shape and same posture as `cycle.supply_for_slot`'s guard, which refuses to
    # read the live queue when no `queue_path` is passed under pytest. Refusing the
    # WRITE is the tighter half: a test that wants rows passes `log_path`, and
    # `test_critic.py` and `test_critic_live_path.py` both do, so nothing loses coverage.
    #
    # Returns 0 rather than raising, deliberately: raising would fail 37 tests that are
    # correct as written and never asked for a critic at all.
    if path is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    # The guard above still decides, and it decides FIRST. The deployment adapter
    # supplies its default only outside pytest, for exactly that reason: a test that
    # never asked for a critic must not be able to write fixture verdicts into the
    # operator's live ledger, and it could if the adapter filled the path in before
    # this line ever ran.
    path = _required(path, "a critic log path")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # ONE WRITER, AND NOW ALSO ONE WRITE. Concurrency arrived in `review` 2026-08-13, and
    # while this function is still the only thing that opens the file, two PROCESSES
    # (a scheduled bank run and a hand-driven one) can reach it at the same moment. An
    # interleaved write would split a JSONL row down the middle and `read_log`'s
    # json.loads would raise on a line that is half of one row and half of another.
    #
    # The lock is advisory and process-wide; the payload is serialised ONCE and written
    # in a single call, so a reader never sees a partial row even without the lock. Both,
    # because a lock on its own does not help a reader mid-write and a single write on
    # its own does not order two appends.
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(payload)
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return len(rows)


def read_log(path):
    """Every row, oldest first. The operator's review renders from this."""
    path = _required(path, "a critic log path")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def violations_for(failures):
    """Failed constraints as `revise.revise` violations.

    The rule name is namespaced `critic-<id>` so a reader of a discard reason can tell a
    model verdict from one of the 15 deterministic gates. The detail carries the
    constraint text AND the critic's finding, because the reviser is given the detail and
    nothing else: handing it only the finding would ask it to fix a complaint whose
    requirement it cannot see.
    """
    return [{"rule": f"critic-{row['id']}",
             "detail": f"{row['text']} The review found: {detail}"}
            for row, detail in failures]


def run(text, channel, at=None, runner=None, reviser=None, regate=None,
        path=None, log_path=None, attempts=CRITIC_MAX_ATTEMPTS, notify=None,
        capture=None, **kwargs):
    """Critique, revise, re-gate, re-critique. Returns an `Outcome`, never a hold.

    `regate(text) -> (repaired_text, blocking_violations)` is supplied by the caller and
    is `decide.assess` with the slot's own arguments. It is required for revision:
    without it a critic-driven revision would ship without re-entering the 15
    deterministic gates, which is the one thing the placement fork was picked to prevent.

    THE SHIPPED TEXT IS THE JUDGED TEXT. This returns either the string it was handed or
    a string `reviser` produced and `regate` then cleared. The critic's rationale flows
    only into the log rows. `test_critic_rationale_never_reaches_the_body` drives it.

    A revision the gates reject is a DISCARD, not another attempt: re-running the same
    prompt against the same text is the identical-retry this repo already bans, and the
    slot refills from the next candidate in the same cycle.

    `capture(bodies, channel, at)` IS OPTIONAL AND THE ENGINE OWNS NO STORE (2026-09-07,
    cgs-1). The critic keeps `content_key.text_sha(text)` and throws the body away, so
    none of its verdicts could ever be checked against a person's own read: a draft that
    fails is discarded and never reaches the postbook. `bodies` is every body this run
    wrote a VERDICT ROW about, keyed by that same sha, handed to the caller once, after
    the log is written. That is wider than "judged": it includes a revision the deterministic
    gates rejected, which the critic never scored but which owns a STAGE_REGATE row and
    therefore has to be joinable. The store carries no stage, so a gold-set builder
    tells the two apart by joining back through the log.

    why a CALLABLE and not a path. The store needs a read-modify-write under
    `locking.file_lock`, which locks a sibling `<path>.lock` because `os.replace` swaps
    the inode; a lock taken on the data file the way `append` does it guards an inode
    the replace has already unlinked and excludes nobody. Engine code may not import the
    deployment's lock, so a store here would have had a second writer AND a second lock
    mechanism that never serialised against the first. Injecting the callable puts the
    whole store on one side of the line.

    A capture that raises is a MISSING CACHE ROW, never a dead slot. Nothing else on
    this path catches it, so an ENOSPC on the output directory would propagate out of
    `critic.run` into `cycle.run_slot`.

    THE BLAST RADIUS, corrected after review measured it rather than accepting the
    first draft's claim. A deployment whose scheduled callers already wrap this in
    `except Exception` loses one SLOT plus an error entry in its heartbeat, not the
    whole job. That is bad enough and is the argument this wrapper stands on; a scar
    comment that overstates its own scar is how the next reader stops trusting the
    rest of the comment. A deployment that does NOT wrap its caller loses the job, so
    the wrapper is the engine's guarantee either way.
    """
    at = at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = rows_for(channel, path)
    log_rows = []
    attempt = 1
    # Every body this run JUDGED, keyed by the same content key the log rows carry, so
    # the two artifacts join. A dict and not a list because the revision loop can judge
    # the same body twice (failed rows are re-judged first on the next pass).
    judged = {}

    def _note(body):
        """Record a body at the moment it enters judgement.

        Two other placements were measured and rejected. `_row` is a pure dict-builder
        that `test_critic.py` calls directly and whose regate callers pass gate-repaired
        text; making it write would make those tests write. `_cost_row` fires once per
        candidate with whichever body is current, so it stores at most one body per
        candidate while a revising run judges two or three, and the ones it drops are
        the attempt-1 originals.

        THE RATIO IS THE POINT AND THE LOG IS THE RECORD. An operator's verdict log
        carries far more distinct `draft_sha` than `cost` rows; count them there rather
        than trusting a number written here, which rots (the first draft of this
        comment was stale within the hour, partly from the run that verified it) and
        which is that operator's usage data, not this package's.
        """
        if body:
            judged[content_key.text_sha(body)] = body

    def _flush():
        """THE single flush point, replacing the six bare `append` calls.

        Order is load-bearing: the verdict log is the primary artifact and is written
        FIRST, so a capture failure cannot cost a verdict row.

        THE COST OF THAT ORDER, named because the standard review asked for it either
        fixed or stated. A capture failure produces a SECOND append, so one run's rows
        are no longer one atomic write, and `critic.append`'s own docstring records that
        two processes reach this file at once. Another run's rows can land between the
        two, and `batch_review.segments` opens a block only on an attempt-1 critique
        row, so an orphaned capture warn row is attributed to whichever block is open.
        The alternative -- run the capture first and write once -- was rejected: the
        store takes a file lock, and a STUCK lock (not a raise) would then lose the
        verdict rows entirely, which is strictly worse than mis-attributing a warn.
        The rendering half is `batch_review`'s and is out of this issue's scope.
        """
        append(log_rows, log_path)
        if capture is None:
            return
        try:
            capture(dict(judged), channel, at)
        except Exception as exc:                  # noqa: BLE001 - see the docstring
            # LOUD AND OPEN, the same posture as the empty-checklist branch. A capture
            # that never fired and one that fails every time look identical in the
            # store, so the difference has to reach the log and the notify sink.
            #
            # THE RECOVERY IS WRAPPED TOO, and that is not belt-and-braces. The fault
            # this handler exists for is ENOSPC or a permission fault on the output
            # directory, and a deployment normally puts its draft store and its critic
            # log in the SAME one. So the recovery is another `append` into the very
            # directory that just failed, plus a `notify` into caller-supplied code.
            # Unwrapped, the exact fault named two lines up raised out of `run()` into
            # the caller and cost a slot: the recovery became the failure. Found by
            # review 2026-09-07, reproduced by
            # `test_a_failing_log_write_in_the_recovery_still_cannot_kill_the_run`.
            try:
                append([_row(at, channel, text, "capture", WARN,
                             f"draft capture failed after {len(judged)} bodies: "
                             f"{exc}", attempt, STAGE_CAPTURE)],
                       log_path)
            except Exception:                     # noqa: BLE001
                pass
            if notify:
                try:
                    notify(f"{channel}: draft capture failed: {exc}")
                except Exception:                 # noqa: BLE001
                    pass
    # THE SPEND IS A NUMBER IN THE LOG, not an impression (2026-08-13). Counted per
    # candidate across every attempt, split by tier, so "we are burning way too many
    # tokens" becomes something anyone can total out of the file.
    counts = {}

    if not rows:
        # LOUD AND OPEN. Nothing was judged, and the run says so in the log and to the
        # notify sink rather than passing quietly, because a silently absent critic is
        # indistinguishable from a critic that approved everything.
        log_rows.append(_row(at, channel, text, "checklist", WARN,
                             f"no critic constraints loaded from "
                             f"{path}; nothing was judged",
                             1, STAGE_CHECKLIST))
        if notify:
            notify(f"{channel}: critic checklist empty or unreadable; draft shipped "
                   f"with no critique")
        _flush()
        return Outcome(ACCEPTED, text, log_rows)
    order = None
    while True:
        _note(text)
        results = review(text, channel, runner=runner, path=path, order=order,
                         counts=counts, **kwargs)
        failures = []
        for row, verdict, detail, fmt in results:
            log_rows.append(_row(at, channel, text, row["id"], verdict, detail,
                                 attempt, STAGE_CRITIQUE))
            # THE CONTRACT-VIOLATION RATE IS A NUMBER, not a suspicion (sp-a55d1ffb).
            # A row lands whenever the answer did not follow the strict format, so the
            # rate is countable from the log instead of being inferred from vibes.
            if fmt != FORMAT_OK:
                log_rows.append(_row(at, channel, text, row["id"], fmt,
                                     f"answer did not follow the VERDICT contract "
                                     f"({fmt}); verdict honoured as {verdict}",
                                     attempt, STAGE_FORMAT))
            if verdict == FAIL:
                failures.append((row, detail))
        if not failures:
            log_rows.append(_cost_row(at, channel, text, counts, attempt))
            _flush()
            return Outcome(ACCEPTED, text, log_rows, attempts=attempt)
        if attempt >= attempts or reviser is None or regate is None:
            reasons = [f"critic-{row['id']}: {detail}" for row, detail in failures]
            log_rows.append(_cost_row(at, channel, text, counts, attempt))
            _flush()
            return Outcome(DISCARDED, "", log_rows, reasons, attempts=attempt)

        attempt += 1
        try:
            revised = reviser(text, violations_for(failures))
        except Exception as exc:                  # a broken reviser is not a hold
            reasons = [f"reviser raised: {exc}"]
            log_rows.append(_cost_row(at, channel, text, counts, attempt))
            _flush()
            return Outcome(DISCARDED, "", log_rows, reasons, attempts=attempt)
        if not revised:
            reasons = ["reviser returned nothing"] + \
                      [f"critic-{row['id']}: {detail}" for row, detail in failures]
            log_rows.append(_cost_row(at, channel, text, counts, attempt))
            _flush()
            return Outcome(DISCARDED, "", log_rows, reasons, attempts=attempt)

        repaired, blocking = regate(revised)
        if blocking:
            _note(revised)
            detail = "; ".join(str(v.get("detail", v)) for v in blocking)[:300]
            log_rows.append(_row(at, channel, revised, "gates", FAIL, detail,
                                 attempt, STAGE_REGATE))
            log_rows.append(_cost_row(at, channel, text, counts, attempt))
            _flush()
            return Outcome(DISCARDED, "", log_rows,
                           [f"critic revision failed the gate stack: {detail}"],
                           attempts=attempt)
        # NO _note(repaired) HERE, deliberately. `text = repaired` follows, and the
        # loop head re-enters `_note(text)` one statement later with the same body, so
        # a call here is dead by construction: deleting it left the whole suite green
        # (standard review, 2026-09-07). The regate-FAIL branch above DOES need its own
        # `_note`, because that branch returns and never reaches the loop head.
        log_rows.append(_row(at, channel, repaired, "gates", PASS,
                             "critic revision re-entered the full gate stack and passed",
                             attempt, STAGE_REGATE))
        text = repaired
        # Failed constraints are re-judged FIRST on the next pass, then the rest, because
        # a revision aimed at one constraint can break one that had already passed.
        order = [row["id"] for row, _ in failures]
