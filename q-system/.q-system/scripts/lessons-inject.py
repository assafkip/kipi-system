#!/usr/bin/env python3
"""lessons-inject: put the RELEVANT lesson bodies in front of the model, so
reading the corpus is not something anyone has to remember to do.

UserPromptSubmit hook. Never blocks: exit 0 always, emits nothing on any error.

WHY (2026-08-29):
  A session was handed 155 lesson TITLES by the SessionStart index hook
  (q-system/hooks/lessons-index.py), treated that injection as delivery, opened
  none of them, and then hit a scar that one of those lessons describes exactly.
  The response was a sentence in chat -- "going forward I'll read the corpus
  before designing" -- which no hook, test or gate can hold.

  The fix is NOT to detect the sentence. A Stop-hook detector on commitment
  language was designed, measured and rejected the same day, for a reason worth
  keeping written down: its cheapest compliance path is deleting the sentence.
  The promise then becomes unstated and equally unkept, and the one signal that
  made the failure catchable is gone. Measured over 9,800 local transcripts and
  50,296 turn-final assistant messages: 295 raw matches, of which 218 (74%) were
  retrospective or instructional rather than a commitment. True commitment
  language ran about 1.7 per 1000 turn-final messages.

  So: remove the need for the promise instead of policing it. You cannot promise
  to read what is already in front of you.

WHY BODIES AND NOT TITLES:
  Titles were the original failure. "Emission into context was treated as
  delivery" entered context as a title nobody opened. A title is a pointer; the
  scar lives in the body.

WHY SELECTED AND NOT THE WHOLE CORPUS:
  The corpus is 375,528 bytes across 155 files. voice-dna-loader.py carries the
  measured result of the opposite choice: a 40KB fixed dump made output WORSE.
  This ships a few thousand characters, chosen against the actual prompt.

WHY RANKING IS DEFENSIBLE HERE, given lessons-index.py rejected it:
  That file declines to rank and is right to: "a wrong rank looks identical to a
  right one and fails silently." But it runs at SessionStart, where there is NO
  QUERY -- ranking against nothing is arbitrary by construction. This hook runs at
  UserPromptSubmit, where the prompt IS the query.
  Second half of the answer: this hook is ADDITIVE. The SessionStart index still
  injects all 155 titles. A wrong rank here costs a few thousand characters and
  loses nothing, because the full index is still in the same context. The failure
  mode of a bad rank is today's behavior, not worse.

HONEST BOUNDARY (the part people skip):
  This proves the lesson text ENTERED CONTEXT. It cannot prove it was read, that
  the right lessons were selected for the intent, or that it changed the work that
  followed. It is strictly stronger than a promise, because a promise leaves no
  artifact at all and this puts the actual words in front of the model every time
  the trigger fires. It is strictly weaker than proof of application, and nothing
  here should be read as claiming otherwise. Term overlap is a crude selector: it
  will miss a lesson whose vocabulary differs from the prompt's even when that
  lesson is the relevant one, and the miss is SILENT.
  What it does NOT do: fire on prompts with no engineering intent, rank at
  SessionStart, or block anything.

  AND IT STOPS. There is a per-session budget (SESSION_CEILING_CHARS), so a long
  session gets roughly a dozen lessons and then silence -- not because nothing is
  relevant, but because term overlap past that point is selecting from what is
  left rather than from what fits. An earlier draft of this docstring promised
  the bodies "every time the trigger fires", which the budget contradicts on
  about the fifth engineering prompt (Codex minor, PR #277). The SessionStart
  title index remains the authority on what exists, and it is not budgeted.

  It also does not make read-first-gate redundant. That gate is a PreToolUse
  BLOCKING check on write targets; this is an additive UserPromptSubmit path.
  Different surfaces. In particular sp-6ff00dd5 (a subagent that DID open both
  files is still blocked on a gated target) stays a live defect there and is not
  addressed here.

Contract: UserPromptSubmit hook, hook JSON on stdin, JSON on stdout with
hookSpecificOutput.{hookEventName, additionalContext} -- BOTH keys; see the
note at the emit for why the second one is not optional.
Self-test: python3 test_lessons_inject.py. stdlib only.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

TOP_K = 3
PAYLOAD_CEILING_CHARS = 12000

# PER SESSION, across every firing. Codex major, PR #277.
#
# The dedupe alone made this worse, not better. Before it, a long session got the
# SAME three lessons over and over -- wasteful, but bounded. After it, every turn
# brought three NEW ones, so a long session walked the entire corpus into
# context: measured at 394,822 chars against a 375,528-byte corpus, with
# relevance decaying to noise long before the end.
#
# Both failures are the same missing thing: a budget. 40k chars is roughly ten
# thousand tokens, and about a dozen lessons -- past that, term overlap is
# selecting from what is left rather than from what is relevant, and the header
# already tells the model the SessionStart title index is the authority on what
# exists. Spending the budget is not an error and says so.
SESSION_CEILING_CHARS = 40000
MIN_TERM_LEN = 4

# Engineering intent. Deliberately NOT "every prompt": this costs real tokens on
# every firing, and a hook that fires on "what is the weather" is a tax with no
# signal. A MISSED engineering prompt costs nothing -- the SessionStart titles are
# still there -- so this errs narrow on purpose.
# FOUR WORDS REMOVED (Codex minor, PR #277): design, designing, ship, budget.
# The docstring above promises this does not fire on prompts with no engineering
# intent, and those four have strong non-engineering senses in this founder's own
# work -- design is brand and visual design, ship is publishing content, budget is
# money. They made the docstring false. merge/commit/patch stay: they have no
# common non-engineering reading here.
#
# The COST argument for narrowing is separately handled by the per-session dedupe
# below, which is the better lever: it makes a second firing on the same lesson
# free rather than making the first firing rarer.
TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"fix|fixing|build|building|implement|debug|refactor|harden|"
    r"wire|wiring|patch|migrate|migration|schema|script|deploy|commit|merge|"
    r"gate|gates|hook|hooks|test|tests|guard|lint|linter|validator|detector|"
    r"selector|allowlist|timeout|bug|defect|broken|failing|fails|regress\w*|"
    r"rca|root cause|postmortem|corpus|reproducer|mutation"
    r")\b"
)


def _seen_path(session_id):
    """Per-session record of which lessons have already been injected.

    In the system temp dir, never the repo: this is ephemeral per-machine state
    and writing it under the project would put a file on every prompt into a
    tree that unattended jobs commit with `git add -A`.
    """
    import tempfile
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))[:120]
    if not safe:
        return None
    return Path(tempfile.gettempdir()) / "kipi-lessons-inject" / (safe + ".json")


def load_seen(session_id):
    """(already-injected ids, chars spent so far) for this session.

    NO SESSION ID, NO DEDUPE AND NO BUDGET. The first version fell back to a
    single "nosession" key, which is a GLOBAL record shared by every caller that
    omits the field -- so a second run saw the first run's lessons as already
    injected and stayed silent. Found by this file's own suite going 7/8 then
    5/8 on identical input: a dedupe scoped wider than a session makes the thing
    it dedupes disappear.

    Reads the legacy list shape too, so a record written by the previous version
    does not read as corrupt and reset a live session's budget to zero.
    """
    path = _seen_path(session_id)
    if path is None:
        return set(), 0
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, list):          # the shape before the budget existed
            return set(raw), 0
        return set(raw.get("ids") or []), int(raw.get("chars") or 0)
    except Exception:
        # No record, unreadable record, corrupt record: all mean "inject". This
        # fails OPEN on purpose. The failure mode of a broken dedupe must be a
        # repeated injection, never a silent nothing -- the whole point of this
        # hook is that the words reach the model.
        return set(), 0


def save_seen(session_id, ids, chars):
    p = _seen_path(session_id)
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ids": sorted(ids), "chars": int(chars)}))
        _prune(p.parent)
    except OSError:
        pass


def _prune(d, max_age_seconds=48 * 3600):
    """Drop records older than two days. Nothing else prunes this directory.

    Codex nit, PR #277: 31 files accumulated in two minutes of testing, and no
    pruner existed anywhere in the repo. A session's record is worthless once
    that session is over, and the temp dir is not somebody else's problem just
    because it is outside the repo. Best-effort and silent: a failed prune must
    never cost an injection.
    """
    import time
    cutoff = time.time() - max_age_seconds
    try:
        for f in d.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass

STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "would", "should", "could",
    "there", "their", "them", "then", "than", "what", "when", "which", "while",
    "your", "yours", "about", "into", "over", "some", "just", "like", "make",
    "made", "does", "done", "here", "been", "being", "were", "want", "need",
    "also", "very", "much", "more", "most", "only", "same", "such", "each",
    "because", "before", "after", "again", "still", "even", "back", "down",
}


def terms(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(w) >= MIN_TERM_LEN and w not in STOPWORDS:
            out.add(w)
    return out


def get_qroot(project_dir):
    # Mirrors lessons-index.py get_qroot: some instances carry a nested subtree.
    if (project_dir / "q-system" / "q-system" / "canonical").exists():
        return project_dir / "q-system" / "q-system"
    return project_dir / "q-system"


def parse_lesson(path):
    """(id, title, body) or None. Frontmatter shape matches the lessons corpus."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    lid, title, body = path.stem, path.stem, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip().lower(), v.strip()
                if k == "id" and v:
                    lid = v
                elif k == "title" and v:
                    title = v
            body = text[end + 4:]
    return lid, title, body.strip()


