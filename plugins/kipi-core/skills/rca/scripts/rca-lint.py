#!/usr/bin/env python3
"""
rca-lint.py — Deterministic RCA / premortem structure enforcer.

Pairs with the rca skill (SKILL.md + references/rca-template.md). Catches RCA
docs that skip required sections, bury action items in prose, assert fixes
without evidence, omit cause-type tags, or name people instead of system
failures.

Usage:
    python3 rca-lint.py <file_path>     # CLI mode
    (no args)                           # hook mode: reads PostToolUse JSON on stdin

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- rca-lint-skip --> anywhere in the file to bypass.

Recurrence check (ASK-2541):
    A new RCA whose root-cause sections match the Action items of an EARLIER
    RCA in the same directory must carry a "## Recurrence" section. That
    section names the earlier file and, per matched action, says which action
    failed and why. See recurrence_matches() for the matcher and its measured
    threshold. RCAs dated before RECURRENCE_CUTOFF are exempt.

Scope:
    Fires only on an actual RCA/premortem document, detected by EITHER:
      - H1 starting with "# RCA:" (colon) or "# Premortem"
      - path under an /output/rca/ directory
    Source files that merely contain "rca" in their name (commands, skills,
    this template) are NOT in scope. Anything else exits 0.
"""

import json
import math
import re
import sys
from pathlib import Path

SKIP_MARKER = "rca-lint-skip"

REQUIRED_RCA_SECTIONS = [
    "What happened",
    "Surface symptom",
    "Surface root cause",
    "Structural root cause",
    "Verification",
    "Contributing factors",
    "Fixes shipped",
    "Action items",
    "Lessons",
]

REQUIRED_PREMORTEM_SECTIONS = [
    "Findings by severity",
    "Recommended fix order",
    "What I did NOT find",
]

CAUSE_TYPES = {
    "code-defect", "config", "environmental-trigger", "missing-test",
    "implicit-contract", "process", "capacity",
}

EVIDENCE_WORDS = re.compile(
    r"\b(ran|got|observed|confirmed|passed|output|exit\s*0|reproduced|green)\b", re.I
)

BLAME_PATTERNS = [
    (re.compile(r"\bto blame\b", re.I), "person-blame phrase 'to blame'"),
    (re.compile(r"\bwhose fault\b", re.I), "person-blame phrase 'whose fault'"),
    (re.compile(r"'s fault\b", re.I), "person-blame phrase \"'s fault\""),
    (re.compile(r"\bhuman error\b", re.I), "blame phrase 'human error' (name the missing guardrail instead)"),
]


def in_rca_output_dir(file_path):
    return "/output/rca/" in str(file_path)


def extract_h1(body):
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return None


def doc_kind(file_path, text):
    """Return 'rca', 'premortem', or None (out of scope).

    Tight on purpose: only a real RCA doc (H1 'RCA:' with colon, or H1
    'Premortem') or a file under an output/rca/ dir is in scope. A source file
    that merely has 'rca' in its name is not."""
    h1 = (extract_h1(text) or "").lower()
    if h1.startswith("premortem"):
        return "premortem"
    if h1.startswith("rca:"):
        return "rca"
    if in_rca_output_dir(file_path):
        name = Path(str(file_path)).name.lower()
        return "premortem" if name.startswith("premortem-") else "rca"
    return None


def headers(text):
    found = set()
    for line in text.splitlines():
        m = re.match(r"#{2,3}\s+(.*?)\s*$", line)
        if m:
            found.add(m.group(1).strip())
    return found


def section_body(text, title):
    lines = text.splitlines()
    out, capturing = [], False
    for line in lines:
        if re.match(r"##\s+", line):
            if capturing:
                break
            if re.match(r"##\s+" + re.escape(title) + r"\s*$", line):
                capturing = True
            continue
        if capturing:
            out.append(line)
    return "\n".join(out)


def header_present(found, title):
    if title in found:
        return True
    low = title.lower()
    return any(h.lower().startswith(low) for h in found)


