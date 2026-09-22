#!/usr/bin/env python3
"""Deterministic repair of a draft BEFORE the voice gate sees it.

why this exists (2026-08-05, ASK-407): the content engine stopped shipping because
`check_capitalization()` blocks on a lowercase sentence start, and three live incidents
tripped it on tokens whose CORRECT spelling is lowercase -- the tool names `ratchet` and
`acontext`, and lines starting `https://`. The regenerate loop asked a model to "fix"
correct names three times and fail-closed. Three failures, nothing shipped.

**A gate that can only be cleared by producing something wrong is not a gate, it is a
stop.** This module is the missing layer: it repairs what is genuinely wrong and PROTECTS
what is genuinely right, deterministically, before any model is asked to regenerate.

The layering it belongs to (PRD prd-content-engine-2026-08-04):

    deterministic repair (here) -> gate -> bounded LLM regenerate -> terminal action

Two design rules, both load-bearing:

1. **It imports the linter's own helpers rather than reimplementing them.** If this module
   had its own idea of where a sentence starts, the repairer and the gate would drift and
   the drift would look like a flaky gate. The linter is the single source of truth for
   what a violation IS; this module only decides what to DO about one.
2. **A token whose correct form is lowercase is never recapitalized.** It is wrapped in
   backticks instead, which is both correct markdown and the thing that makes the linter
   skip it (`INLINE_CODE_RE` -> `__CODE__`). The repair makes the text MORE correct, never
   less, which is why it is safe to run unattended.

Scope (widened 2026-08-05, founder-directed): every violation whose fix is a pure
textual transform with exactly one correct answer. Capitalization, emdashes, slash
commands, non-contracted negations, the safe banned-word substitutions, and the pure
transition adverbs. The founder's rule, verbatim: "you dont need to kill posts that have
a fail, just fix the fail if possible. you are narrowing your own set by killing a full
post over capitalization." Anything needing the text's MEANING (a stat's source, a
mechanism, a rephrase) goes to the bounded targeted revision in `revise.py` instead;
this module must never guess at meaning, because a deterministic layer that guesses is
a second voice system wearing a script.
"""
from __future__ import annotations

import functools
import importlib.util
import os
import re

# NO PATH CONSTANTS LIVE HERE, deliberately (2026-09-05, package extraction slice 3b).
#
# This module used to resolve four files from __file__: a verbatim-lowercase
# allowlist, a banned-word repair map, an extra banned-phrase list, and the voice
# linter script itself. Inside one deployment that is correct and invisible. Inside
# a package that ships fleet-wide it silently points every operator at whichever
# files happen to sit beside the code, which is the failure `voice_ref` already
# refuses by carrying no default corpus at all, and which `experience.match` refuses
# by taking its corpus directory as a required argument.
#
# So every loader below takes its path, and every entry point takes its data. There
# is no default and no fallback: a caller that forgets is a TypeError at the call
# site, never a silent read of the wrong operator's config. The deployment half is
# the deployment's own `pipeline/post_repair.py`, which binds all four and keeps
# the old signatures, so that not one caller changed in this slice.

# A bare URL or a path-like token is self-evidently verbatim; it needs no allowlist entry.
_URL_RE = re.compile(r"^(?:https?://|www\.|[\w.-]+/)", re.I)
_PATHY_RE = re.compile(r"^[\w-]+(?:\.[a-z]{1,4}\b|/|_)")

# THE DOUBLE DASH IS OUT OF POSTS TOO (founder-directed 2026-08-13, verbatim: "the
# post I liked had -- which is against the rules"). " -- " remains the house form
# for DOCS (CLAUDE.md language rules, unchanged); a published post carries neither
# the emdash nor its substitute. Measured before wiring, per the word-list scar:
# 0 of his 28 real X posts and 0 of his 19 writing samples use "--"; the only 5
# corpus hits are March-2026 LinkedIn drafts. An emdash therefore repairs to a
# comma (one correct answer stays one correct answer); an existing " -- " has no
# single correct replacement (comma, period, or recast), so it BLOCKS and routes
# to the reviser like a banned word.
_EMDASH_RE = re.compile(r"[ \t]*—[ \t]*")
_DOUBLE_DASH_RE = re.compile(r"(?<![-\w])--(?![-\w])")

# `/q-foo` inside backticks trips the slash-command rule; the same token without the
# slash does not, and reads identically in prose ("run `q-assess`"). Meaning preserved.
_SLASH_CMD_RE = re.compile(r"`/(q-[a-z][a-z0-9-]*)`")

