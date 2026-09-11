#!/usr/bin/env python3
"""Targeted revision: fix the NAMED violations in a post, keep everything else.

why this exists (2026-08-05, founder-directed): of 12 real human drafts, only 4 survived
the gate, and the deaths were all FIXABLE -- a bare "80%" needing its source or its count
form, a post missing one mechanism sentence. The engine's only tool for a dirty candidate
was discard. Founder, verbatim: "you dont need to kill posts that have a fail, just fix
the fail if possible. you are narrowing your own set by killing a full post over
capitalization."

Cole's history shows both failure directions, so this module is built against both:

- Discard-instead-of-repair starved cole's queue for weeks (producer.produce dropped
  on lint-fail; four lanes still hold-not-regenerate). Hence this layer exists.
- Weaken-the-gate-to-pass is how cole's two highest-volume lanes ended up shipping
  with no AI-shape check at all (DIGEST_DOWNGRADE grew rule by rule). The deterministic
  blocker against that here is `decide.decide_candidate`: it re-runs `decide.assess`
  (the full gate stack) on every revision this module returns, so a bad revision is
  discarded by code, and `test_revise.py::test_a_revision_that_still_fails_is_discarded`
  is the negative proof that the re-gate can actually reject.

The layering: deterministic repair -> gate -> THIS (bounded) -> discard as last resort.

why this is ENGINE code (2026-09-06, VoiceLoop package extraction, slice 6b). The
repair ladder is the method and the rung is the same for every operator: hand the
model the NAMED failures, forbid invention, re-gate what comes back. `RULE_GUIDANCE`
is keyed by rule name, and every entry is an instruction about the DEFECT rather than
about ASK -- "restate the percentage as its underlying count", "capitalize sentence
starts". None of it is one practice's positioning.

why it is an ALIAS in the deployment and not an adapter, which is the whole scar of
this slice. `reviser()` returns a closure that calls the bare name `revise(...)`, and
Python resolves that in the globals of the module where `reviser` is DEFINED. A
forwarding adapter is a second namespace, so `monkeypatch.setattr(revise, "revise",
...)` would patch a name nothing reads. Measured: it took
`test_reddit_mirrors_the_post_mechanism` green to red with "regenerator raised: revise
reached the live model from inside a test", eight lines away from any test that
mentions revising. So `pipeline/revise.py` aliases this module through `sys.modules`
and the two deployment values arrive as ARGUMENTS instead.

Distinct from `generate.py` on purpose: generate turns raw MATERIAL into a post and may
restructure freely. This edits a POST that is already in the founder's voice, and the
prompt forbids restructuring, because a full rewrite of a human draft would replace his
words with a model's, which is the exact thing the voice system exists to prevent.
"""
from __future__ import annotations

import os
import subprocess

from . import prompt_render

TIMEOUT_SECONDS = 120

# The two sentences the reviser USED to be handed as shapes to imitate. They are no
# longer in any prompt, and this constant exists only so the echo gate can RECOGNISE
# them (item 8).
#
# why the constant survives a deletion (item 8, and the PRD is explicit): both strings
# shipped in real published posts -- 9 of 22 carried the second one verbatim -- so a
# future candidate reproducing one is still a leak worth catching, and the echo gate can
# only catch what the carried set contains. Delete the constant and the gate goes blind
# to the exact strings it was built for. The prompt copy and the comparison copy have
# OPPOSITE jobs, which is why this is a rename and not a removal. Item 6 deleted the
# generator's copies outright and had to resurrect them as RETIRED_GENERATOR_EXAMPLES;
# doing it in that order costs a round trip and briefly leaves the gate blind.
#
# The contradiction this resolves: item 7 made these two strings a REJECTION rule
# (`voice-retired-phrase`), while RULE_GUIDANCE was still quoting them at the model as
# things to write. The same slot was handing out a phrase and killing a post for using
# it. Reproducing one is now a violation, so instructing the model to reproduce one had
# to stop.
RETIRED_GUIDANCE_EXAMPLES = (
    "Different vocabularies. Same architecture underneath.",
    "Nothing was sent. Nothing was lost. The damage was trust.",
)