# --- Recurrence check (ASK-2541) -------------------------------------------
#
# Why: an RCA's root cause (a gate proven by reading source, a scanner with no
# drain, one fresh agent per brief instead of per task) was the earlier RCA's
# own action items failing, and the new RCA only half-said which one failed. A
# recurrence nobody names gets fixed a third time the same way.

# RCAs dated before this day predate the check. Same shape as plan-lint's
# CUTOFF: a gate red on its own existing population gets switched off. Like
# plan-lint it reads the date in the FILENAME (then the **Date:** line), so a
# back-dated filename walks past it.
RECURRENCE_CUTOFF = "2026-10-06"
RECURRENCE_SKIP_MARKER = "rca-recurrence-skip"
# An undated RCA is being written now, so every dated sibling precedes it and
# the cutoff never exempts it (PR 527 review: dropping the date was a hole).
UNDATED = "9999-12-31"

# An action item matches when the rarity-weighted overlap between its terms and
# the new RCA's root-cause terms reaches RECURRENCE_SCORE. An earlier RCA
# counts as recurring when RECURRENCE_MIN_ACTIONS of its actions match.
# Measured 2026-10-06 over three real RCA dirs (33 + 11 + 6 RCAs, every
# earlier pair), sweeping cap x floor x score together: cap 2.5, floor 5,
# score 6.0 flags 4 pairs, keeps the known recurrence, and drops the
# reviewer's false pair (generic hook/guard/setting vocabulary). Floor 4 kept
# that false pair; score 7.0 lost the known recurrence at every cap.
RECURRENCE_SCORE = 6.0
RECURRENCE_MIN_ACTIONS = 2

# Two guards against a bar that loosens as the directory grows (PR 527 review):
# a pair-unique term weighs ln(n+2), so at n=20 two shared identifiers reached
# 6.0 and an unrelated RCA was blocked. The cap bounds one term's weight, and
# the floor needs this many DISTINCT shared terms whatever n is.
RECURRENCE_WEIGHT_CAP = 2.5
RECURRENCE_MIN_SHARED = 5

# A Recurrence line answers an action when it shares this many terms with it.
RECURRENCE_LINE_TERMS = 3

# Words every RCA shares (template vocabulary plus common English). They say
# nothing about WHICH failure recurred, so they never count as a shared term.
_STOP = set("""
about above after again against also although always among another anything
around because been before being below between both cannot could does doing
done down during each either else enough even ever every first from further
had has have having here however into itself just last later least less like
made make makes many might more most much must never next none once only other
others over same should since some still such than that their them then there
these they this those though three through under until upon very were what
when where whether which while whom whose will with within without would your
owner type test code process gate config action actions item items fix fixed
fixes ship shipped shipping build built added adds runs running every time
times line lines file files thing things work works working path paths call
calls called check checks checked root cause causes surface structural
""".split())

