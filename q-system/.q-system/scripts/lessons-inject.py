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

  It also does not make read-first-gate redundant. That gate is a PreToolUse
  BLOCKING check on write targets; this is an additive UserPromptSubmit path.
  Different surfaces. In particular sp-6ff00dd5 (a subagent that DID open both
  files is still blocked on a gated target) stays a live defect there and is not
  addressed here.

Contract: UserPromptSubmit hook, hook JSON on stdin, JSON on stdout with
hookSpecificOutput.additionalContext (the shape voice-dna-loader.py uses).
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
MIN_TERM_LEN = 4

# Engineering intent. Deliberately NOT "every prompt": this costs real tokens on
# every firing, and a hook that fires on "what is the weather" is a tax with no
# signal. A MISSED engineering prompt costs nothing -- the SessionStart titles are
# still there -- so this errs narrow on purpose.
TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"fix|fixing|build|building|implement|design|designing|debug|refactor|harden|"
    r"wire|wiring|ship|patch|migrate|migration|schema|script|deploy|commit|merge|"
    r"gate|gates|hook|hooks|test|tests|guard|lint|linter|validator|detector|"
    r"selector|allowlist|timeout|budget|bug|defect|broken|failing|fails|regress\w*|"
    r"rca|root cause|postmortem|corpus|reproducer|mutation"
    r")\b"
)

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
    prompt = payload.get("prompt") or ""
    if not prompt.strip() or not TRIGGER_RE.search(prompt):
        return 0

    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    lessons_dir = get_qroot(root) / "lessons"
    if not lessons_dir.is_dir():
        return 0

    lessons = []
    for p in sorted(lessons_dir.glob("*.md")):
        parsed = parse_lesson(p)
        if not parsed:
            continue
        lid, title, body = parsed
        if not body:
            continue
        lessons.append((lid, title, body, terms(title + " " + body)))
    if not lessons:
        return 0

    picked = rank(lessons, terms(prompt))[:TOP_K]
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
    parts, used = [header], len(header)
    for score, lid, title, body in picked:
        chunk = f"\n=== [{lid}] {title}  (relevance {score:.1f}) ===\n\n{body}\n"
        if used + len(chunk) > PAYLOAD_CEILING_CHARS:
            break
        parts.append(chunk)
        used += len(chunk)
    if len(parts) == 1:
        return 0

    # hookEventName is REQUIRED, not optional. Claude Code silently DISCARDS
    # a hook payload whose hookSpecificOutput carries no hookEventName --
    # measured 2026-08-30 by probe_hook_envelope.py, three headless runs with
    # a positive control; the published docs say optional and are wrong. This
    # hook emitted the nameless shape from the day it was written, so nothing
    # it injected ever reached the model, and no downstream gate could see it:
    # they all measure the OUTPUT, none check that the INPUT arrived.
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "".join(parts),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