# Rules whose fix CANNOT be surgical, so the surgical instruction has to stand down.
#
# why this exists (2026-08-09, x-format-4b-length, adversarial review): the new
# `x-too-long` gate is correct about the text and the reviser could not act on it. It
# received the generic "fix exactly what the check describes" while the SAME prompt
# said "Keep every other word, the order, the line breaks and the voice exactly as
# they are". Told to shorten a post and forbidden to change a word.
#
# Measured on the real supply with the engine's own published bodies as the generator:
# the X slot raised IndexError after 371 candidates and 1083 model calls, where the
# pre-gate path shipped after 61 discards and 184 calls. A gate the repair ladder
# cannot satisfy does not reject a post, it kills the slot -- and `decide_slot` raises
# before `run_slot` writes any row, so the failure is not even recorded.
#
# Deliberately a SET and not a flag on each guidance string: the conflicting sentence
# is one line in the prompt, and which line to print is a property of the violation
# SET, not of any single rule.
REWRITE_RULES = frozenset({"x-too-long"})

# What each repairable-with-meaning rule needs. Keyed by the linters' rule names.
# A rule absent from this table still gets revised: the violation detail itself is the
# instruction, and the gate re-judges the result either way.
RULE_GUIDANCE = {
    "x-too-long": (
        "cut it to fit. This is the one rule that authorises a REWRITE: drop whole "
        "sentences, drop the weakest example, and keep the single strongest idea. "
        "Preserve the voice, the central claim and every number that survives -- but "
        "do NOT preserve the length, the line breaks or the sentence order. A post "
        "that is still too long is a post that will be truncated, so returning it "
        "unchanged is worse than returning nothing."),
    "stats-citation": (
        "attach the figure's named source inline if the draft names one, or restate the "
        "percentage as its underlying count ('80%' -> '4 of 5', '60%' -> '3 of 5'). "
        "NEVER invent a source or a study."),
    "banned-word": (
        "replace the banned word with a plain everyday word that keeps the sentence's "
        "meaning. Do not rewrite the sentence around it."),
    "banned-phrase": (
        "delete the banned phrase or say the same thing in plain words."),
    "substance-number": (
        "bind a number ALREADY IN THE DRAFT to its denominator, rate, timeframe or "
        "dollar amount. Use only numbers the draft contains. If the draft has no real "
        "number to bind, output nothing at all."),
    "substance-mechanism": (
        "add one sentence saying WHY it happened or HOW it works, using only facts "
        "already in the draft. If the draft never says why, output nothing at all."),
    "figure-unsourced": (
        "the named figures are not in the material this post came from. Replace each one "
        "with a number the check lists as present in the source, or delete the sentence "
        "carrying it. NEVER adjust a figure to something that sounds close. The listed "
        "source numbers are the ONLY numbers you may use."),
    # Added 2026-08-06 with the outright closing-question ban. Without explicit guidance
    # this rule fell through to "fix exactly what the check describes", and the reviser
    # answered a banned question by writing a different question. Every candidate ending
    # in one would burn its three attempts and discard, which starves the slot.
    "marketer-ending": (
        "replace the FINAL sentence only. Leave every other sentence exactly as it is. "
        "The new final sentence must be a VERDICT: a flat statement of what the thing "
        "means, drawn from facts already in the draft. It must NOT be a question of any "
        "kind, must NOT tell the reader to go do something ('pick one...', 'go check "
        "your...', 'worth checking...'), and must NOT solicit a reply, a follow or a "
        "booking. He does not end on questions: 1 of 27 of his published samples does. "
        # No sentence to copy, and no retreat to abstraction either. Abstraction was the
        # first attempt and it starved slots: every closing-question candidate burned all
        # three attempts and discarded. Pointing at the DRAFT'S OWN subject is concrete
        # enough to act on and differs per post, so there is nothing to reproduce.
        "Build it out of the draft's own subject: name the thing the draft is about, "
        "then state the one thing that is now true about it. Two short clauses beat one "
        "long one. Do not reach for a phrase from anywhere else."),
    # voice-4: the echo gate's repairs. "Own words" is the whole instruction; the
    # facts stay, the borrowed sentences go.
    "voice-echo": (
        "one or more passages are copied verbatim from the example posts in the "
        "prompt. Rewrite ONLY those passages in your own words. Keep every fact, "
        "keep the meaning, change the wording and sentence shapes. Never quote "
        "the examples."),
    "voice-opener-echo": (
        "rewrite ONLY the first sentence so it opens differently from the recent "
        "post named in the check. Keep its meaning. Do not change any other "
        "sentence."),
    # voice-6: the fingerprint gate's repairs. Rhythm edits, facts untouched.
    "voicefp-sentence_mean": (
        "his sentences run 5 to 9 words; this draft's run long. Split long "
        "sentences into short ones. Change no fact, remove no content -- only "
        "add periods and trim connectives."),
    "voicefp-short_share": (
        "his writing is majority short bursts (6 words or fewer); this draft "
        "has too few. Split sentences so at least half are 6 words or fewer. "
        "Change no fact."),
    # 2026-08-24, RCA-voice-enforcement RC3: style-distance feedback reaches the
    # reviser through the same channel as every other gate. One entry per axis
    # the calibrated review can hold on; the detail row names the measured drift.
    "voice-style-colon_rate": (
        "he almost never writes colon constructions. Fold each colon line into a "
        "plain sentence or split it. Keep the content; lose the setup-line shape."),
    "voice-style-para_max_sentences": (
        "one paragraph carries far more sentences than he ever packs in. Split it "
        "into paragraphs of one to three short sentences."),
    "voice-style-first_person_rate": (
        "the draft barely says I, my, me. Ground it in what HE did: first person, "
        "specific and witnessed, no general advice voice."),
    "voice-style-monotony_run": (
        "too many consecutive sentences of near-identical length. Vary the rhythm: "
        "break one run with a very short sentence."),
    "voice-style-sentence_stdev": (
        "sentence lengths are too uniform against his range. Mix bursts with one "
        "longer sentence."),
    "voice-style-aggregate": (
        "overall the draft sits farther from his voice than anything he wrote. "
        "Recast it toward his register: short bursts, first person, concrete "
        "verdicts, no marketing cadence."),
    "source-shape": (
        "rewrite the flagged fragments as prose a reader outside the codebase "
        "understands: no file names, ticket keys, commit prefixes, code identifiers or "
        "CLI flags. The claim stays; the notation goes."),
    # 2026-08-13, founder-directed: posts carry neither the emdash nor " -- ".
    "emdash": "replace each em dash with a comma or a period. Never with ' -- '.",
    "double-dash": (
        "replace each ' -- ' with a comma, a period, or recast the sentence so the "
        "pause is not needed. Change nothing else. Posts carry neither the emdash "
        "nor the double dash."),
    "capitalization": (
        "capitalize sentence starts and the word 'I'. A tool name whose correct "
        "spelling is lowercase goes in backticks instead of being recapitalized."),
    "slash-command": "name the command in prose without the leading slash.",
}