_TOKEN = re.compile(r"[a-z][a-z0-9_]*(?:[.\-/][a-z0-9_]+)*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _stem(word):
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _terms(text):
    """Candidate terms. A compound identifier (a_module.check, some-script.sh)
    counts whole AND by its parts: an RCA that writes `thing.check` is still
    talking about `thing`. The real miss without this: the earlier action named
    the wrapper bare, the new root cause named its .check method."""
    out = set()
    for tok in _TOKEN.findall(text.lower()):
        parts = [tok]
        if re.search(r"[.\-/]", tok):
            parts += re.split(r"[.\-/]", tok)
        for part in parts:
            if len(part) < 4 or part in _STOP:
                continue
            out.add(part if re.search(r"[._\-/]", part) else _stem(part))
    return out


def _action_items(text):
    """Checkbox action items, minus the trailing owner/type bookkeeping."""
    items = []
    for line in section_body(text, "Action items").splitlines():
        m = re.match(r"\s*-\s*\[[ xX]\]\s*(.+)", line)
        if m:
            item = re.split(r"\s[—-]+\s*owner\b|\b[Oo]wner:", m.group(1))[0]
            items.append(item.strip().rstrip("."))
    return items


def _doc_date(file_path, text):
    found = _DATE.findall(Path(str(file_path)).name)
    if found:
        return found[-1]
    m = re.search(r"^\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    return m.group(1) if m else None


def _is_earlier(old_path, old_date, new_path, new_date):
    """Same-day RCAs order by mtime: a follow-up written in the same session
    as the earlier RCA is still a recurrence of it (PR 527 review)."""
    if old_date != new_date:
        return old_date < new_date
    try:
        return Path(old_path).stat().st_mtime < Path(str(new_path)).stat().st_mtime
    except OSError:
        return False


def _recurrence_section(text):
    """Body of the first '## Recurrence...' heading. Prefix match, like
    header_present: '## Recurrence (ASK-1)' is still the section."""
    out, capturing = [], False
    for line in text.splitlines():
        if re.match(r"##\s+", line):
            if capturing:
                break
            capturing = bool(re.match(r"##\s+Recurrence\b", line, re.I))
            continue
        if capturing:
            out.append(line)
    return "\n".join(out)


def _root_cause_text(text):
    return section_body(text, "Surface root cause") + "\n" + section_body(text, "Structural root cause")


def _sibling_rcas(file_path):
    """Every other RCA in the same directory: [(path, text)]."""
    me = Path(str(file_path))
    out = []
    try:
        candidates = sorted(me.parent.glob("*.md"))
    except OSError:
        return out
    for p in candidates:
        if p.name == me.name:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if doc_kind(p, t) == "rca":
            out.append((p, t))
    return out


def recurrence_matches(file_path, text):
    """[(earlier_file_name, [matched action items])] for each earlier RCA in
    the directory whose action items the new root cause matches.

    A shared term weighs its rarity among the OTHER RCAs in the directory
    (neither the new one nor the earlier one): ln((n+2)/(df+1)). A word most
    RCAs use is weak evidence; a word only these two share is strong. With few
    other RCAs in the directory every term weighs little, so more terms must be
    shared before anything matches. Measured, not argued: plain overlap counts
    flagged pairs on words like 'hook', 'post' and 'read'."""
    my_date = _doc_date(file_path, text) or UNDATED
    root = _terms(_root_cause_text(text))
    if not root:
        return []
    siblings = _sibling_rcas(file_path)
    term_sets = {p: _terms(t) for p, t in siblings}
    hits = []
    for old_path, old_text in siblings:
        old_date = _doc_date(old_path, old_text)
        if not old_date or not _is_earlier(old_path, old_date, file_path, my_date):
            continue
        others = [term_sets[p] for p, _ in siblings if p != old_path]
        n = len(others)

        def weight(term, others=others, n=n):
            df = sum(1 for s in others if term in s)
            return min(RECURRENCE_WEIGHT_CAP, math.log((n + 2) / (df + 1)))

        matched = []
        for a in _action_items(old_text):
            shared = _terms(a) & root
            if (len(shared) >= RECURRENCE_MIN_SHARED
                    and sum(weight(t) for t in shared) >= RECURRENCE_SCORE):
                matched.append(a)
        if len(matched) >= RECURRENCE_MIN_ACTIONS:
            hits.append((old_path.name, matched))
    return hits


def _unanswered_actions(recurrence_text, actions):
    """Actions with no Recurrence line of their own. Each line answers at most
    one action (greedy, best overlap first), so a line about the first action
    cannot also count for the second when the two share vocabulary."""
    lines = [ln for ln in recurrence_text.splitlines() if len(ln.split()) >= 8]
    pairs = []
    for ai, action in enumerate(actions):
        a_terms = _terms(action)
        need = min(RECURRENCE_LINE_TERMS, len(a_terms)) or 1
        for li, line in enumerate(lines):
            overlap = len(a_terms & _terms(line))
            if overlap >= need:
                pairs.append((overlap, ai, li))
    used_a, used_l = set(), set()
    for _overlap, ai, li in sorted(pairs, reverse=True):
        if ai in used_a or li in used_l:
            continue
        used_a.add(ai)
        used_l.add(li)
    return [a for i, a in enumerate(actions) if i not in used_a]


def recurrence_violations(file_path, text):
    # Its own marker, so a false positive costs only this check. The file-wide
    # rca-lint-skip would also drop the structure, evidence and blameless
    # checks (PR 527 review).
    if RECURRENCE_SKIP_MARKER in text:
        return []
    my_date = _doc_date(file_path, text) or UNDATED
    if my_date < RECURRENCE_CUTOFF:
        return []
    hits = recurrence_matches(file_path, text)
    if not hits:
        return []
    rec = _recurrence_section(text)
    violations = []
    for old_name, actions in hits:
        listed = "\n".join(f"      - {a}" for a in actions)
        if not rec.strip():
            violations.append({
                "rule": "recurrence-unnamed",
                "detail": f"root cause matches {len(actions)} action item(s) of the earlier RCA "
                          f"{old_name}. Add a '## Recurrence' section that names {old_name} and, per "
                          f"action, says which action failed and why (e.g. 'marked built without a "
                          f"runtime test'). Not a recurrence? Add <!-- {RECURRENCE_SKIP_MARKER} --> "
                          f"(skips only this check):\n{listed}",
            })
            continue
        if old_name not in rec:
            violations.append({
                "rule": "recurrence-unnamed",
                "detail": f"## Recurrence does not name the earlier RCA {old_name}, whose action "
                          f"items this root cause matches:\n{listed}",
            })
            continue
        missing = _unanswered_actions(rec, actions)
        if missing:
            listed = "\n".join(f"      - {a}" for a in missing)
            violations.append({
                "rule": "recurrence-action-unanswered",
                "detail": f"## Recurrence names {old_name} but has no line (8+ words, sharing "
                          f"{RECURRENCE_LINE_TERMS}+ terms with the action) saying why each of "
                          f"these failed:\n{listed}",
            })
    return violations


def lint_text(file_path, text):
    violations = []
    kind = doc_kind(file_path, text)
    if kind is None:
        return []

    if not re.search(r"^\*\*Date:\*\*", text, re.M):
        violations.append({"rule": "missing-metadata", "detail": "missing **Date:** line"})
    if not re.search(r"^\*\*Trigger:\*\*", text, re.M):
        violations.append({"rule": "missing-metadata", "detail": "missing **Trigger:** line"})

    found = headers(text)
    required = REQUIRED_RCA_SECTIONS if kind == "rca" else REQUIRED_PREMORTEM_SECTIONS
    for sec in required:
        if not header_present(found, sec):
            violations.append({"rule": "missing-section", "detail": f"missing required section: ## {sec}"})

    if kind == "rca":
        struct = section_body(text, "Structural root cause")
        tags = re.findall(r"type:\s*([a-z-]+)", struct)
        if not [t for t in tags if t in CAUSE_TYPES]:
            violations.append({
                "rule": "missing-cause-type",
                "detail": "Structural root cause has no valid 'type:' tag "
                          f"(one of: {', '.join(sorted(CAUSE_TYPES))})",
            })

        verif = section_body(text, "Verification")
        if "```" not in verif and not EVIDENCE_WORDS.search(verif):
            violations.append({
                "rule": "no-evidence",
                "detail": "Verification section has no evidence "
                          "(a code fence or words like ran/got/observed/passed)",
            })

        actions = section_body(text, "Action items")
        if not re.search(r"^\s*-\s*\[[ xX]\]", actions, re.M):
            violations.append({
                "rule": "prose-action-items",
                "detail": "Action items must be checkboxes (- [ ] ...), not prose",
            })

        violations.extend(recurrence_violations(file_path, text))

    for pat, msg in BLAME_PATTERNS:
        if pat.search(text):
            violations.append({"rule": "not-blameless", "detail": msg})

    return violations


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        # Never block a write on an infra/read failure; this is a content gate.
        return []
    if SKIP_MARKER in text:
        return []
    return lint_text(file_path, text)


def format_report(file_path, violations):
    lines = [f"rca-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append(f"Fix per the rca skill's references/rca-template.md, or add <!-- {SKIP_MARKER} --> to bypass.")
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not str(file_path).endswith(".md"):
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)
    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    violations = lint_file(file_path)
    if not violations:
        print(f"rca-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: rca-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