def rank(lessons, query):
    """Term overlap with inverse-document-frequency weighting.

    IDF is not polish at this corpus size: 'gate', 'test' and 'hook' appear in most
    of the 155 lessons, so UNWEIGHTED overlap ranks by how common a word is rather
    than how discriminating it is. Title hits count triple -- a lesson's title is
    its thesis. Zero-score lessons are dropped, not ranked last: shipping an
    unrelated lesson is the noise this hook exists to avoid.
    """
    n = len(lessons)
    df = {}
    for _lid, _t, _b, tset in lessons:
        for w in tset:
            df[w] = df.get(w, 0) + 1
    scored = []
    for lid, title, body, tset in lessons:
        title_terms = terms(title)
        score = 0.0
        for w in query:
            if w not in tset:
                continue
            idf = math.log((n + 1) / (df.get(w, 0) + 1)) + 1.0
            score += idf * (3.0 if w in title_terms else 1.0)
        if score > 0:
            scored.append((score, lid, title, body))
    # Sort by score then id, so ties are stable and not filesystem order.
    scored.sort(key=lambda r: (-r[0], r[1]))
    return scored


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        # `4`, `"x"` and `[]` are all valid JSON and none of them has .get.
        # The docstring promises exit 0 and no output on any error; without this
        # they exited 1 with an AttributeError traceback (Codex nit, PR #277).
        return 0
    prompt = payload.get("prompt") or ""
    if not prompt.strip() or not TRIGGER_RE.search(prompt):
        return 0

    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    lessons_dir = get_qroot(root) / "lessons"
    if not lessons_dir.is_dir():
        return 0

    lessons = []
    for p in sorted(lessons_dir.glob("*.md")):
        # README.md is the corpus's own authoring instruction, not a lesson.
        # It out-ranked real lessons on any lessons-related prompt because its
        # vocabulary IS the corpus vocabulary (Codex minor, PR #277).
        # lessons-index.py already excludes it by the same name check; this is
        # the second reader of that directory agreeing with the first.
        if p.name == "README.md":
            continue
        parsed = parse_lesson(p)
        if not parsed:
            continue
        lid, title, body = parsed
        if not body:
            continue
        lessons.append((lid, title, body, terms(title + " " + body)))
    if not lessons:
        return 0

    # CROSS-TURN DEDUPE (Codex minor, PR #277). Without it a byte-identical
    # payload was re-injected every turn: measured at 48KB across six turns of
    # one session, for zero added information after the first.
    #
    # Keyed on the lesson ID, not the payload hash: the point is that the model
    # has already been shown this lesson's TEXT in this session, and that stays
    # true even when a later prompt would have ranked it differently.
    session_id = payload.get("session_id") or ""
    seen, spent = load_seen(session_id)
    if session_id and spent >= SESSION_CEILING_CHARS:
        # Budget spent. Silent by design: the SessionStart title index is still
        # there and is the authority on what exists, which the payload header
        # says every time. Continuing past here is how three relevant lessons
        # become a hundred and fifty irrelevant ones.
        return 0
    ranked = rank(lessons, terms(prompt))
    picked = [r for r in ranked if r[1] not in seen][:TOP_K]
    if not picked:
        return 0

    header = (
        "[lessons-inject] Relevant entries from the lessons corpus, selected against "
        "this prompt and included IN FULL below. These are not titles to look up; the "
        "text is here.\n"
        "Scar 2026-08-29: a session was given 155 lesson titles, treated the injection "
        "as delivery, opened none, and repeated a documented failure. Selection is term "
        "overlap and is crude: it can MISS the relevant lesson silently, so the full "
        "title index from SessionStart remains the authority on what exists.\n"
    )
    parts, used, shown = [header], len(header), []
    for score, lid, title, body in picked:
        chunk = f"\n=== [{lid}] {title}  (relevance {score:.1f}) ===\n\n{body}\n"
        if used + len(chunk) > PAYLOAD_CEILING_CHARS:
            # SKIP IT, do not stop (Codex minor, PR #277). `break` meant one
            # oversized top-ranked lesson returned the header alone -- and since
            # `len(parts) == 1` then returns 0 without recording anything, that
            # same lesson ranked first again next turn and blocked the smaller,
            # equally relevant ones behind it for the whole session. Permanent
            # starvation caused by one long file.
            continue
        parts.append(chunk)
        used += len(chunk)
        shown.append(lid)
    if not shown:
        return 0

    # Record what was actually SHOWN, collected as each chunk is appended.
    #
    # It used to slice `picked[:len(parts) - 1]`, which is only correct while the
    # loop above stops at the first oversized lesson. Changing that `break` to a
    # `continue` broke the positional assumption in the same commit and neither
    # the comment nor any case noticed (Codex minor, PR #277 round 4): skip the
    # first of three and the slice records the SKIPPED one as shown -- silently
    # suppressing it for the rest of the session -- while the third, which really
    # was shown, goes unrecorded and gets re-injected next turn. Both halves
    # wrong, from one stale index.
    #
    # A list appended beside the payload cannot drift from it, because there is
    # no longer a second thing to keep in sync.
    save_seen(session_id, seen | set(shown), spent + used)

    # hookEventName IS PART OF THE ENVELOPE (Codex major, PR #277). Without it
    # the payload is discarded and not one word of any lesson reaches the model,
    # which makes this whole hook an expensive no-op that looks like it is
    # working: it fires, it ranks, it writes to stdout, and nothing arrives.
    #
    # This repo already recorded the shape and the scar. token-guard.py:1046
    # carries it verbatim -- "must be nested under hookSpecificOutput with
    # hookEventName; a top-level additionalContext key is silently ignored by
    # Claude Code, which left every warning tier invisible until 2026-07-02".
    # Every emitter here that is known to deliver includes the key.
    #
    # The docstring said this copies voice-dna-loader.py's shape, and it does --
    # including that file's omission of the same key. Copying a shape is not
    # checking it. voice-dna-loader.py has the identical defect and is captured
    # separately rather than widened into this PR.
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "".join(parts),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