#: Who the post is attributed to inside the instruction, when the caller names nobody.
#:
#: why a PARAMETER and not a constant (2026-09-06, slice 6b). The sentence below used to
#: read "already written in <the founder>'s own voice", and that name is the deployment's,
#: not the package's. `automation/export_voice_loop.py` refuses to publish an engine file
#: carrying it, which is the guard doing its job: a fleet package that hardcodes one
#: operator's name writes every other operator's posts in the wrong voice.
#:
#: It is threaded rather than laundered through the exporter's RENAMES table on purpose.
#: A rename would leave the private copy naming him and the public copy not, so the file
#: that runs and the file that ships would differ on the one line that tells the model
#: whose voice to keep. The deployment passes its own name and the live prompt is
#: byte-identical to what it was.
DEFAULT_AUTHOR = "the author"


def build_prompt(text, violations, author=None):
    """The instruction: surgical, violation-by-violation, no invention."""
    lines = []
    for v in violations:
        rule = v.get("rule", "unknown")
        guidance = RULE_GUIDANCE.get(rule, "fix exactly what the check describes")
        lines.append(f"- [{rule}] {v.get('detail', '')}\n  How to fix: {guidance}")
    failures = "\n".join(lines)

    # The preservation rule is CONDITIONAL, because for one class of violation it is
    # the thing preventing the fix. Printing both sentences was the defect: the reviser
    # was handed "shorten this" and "change no words" in the same breath and could only
    # return the text unchanged, which the gate then rejected again, for the full
    # attempt budget, on every candidate in the supply.
    if any(v.get("rule") in REWRITE_RULES for v in violations):
        # PRECEDENCE, stated explicitly, because deleting the global line only moved
        # the contradiction (adversarial round 2). The per-rule guidance for the OTHER
        # violations still says the opposite in its own words -- `marketer-ending` says
        # "replace the FINAL sentence only. Leave every other sentence exactly as it
        # is", and that rule co-occurs with x-too-long on 10 of the 29 real X bodies.
        # So the prompt still held two instructions that cannot both be obeyed on 34%
        # of the supply; it had just moved from the RULES block into FAILED CHECKS.
        #
        # Naming the winner is the fix. Silently rewriting each rule's guidance would
        # mean maintaining two copies of every rule, which is the divergence the
        # single-source rules in this file already forbid.
        preserve = (
            "- You MAY cut, reorder and rewrite as much as the length needs. Keep the "
            "VOICE and\n  the central claim; keep every number you keep the sentence "
            "for. Length is the one\n  thing you must change.\n"
            "- WHERE A CHECK BELOW SAYS TO LEAVE OTHER TEXT ALONE, THE LENGTH RULE "
            "WINS. Obey the\n  other check's INTENT (what it wants the post to stop "
            "doing) and ignore its\n  instruction to preserve everything else.")
    else:
        preserve = ("- Keep every other word, the order, the line breaks and the voice "
                    "exactly as they are.")

    return f"""You are editing ONE post already written in {author or DEFAULT_AUTHOR}'s own voice.
It failed specific deterministic checks. Fix ONLY those failures.

RULES:
{preserve}
- Never invent facts, numbers, sources or names. If a fix needs information the draft
  does not contain and the guidance offers no restatement, output NOTHING at all.
- No emdashes. Real capitalization. Contractions for negations.
- Output ONLY the corrected post text. No preamble, no explanation.

FAILED CHECKS (fix each, change nothing else):
{failures}

POST:
{text}
"""