# Every non-contracted negation the linter flags has exactly one contracted form.
CONTRACTIONS = {
    "do not": "don't", "does not": "doesn't", "did not": "didn't",
    "is not": "isn't", "are not": "aren't", "was not": "wasn't",
    "were not": "weren't", "have not": "haven't", "has not": "hasn't",
    "had not": "hadn't", "will not": "won't", "would not": "wouldn't",
    "could not": "couldn't", "should not": "shouldn't", "must not": "mustn't",
    "can not": "can't", "cannot": "can't",
}

# Banned transition adverbs that open a sentence carry no meaning at all; deleting them
# is the fix, not a rephrase. Mid-sentence occurrences go to the revision layer instead.
_TRANSITION_OPENER_RE = re.compile(
    r"(^|(?<=[.!?] ))[ \t]*(?:furthermore|moreover|additionally),\s+([a-zA-Z])",
    re.I | re.M)


def _load_linter(linter_path):
    """Import voice-lint.py by path. It is a script, not a package."""
    spec = importlib.util.spec_from_file_location("voice_lint", linter_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_verbatim_lowercase(path):
    """Tokens that must keep their lowercase spelling. Missing file = empty set.

    Empty is the SAFE degradation: with no allowlist every lowercase sentence start gets
    capitalized, which is the old behaviour and merely wrong, not dangerous. The negative
    self-test asserts the allowlist is load-bearing by proving the tool names get mangled
    without it.
    """
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            token = line.split("#", 1)[0].strip()
            if token:
                out.add(token.lower())
    return out


def is_verbatim(word, allowlist):
    """Is this token's lowercase form the CORRECT form?"""
    return (word.lower() in allowlist
            or bool(_URL_RE.match(word))
            or bool(_PATHY_RE.match(word)))


def load_banned_word_repairs(path):
    """`banned -> replacement` pairs, one per line. Missing file = empty dict.

    Empty is the SAFE degradation: an unmapped banned word is not guessed at, it goes to
    the bounded revision with the violation named. Only 1:1 meaning-free substitutions
    belong in this file; 'leverage' is NOT here because it is a legitimate noun.
    """
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if "->" not in line:
                continue
            banned, _, repl = line.partition("->")
            if banned.strip() and repl.strip():
                out[banned.strip().lower()] = repl.strip()
    return out


def _match_case(replacement, seen):
    """Carry the original token's casing onto its replacement."""
    if seen.isupper() and len(seen) > 1:
        return replacement.upper()
    if seen[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _protected_spans(text, linter):
    """(start, end) spans the repairer must never rewrite: code fences, inline code,
    frontmatter. The linter's own regexes define them, so repairer and gate agree on
    what is code. Rewriting inside a fence would 'fix' working commands (recon scar F9:
    cole's --fix call rewrote nothing but CLAIMED to; ours must rewrite only prose)."""
    spans = []
    front = linter.FRONTMATTER_RE.search(text)
    if front:
        spans.append(front.span())
    for regex in (linter.CODE_FENCE_RE, linter.INLINE_CODE_RE):
        spans.extend(match.span() for match in regex.finditer(text))
    return spans


def _sub_outside_code(pattern, repl, text, linter):
    """pattern.sub(repl, text), skipping protected spans. Returns (text, count)."""
    spans = _protected_spans(text, linter)
    count = 0

    def _apply(match):
        nonlocal count
        if any(start <= match.start() < end for start, end in spans):
            return match.group()
        count += 1
        return repl(match) if callable(repl) else repl

    return pattern.sub(_apply, text), count


def repair_emdash(text, linter):
    """`—` -> a comma. Posts carry neither the emdash nor " -- " (2026-08-13)."""
    repaired, count = _EMDASH_RE.subn(", ", text)
    repaired = repaired.replace(" ,", ",").replace(",\n", ",\n")
    changes = [f"emdash -> ',' x{count}"] if count else []
    return repaired, changes


def repair_slash_commands(text, linter):
    """`/q-foo` -> `q-foo`. The slash is the violation; the name is the meaning."""
    repaired, count = _SLASH_CMD_RE.subn(r"`\1`", text)
    changes = [f"dropped slash from slash-command x{count}"] if count else []
    return repaired, changes


def repair_contractions(text, linter):
    """Non-contracted negations -> their one contracted form, prose only.

    A deliberately shouted 'NOT' ("do NOT ship this") is emphasis, not a violation the
    founder wants smoothed away, so mixed-case matches are left for a human eye.
    """
    changes = []
    for long_form, short_form in CONTRACTIONS.items():
        pattern = re.compile(r"\b" + long_form.replace(" ", r"\s+") + r"\b", re.I)

        def _fix(match, short=short_form):
            seen = match.group()
            if "NOT" in seen and not seen.isupper():
                return seen
            return _match_case(short, seen)

        text, count = _sub_outside_code(pattern, _fix, text, linter)
        if count:
            changes.append(f"'{long_form}' -> '{short_form}' x{count}")
    return text, changes


def repair_banned_words(text, linter, mapping):
    """Only the config-mapped 1:1 substitutions. Everything else is a revision job."""
    changes = []
    for banned, replacement in mapping.items():
        pattern = re.compile(r"\b" + re.escape(banned) + r"\b", re.I)
        text, count = _sub_outside_code(
            pattern, lambda m, r=replacement: _match_case(r, m.group()), text, linter)
        if count:
            changes.append(f"banned word '{banned}' -> '{replacement}' x{count}")
    return text, changes


def repair_transition_openers(text, linter):
    """Sentence-initial 'Furthermore,' / 'Moreover,' / 'Additionally,' -> deleted.

    These are banned words whose only job is filler. The sentence they open is complete
    without them, so deletion (plus re-capitalizing the real first word) IS the fix.
    """
    text, count = _sub_outside_code(
        _TRANSITION_OPENER_RE, lambda m: m.group(1) + m.group(2).upper(), text, linter)
    changes = [f"dropped transition opener x{count}"] if count else []
    return text, changes


def repair(text, allowlist, linter, mapping):
    """Return (repaired_text, [what changed]). Pure: never touches disk.

    Order matters. Bare `i` is fixed first because it is unambiguous, then sentence
    starts, then proper nouns. Each pass re-derives offsets from the linter against the
    CURRENT text, so an earlier repair never invalidates a later offset.
    """
    changes = []

    # 0. The pure textual transforms, before any offset-based work: each has exactly one
    #    correct output, so ordering among them cannot matter, but they must precede the
    #    sentence-start pass because deleting a transition opener moves sentence starts.
    # `repair_banned_words` is bound to the caller's mapping before the loop, so the
    # loop keeps its one uniform call shape. Reordering these is not free: each has
    # exactly one correct output, but all of them must precede the sentence-start
    # pass, because deleting a transition opener moves sentence starts.
    banned_words = functools.partial(repair_banned_words, mapping=mapping)
    for fix in (repair_emdash, repair_slash_commands, repair_transition_openers,
                banned_words, repair_contractions):
        text, made = fix(text, linter)
        changes.extend(made)

    # 1. bare 'i' -> 'I'. Always correct, no exceptions, so it needs no allowlist check.
    repaired, count = linter.BARE_I_RE.subn(lambda m: m.group().replace("i", "I"), text)
    if count:
        changes.append(f"bare 'i' -> 'I' x{count}")

    # 2. Lowercase sentence starts. Capitalize a real word; BACKTICK a verbatim token.
    #    Offsets come from the linter's prose view, so they are indices into the STRIPPED
    #    text, not the raw text. Repair by locating the token in the raw text instead,
    #    which is why this walks matches rather than splicing by offset.
    for _ in range(10):  # bounded: each pass fixes at least one or breaks
        prose = linter.strip_code_preserving_lines(repaired)
        target = None
        for offset in linter._sentence_start_offsets(prose):
            token = re.match(r"[A-Za-z][\w'-]*", prose[offset:])
            if not token or token.group() == "__CODE__" or token.group()[0].isupper():
                continue
            target = token.group()
            break
        if target is None:
            break

        if is_verbatim(target, allowlist):
            pattern = re.compile(r"(?<![`\w])" + re.escape(target) + r"(?![`\w])")
            repaired, n = pattern.subn(f"`{target}`", repaired, count=1)
            if not n:
                break
            changes.append(f"protected verbatim token '{target}' with backticks")
        else:
            pattern = re.compile(r"(?<![`\w])" + re.escape(target) + r"(?![`\w])")
            repaired, n = pattern.subn(target[0].upper() + target[1:], repaired, count=1)
            if not n:
                break
            changes.append(f"capitalized sentence start '{target}'")

    # 3. Proper nouns miscased against the linter's own list, in its canonical spelling.
    for noun in linter.load_proper_nouns(""):
        pattern = re.compile(r"\b" + re.escape(noun).replace(r"\ ", r"\s+") + r"\b", re.I)

        def _fix(match):
            seen = match.group()
            return seen if (seen == noun or seen.isupper()) else noun

        repaired, n = pattern.subn(_fix, repaired)
        if n and noun not in text:
            changes.append(f"proper noun -> '{noun}'")

    return repaired, changes


def capitalization_violations(text, linter):
    """Only the capitalization verdict. Used to prove the REPAIR worked."""
    return linter.check_capitalization(text)



def instance_banned_phrases(path):
    """The instance's own banned phrases. [] when the file is missing.

    Silent without the file, `figure_gate`'s posture: every caller written before this
    sees no change, and a moved config costs one check rather than the whole run.
    `test_post_repair_instance_phrases.py` asserts the live file is present and carries
    its entries, so the degraded path cannot become the quiet normal.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.lower())
    return out


def check_instance_banned_phrases(text, path):
    """Violations for any instance-local banned phrase present in `text`.

    Emits rule `banned-phrase`, the SAME name the skeleton linter uses, on purpose: the
    reviser's `RULE_GUIDANCE["banned-phrase"]` already knows how to repair one, and a new
    rule name would fall through to the generic "fix exactly what the check describes"
    that starved slots the last time a rule arrived without guidance.
    """
    lowered = (text or "").lower()
    return [{"rule": "banned-phrase", "line": 1,
             "detail": f"banned phrase: {phrase!r}"}
            for phrase in instance_banned_phrases(path) if phrase in lowered]


def check_double_dash(text):
    """A published post carries no " -- " (founder-directed 2026-08-13; the emdash's
    doc-substitute is a docs convention, not a post one). Corpus-measured before
    wiring: 0 of 28 real X posts, 0 of 19 writing samples; see the constant above.
    BLOCKS rather than repairs: comma, period, or recast is a meaning call, so the
    reviser makes it with `RULE_GUIDANCE["double-dash"]`."""
    hits = len(_DOUBLE_DASH_RE.findall(text or ""))
    if not hits:
        return []
    return [{"rule": "double-dash", "line": 1,
             "detail": f"the post carries ' -- ' x{hits}. Posts use neither the emdash "
                       f"nor its doc substitute; replace each with a comma, a period, "
                       f"or recast the sentence."}]


def violations(text, linter, phrases_path):
    """EVERY blocking voice rule, not just capitalization.

    why this changed (2026-08-05, found by an adversarial review of the two posts that
    actually went out): this function used to return `check_capitalization` alone. The
    linter has SIXTEEN checks. Banned words, banned phrases, stats-citation, emdashes,
    contractions, hedge density, comma triplets, rule-of-three, sentence uniformity, bold
    restatement, emphasis openers and rhetorical Q&A were all wired to nothing.

    The founder's requirement was "all of the voice lints MUST pass and they must be
    proven to pass deterministically". One of sixteen is not that, and the LinkedIn post
    published today carries a blocking `stats-citation` violation that this gate should
    have caught and did not.

    WARN_RULES are excluded on purpose: the linter itself classes them as non-blocking
    (exit 0 + stderr), and treating a warning as a discard would throw away good posts for
    stylistic preferences. Blocking means blocking; warnings are reported, not enforced.
    """
    all_v = []
    for check, args in ((check_instance_banned_phrases, (text, phrases_path)),
                        (check_double_dash, (text,)),
                        (linter.check_emdash, (text,)),
                        (linter.check_banned_words, (text,)),
                        (linter.check_banned_phrases, (text,)),
                        (linter.check_stats, (text,)),
                        (linter.check_slash_commands, (text,)),
                        (linter.check_contractions, (text,)),
                        (linter.check_capitalization, (text, "")),
                        (linter.check_rule_of_three, (text,)),
                        (linter.check_comma_triplet, (text,)),
                        (linter.check_cross_paragraph_fragments, (text,)),
                        (linter.check_sentence_uniformity, (text,)),
                        (linter.check_hedge_density, (text,)),
                        (linter.check_single_sentence_paragraph, (text,)),
                        (linter.check_bold_restatement, (text,)),
                        (linter.check_emphasis_opener, (text,)),
                        (linter.check_rhetorical_qa, (text,))):
        try:
            all_v.extend(check(*args))
        except Exception as exc:      # a broken check must fail CLOSED, never silently
            all_v.append({"rule": "voice-lint-error", "line": 1,
                          "detail": f"{check.__name__} raised: {exc}"})
    warn = getattr(linter, "WARN_RULES", frozenset())
    return [v for v in all_v if v.get("rule") not in warn]


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: post_repair.py <file>", file=sys.stderr)
        raise SystemExit(2)
    with open(sys.argv[1], encoding="utf-8") as fh:
        original = fh.read()
    fixed, what = repair(original)
    left = violations(fixed)
    for line in what:
        print(f"  repaired: {line}")
    print(f"  blocking violations remaining after repair: {len(left)}")
    raise SystemExit(1 if left else 0)