def _run_prompt(prompt, claude_bin=None, timeout=TIMEOUT_SECONDS, runner=None,
                model=None):
    """One bounded model call. Same chokepoint contract as the writer's."""
    if runner is not None:
        return runner(prompt)
    # A suite must never spend a real model call (slow, costs money, non-deterministic).
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "revise reached the live model from inside a test. Inject `runner=`.")
    # BOTH DEPLOYMENT VALUES ARE REQUIRED, and the checks sit exactly here, after both
    # short-circuits, for the reason `prompt_render.run_model` records at the same spot:
    # a caller with a runner never shells anything, and a caller inside pytest must get
    # the spend guard's error rather than this one. Only a real call needs a real path.
    #
    # They are arguments and not module constants because this file ships fleet-wide.
    # `~/.local/bin/claude` is one machine's filesystem and "claude-opus-4-8" is one
    # operator's tier choice; either as a default here would be that operator's setup
    # shipped to everybody, which is what drift_check.probe_unisolated_live_paths
    # refuses. The deployment holds both and passes them in.
    if not claude_bin:
        raise ValueError(
            "revise needs an explicit claude_bin; the engine has no default binary "
            "because a default would be one machine's path shipped fleet-wide")
    if not model:
        raise ValueError(
            "revise needs an explicit model; the engine has no default tier because "
            "the writer's tier is the operator's choice, not the package's")
    binary = claude_bin
    if not os.path.exists(binary):
        return None
    try:
        # THE REVISER WRITES, so it gets the writer's tier (2026-08-13). It edits a post
        # that is already in his voice and must not flatten it; that is the same
        # cross-source judgment the writer needs, not the cheap comparison a critic does.
        result = subprocess.run([binary, "--model", model, "-p", prompt],
                                capture_output=True,
                                text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def revise(text, violations, claude_bin=None, timeout=TIMEOUT_SECONDS, runner=None,
           model=None, author=None):
    """Return the revised post, or None. None is a discard upstream, never a hold."""
    out = _run_prompt(build_prompt(text, violations, author=author), claude_bin, timeout,
                      runner, model=model)
    out = prompt_render.strip_preamble(out or "")
    if not out:
        return None
    # A model that echoed the prompt scaffolding back is a failure, not a revision.
    if "FAILED CHECKS" in out or "POST:" in out:
        return None
    return out


def reviser(claude_bin=None, runner=None, model=None, author=None):
    """A `regenerate(text, violations)` callable for `decide.decide_candidate`.

    `_revise` calls the MODULE-LEVEL `revise`, resolved in this module's globals at call
    time. That is deliberate and it is load-bearing: a suite patches `revise.revise` to
    steer the repair ladder without spending a model call, and the patch only lands
    because the name the closure reads and the name the test sets are the same one.
    """
    def _revise(text, violations):
        return revise(text, violations, claude_bin=claude_bin, runner=runner,
                      model=model, author=author)
    return _revise
