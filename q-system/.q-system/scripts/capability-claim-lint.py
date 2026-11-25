#!/usr/bin/env python3
"""capability-claim-lint: an alerting claim in a rule or README names its emitter.

Pairs with `.claude/rules/founder-notifications.md` (the named-emitter clause)
and `.claude/rules/no-orphan-findings.md` (the uncaptured-commitment clause).

WHY (ASK-562): four times in one day a capability was reported by reading the
design instead of observing the behaviour. "I'll tell you either way" with
nothing computing it; "runs continuously every 4 hours" for a job that had
never run once. The cost is worse than a bug: the reader stops watching for the
thing because a sentence said something else is watching. The one question
that caught every case was "what runs that?". This lint asks it of files on
disk: a line that says something will alert, notify, page or tell you must have
an executable path (a `.py`, `.sh`, `.plist`, ...) on that line or within
WINDOW lines of it.

HONEST BOUNDARY:
  1. It sees FILES, never chat. A promise said to the founder in conversation
     is out of reach of any hook; `no-orphan-findings.md` carries that half.
  2. It checks that an emitter is NAMED near the claim, never that the named
     script exists, is wired, or actually fires. A wrong path passes.
  3. It matches a fixed phrase set. A new way of saying "someone is watching"
     walks past it until the set is widened.

Scope: `.claude/rules/*.md` and any `README*.md`. Everything else exits 0 on
the first check, because this ships fleet-wide via settings-template.json and a
false positive would block edits in every instance.

Bypass: put `capability-claim-lint-skip` in the file.
Contract: hook mode reads PostToolUse JSON on stdin; exit 0 pass, exit 2 block.
CLI: `capability-claim-lint.py FILE...` lints the named files (exit 2 on a hit);
`capability-claim-lint.py --scan ROOT...` lints every in-scope file under each
root and prints every hit (the population replay the gate was bounded by).
stdlib only. Self-test: `python3 test_capability_claim_lint.py`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SKIP_MARKER = "capability-claim-lint-skip"

# How far from the claim the emitter may sit: a sentence that wraps across a
# markdown paragraph. Measured 2026-09-23 on both populations (ASK-562 PR body):
# windows 1, 2 and 3 flag the same lines, so the tighter end is taken. A wide
# window lets an unrelated path three bullets away vouch for a claim.
WINDOW = 2

# The alerting phrases from ASK-562's own occurrences: a promise that someone or
# something will speak up. Deliberately NOT bare "alert"/"notify" as nouns:
# "alert fatigue" or "a notification" claims nothing about what runs. And NOT a
# present-tense "tells you": the replay flagged the skeleton README's "then it
# tells you what it found", which describes an answer in the session, not a
# watcher. The future form ("I'll tell you") is the promise and stays.
CLAIM_RE = re.compile(
    r"\b(?:will|would|'ll)\s+(?:alert|notify|page|ping|warn|flag)\b"
    r"|\b(?:will|would|'ll)\s+(?:tell|let)\s+you\b"
    r"|\b(?:alerts|notifies|pages|pings|warns|taps)\s+"
    r"(?:you|the\s+founder|the\s+operator|sana|him)\b"
    r"|\bnotifies\b"
    r"|\b(?:is|are|gets?|being|stays)\s+watched\b"
    r"|\bkeeps?\s+(?:an\s+)?eye\s+on\b",
    re.IGNORECASE,
)

# A negated claim is honest, not a promise: "nothing will alert you" is exactly
# the sentence this lint wants people to write.
NEGATION_RE = re.compile(
    r"\b(?:no|nothing|nobody|never|not|cannot|can't|won't|doesn't|does\s+not"
    r"|without|neither|nor)\b[^.;:]*$",
    re.IGNORECASE,
)

# An executable named: a script or unit file, or a module run with `-m`.
EMITTER_RE = re.compile(
    r"[\w./~$-]+\.(?:py|sh|bash|zsh|mjs|cjs|js|ts|plist)\b"
    r"|\bpython3?\s+-m\s+[\w.]+",
)

FENCE_RE = re.compile(r"^\s*(```|~~~)")


def in_scope(path: str) -> bool:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if not name.lower().endswith(".md"):
        return False
    if name.lower().startswith("readme"):
        return True
    parent = p.rsplit("/", 1)[0] if "/" in p else ""
    return parent.endswith("/.claude/rules") or parent == ".claude/rules"


def hits(body: str) -> list[tuple[int, str]]:
    """(1-based line, text) of every claim with no emitter within WINDOW."""
    if SKIP_MARKER in body:
        return []
    lines = body.splitlines()
    out = []
    fenced = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = CLAIM_RE.search(line)
        if not m:
            continue
        if NEGATION_RE.search(line[: m.start()]):
            continue
        lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
        if any(EMITTER_RE.search(lines[j]) for j in range(lo, hi)):
            continue
        out.append((i + 1, line.strip()))
    return out


def lint_file(path: Path) -> list[tuple[int, str]]:
    try:
        return hits(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


def scan(root: Path) -> list[Path]:
    """Every in-scope file under root, skipping VCS and dependency trees."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "venv",
                                    "__pycache__")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if in_scope(rel):
                found.append(Path(full))
    return sorted(found)


def message(path: str, bad: list[tuple[int, str]]) -> str:
    listed = "\n".join(f"    {path}:{n}: {t[:160]}" for n, t in bad)
    return (
        "CAPABILITY CLAIM LINT (blocked): a line says something will alert, "
        "notify or tell you, and no executable is named within "
        f"{WINDOW} lines of it:\n{listed}\n\n"
        "  The question is \"what runs that?\". Name the script and the channel, "
        "e.g. `q-system/.q-system/scripts/slack-notify.sh` (Sana's Linear "
        "triage). If nothing runs it, say that instead (\"nothing alerts on "
        "this\"), or capture the missing detector with `spillover add`.\n"
        "  See .claude/rules/founder-notifications.md (named-emitter clause).\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")


# ---------------------------------------------------------------------------
# Enforcement claims (ASK-3818, RULE-2026-11-06-A).
#
# WHY: `.claude/rules/no-orphan-findings.md:37` said "`gates run` fails while
# any item is open". No `gates` executable exists in this repo, and the real
# one (prd-os `prd_runner.py gates run`) fails only on items attributable to the
# run's scope. The sentence sat there as a backstop that nobody checked, which
# is the rca-enforce-in-code-ends-as-prose shape: a claim that names a mechanism
# is read as the mechanism. So a line that says a named thing fails, blocks,
# refuses, denies, rejects or exits non-zero must be held by something a reader
# can open:
#   - the named subject itself resolves to an executable that is wired, or
#   - `held_by: <path>` names one (a wired executable, or a test file), or
#   - `ticket: ASK-n` plus `expires: YYYY-MM-DD` not yet past (interim prose), or
#   - `kind: observation` (RCA 696: a measured fact, not a rule).
# Every other must/never/always line is COUNTED (the census), not refused: the
# corpus predates the tag and a gate red on its whole population gets switched
# off. `--census FILE --record-re RE` is the strict reader a caller points at
# one file whose every record must be held (chief's F21 reads DEC lines).
#
# HONEST BOUNDARY: it proves the holder exists and is named in a config. It does
# not prove the holder enforces this sentence; review proves that.
# ---------------------------------------------------------------------------
import datetime
import glob
import hashlib
import subprocess

MECHANISM_VERB = (r"\b(?:fails|blocks|refuses|denies|rejects"
                  r"|exits\s+(?:1|2|non-zero|nonzero))\b")
MECHANISM_RE = re.compile(r"`([^`]+)`[^.;:`]{0,40}?" + MECHANISM_VERB, re.IGNORECASE)
# Review round 1 (PR #884): the scar sentence with its backticks removed ("gates
# run fails while any item is open") walked past the backtick-only pattern. A
# plain-prose subject is the up-to-three words before the verb.
PLAIN_MECHANISM_RE = re.compile(
    r"((?:[\w/-]+(?:\.[\w-]+)*\s+){0,2}[\w/-]+(?:\.[\w-]+)*)\s+" + MECHANISM_VERB,
    re.IGNORECASE)
# A plain subject counts only when it names a mechanism: a noun from this set, a
# pronoun standing for one, or a tool-shaped token (dash, dot or slash). Without
# this, "Common blocks" and "a page that fails the gate" read as claims.
MECH_NOUNS = {"hook", "hooks", "lint", "linter", "gate", "gates", "check", "guard",
              "validator", "script", "test", "command", "job", "workflow", "ci",
              "run", "it", "this", "detector", "ratchet", "floor", "harness"}
ADVERBS = {"also", "only", "still", "now", "then", "always", "already", "simply"}
PRONOUNS = {"it", "this"}
# A verb under a negation or a condition claims nothing runs: "never blocks",
# "does not fail", "if the push fails".
NOT_A_CLAIM_RE = re.compile(
    r"\b(?:no|nothing|never|not|cannot|can't|won't|doesn't|without|neither|nor"
    r"|if|when|unless|whether|until|until)\b[^.;:]*$", re.IGNORECASE)
BROAD_RE = re.compile(
    r"\b(?:must|never|always|blocks|refuses|fails|denies|rejects"
    r"|bounded\s+by\s+code)\b",
    re.IGNORECASE,
)


def mechanism_subject(line: str) -> str | None:
    """The subject of a positive mechanism claim on this line, or None."""
    m = MECHANISM_RE.search(line)
    if m and not NOT_A_CLAIM_RE.search(line[: m.start()]):
        return m.group(1)
    for p in PLAIN_MECHANISM_RE.finditer(line):
        words = p.group(1).split()
        while len(words) > 1 and words[-1].lower() in ADVERBS:
            words.pop()  # "the lint hook also blocks": the subject is "lint hook"
        last = words[-1].lower()
        if last in ("that", "which", "who") or len(words) > 1 and words[-2].lower() in (
                "that", "which", "who"):
            continue  # a relative clause: "a step that fails" describes, not claims
        if not (last in MECH_NOUNS or re.search(r"[-./]", last)):
            continue
        if NOT_A_CLAIM_RE.search(line[: p.start(1)] + p.group(1)):
            continue
        return " ".join(words)
    return None
HELD_RE = re.compile(r"held_by:\s*`?([^\s`,;)]+)`?")
TICKET_RE = re.compile(r"ticket:\s*`?([A-Z]+-\d+)")
EXPIRES_RE = re.compile(r"expires:\s*`?(\d{4}-\d{2}-\d{2})")
OBSERVATION_RE = re.compile(r"kind:\s*observation\b")
EXEC_EXT = (".py", ".sh", ".bash", ".zsh", ".mjs", ".cjs", ".js", ".ts")
TEST_NAME_RE = re.compile(r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.py|test-[^/]+\.sh)$")


def _config_text(root: Path, user_settings: bool = False) -> str:
    """Every file whose mention of a script means it runs: hook settings,
    lefthook, CI, launchd units, plugin hooks, and the `kipi` CLI with the
    harness it calls. Read once per run."""
    pats = [".claude/settings.json", ".claude/settings.local.json",
            "settings-template.json", "lefthook.yml", ".github/workflows/*.yml",
            "kipi", "validate-separation.py", "plugins/*/hooks/hooks.json",
            "**/*.plist"]
    chunks = []
    for pat in pats:
        for f in glob.glob(str(root / pat), recursive=True):
            if "/.git/" in f or "/node_modules/" in f:
                continue
            try:
                chunks.append(Path(f).read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    # A memory note's holder is usually a global hook, wired in the user's
    # settings rather than any repo's. Only the memory hook asks for it: review
    # round 1 found --all green on the laptop and red in CI for a holder wired
    # only in ~/.claude/settings.json.
    if user_settings:
        try:
            chunks.append((Path.home() / ".claude/settings.json").read_text(
                encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return "\n".join(chunks)


class Holders:
    """Resolves a name to a file under root and says whether it is wired."""

    def __init__(self, root: Path, today: datetime.date | None = None,
                 user_settings: bool = False):
        self.root = root
        self.user_settings = user_settings
        self.today = today or datetime.date.today()
        self._cfg: str | None = None

    @property
    def cfg(self) -> str:
        if self._cfg is None:
            self._cfg = _config_text(self.root, self.user_settings)
        return self._cfg

    def resolve(self, name: str) -> Path | None:
        name = name.split("::", 1)[0].strip().strip("`")
        if not name or name.startswith("-"):
            return None
        p = Path(os.path.expanduser(name))
        cands = [p] if p.is_absolute() else [
            self.root / p, self.root / "q-system/.q-system/scripts" / p,
            self.root / "q-system/.q-system/hooks" / p]
        for c in cands:
            if c.is_file():
                return c
        if "/" not in name and "." in name:
            hit = self.index.get(name)
            if hit:
                return hit
        return None

    @property
    def index(self) -> dict:
        """basename -> first path under root, built once (one walk, ~0.1s)."""
        if getattr(self, "_index", None) is None:
            self._index = {}
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = sorted(d for d in dirnames if d not in (
                    ".git", "node_modules", ".venv", "venv", "__pycache__"))
                for fn in filenames:
                    self._index.setdefault(fn, Path(dirpath) / fn)
        return self._index

    def names_wired_executable(self, text: str) -> bool:
        """True when any script path or backticked command in text resolves to
        a wired executable. A sentence that names its own enforcer is held."""
        cands = [m.group(0) for m in EMITTER_RE.finditer(text)]
        cands += re.findall(r"`([^`]+)`", text)
        return any(self.subject_ok(c) for c in cands)

    def wired(self, path: Path) -> bool:
        return path.name in self.cfg

    def test_runs(self, path: Path) -> bool:
        """A test holds a claim only if it has a test in it and something runs
        it: a config names it, or it is a tracked file whose suite CI collects.
        Review round 1: a 0-byte test_x.py held any claim."""
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        if not re.search(r"^\s*def\s+test_|^\s*check\(|^if __name__", src, re.M):
            return False
        if self.wired(path):
            return True
        full = path.resolve()
        r = subprocess.run(["git", "-C", str(full.parent), "ls-files", "--error-unmatch",
                            str(full)], capture_output=True, text=True, check=False)
        return r.returncode == 0

    def holder_ok(self, name: str) -> tuple[bool, str]:
        path = self.resolve(name)
        if path is None:
            return False, f"held_by `{name}` resolves to no file"
        if TEST_NAME_RE.search(str(path)):
            if self.test_runs(path):
                return True, ""
            return False, (f"held_by `{name}` is a test with no test in it, or one "
                           "nothing tracks or runs")
        if self.wired(path):
            return True, ""
        return False, f"held_by `{name}` exists but nothing runs it (no config names it)"

    def subject_ok(self, subject: str) -> bool:
        first = subject.split()[0] if subject.split() else ""
        path = self.resolve(first)
        if path is None:
            return False
        if not (path.suffix in EXEC_EXT or os.access(path, os.X_OK)):
            return False
        return self.wired(path) or path.name == "kipi"


def tag_verdict(block: str, h: Holders) -> tuple[str, str]:
    """('held'|'ticketed'|'observation'|'missing'|'broken', reason) for one record."""
    if OBSERVATION_RE.search(block):
        return "observation", ""
    m = HELD_RE.search(block)
    if m:
        ok, why = h.holder_ok(m.group(1))
        return ("held", "") if ok else ("broken", why)
    t = TICKET_RE.search(block)
    if t:
        e = EXPIRES_RE.search(block)
        if not e:
            return "broken", f"ticket {t.group(1)} carries no expires: date"
        try:
            exp = datetime.date.fromisoformat(e.group(1))
        except ValueError:
            return "broken", f"expires {e.group(1)} is not a date"
        if exp < h.today:
            return "broken", f"ticket {t.group(1)} expired {exp}"
        return "ticketed", ""
    return "missing", ""


def enforcement_findings(body: str, h: Holders) -> tuple[list[tuple[int, str, str]], int, int]:
    """(violations, broad_claims, broad_untagged) for one rule file.
    A violation is a mechanism claim that is not held, or any broken tag."""
    if SKIP_MARKER in body:
        return [], 0, 0
    out, broad, untagged = [], 0, 0
    fenced = False
    lines = body.splitlines()
    # A claim is judged with the whole bullet or paragraph it sits in, so a tag
    # or an enforcer named on a wrapped line counts. A new bullet, a blank line
    # or a heading starts a new block. Scar: with a +/-1 line window,
    # no-orphan-findings.md:37 was "held" by the unrelated
    # spillover-linear-check.py bullet below it.
    block_of, prev_of, start, last_text = {}, {}, 0, ""
    for i, line in enumerate(lines + [""]):
        new = (not line.strip() or line.lstrip().startswith("#")
               or re.match(r"\s*(?:[-*+]|\d+\.)\s", line))
        if new or i == len(lines):
            text = "\n".join(lines[start:i])
            for j in range(start, i):
                block_of[j] = text
                prev_of[j] = last_text
            if text.strip():
                last_text = text
            start = i
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        ctx = block_of.get(i, line)
        lv, why = tag_verdict(line, h)
        if lv == "broken":
            out.append((i + 1, line.strip(), why))
            continue
        verdict, _ = tag_verdict(ctx, h)
        if verdict == "broken":
            verdict = "missing"  # reported on the line that carries the bad tag
        subj = mechanism_subject(line)
        if subj and subj.split()[-1].lower() in PRONOUNS:
            # "It blocks ..." stands for the enforcer the paragraph above named.
            ctx = prev_of.get(i, "") + "\n" + ctx
        if subj and verdict == "missing" and not h.names_wired_executable(ctx):
            out.append((i + 1, line.strip(),
                        f"names `{subj}` as the mechanism; it resolves to no "
                        "wired executable"))
            continue
        if BROAD_RE.search(line):
            broad += 1
            if verdict == "missing":
                untagged += 1
    return out, broad, untagged


DIRECTIVE_RE = re.compile(r"\b(?:must|never|always|before\s+you)\b", re.IGNORECASE)


# THE EXISTING CORPUS IS DEBT, NOT A TARGET (review round 1 on PR #884). Measured
# 2026-11-25: 689 of 964 auto-memory notes say must/never/always with no holder,
# so a refusal on every write would have refused most memory writes fleet-wide,
# and a gate red on its whole population gets switched off. Same shape as
# rule_gate's debt.md: the notes as they stood when the baseline was taken are
# grandfathered by content hash. A new note, or an old note whose content
# changed, must carry a holder. The baseline only shrinks in effect: it is
# written once and never rewritten.
def memory_baseline_path() -> Path:
    env = os.environ.get("KIPI_MEMORY_CLAIM_BASELINE")
    if env:
        return Path(env)
    return Path.home() / ".config/kipi/memory-claim-baseline.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def memory_baseline(exclude: str | None = None) -> dict:
    """{realpath: sha256} of every auto-memory note at first use. The one writer:
    created with O_EXCL, so two hooks racing on the first write cannot both
    write it, and an existing baseline is never rewritten. `exclude` is the note
    being written right now: it is judged, never grandfathered by its own write."""
    bp = memory_baseline_path()
    try:
        return json.loads(bp.read_text(encoding="utf-8")).get("notes", {})
    except (OSError, ValueError):
        pass
    notes = {}
    skip = os.path.realpath(exclude) if exclude else None
    for f in glob.glob(str(Path.home() / ".claude/projects/*/memory/*.md")):
        if f.endswith("/MEMORY.md") or os.path.realpath(f) == skip:
            continue
        try:
            notes[os.path.realpath(f)] = _sha(Path(f).read_text(encoding="utf-8",
                                                                 errors="ignore"))
        except OSError:
            pass
    data = {"created": datetime.date.today().isoformat(), "ticket": "ASK-3818",
            "notes": notes}
    try:
        bp.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(bp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
    except FileExistsError:
        try:
            return json.loads(bp.read_text(encoding="utf-8")).get("notes", {})
        except (OSError, ValueError):
            pass
    except OSError:
        pass
    return notes


def memory_note_verdict(text: str, root: Path, path: str | None = None) -> str | None:
    """None when a memory note passes; the refusal reason otherwise (RCA 696,
    consulting rca-enforce-in-code-ends-as-prose action 2). A note that says
    must/never/always/before-you is a rule, and a rule held by nothing is the
    prose this ticket exists to stop. A note unchanged since the baseline passes."""
    m = DIRECTIVE_RE.search(text)
    if not m:
        return None
    if path is not None:
        if memory_baseline(exclude=path).get(os.path.realpath(path)) == _sha(text):
            return None
    verdict, why = tag_verdict(text, Holders(root, user_settings=True))
    if verdict in ("held", "ticketed", "observation"):
        return None
    if verdict == "broken":
        return why
    return (f"the note says '{m.group(0)}' and carries no `held_by: <wired script or "
            "test>`, no `ticket: ASK-n` plus `expires: YYYY-MM-DD`, and no "
            "`kind: observation`")


def rule_files(root: Path) -> list[Path]:
    files = sorted(root.glob(".claude/rules/*.md"))
    files += [p for p in (root / "CLAUDE.md", root / "q-system/CLAUDE.md") if p.is_file()]
    return files


def run_all(root: Path, as_json: bool) -> int:
    h = Holders(root)
    report = {"root": str(root), "violations": [], "broad_claims": 0,
              "broad_untagged": 0, "files": 0}
    for f in rule_files(root):
        try:
            body = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        report["files"] += 1
        bad, broad, untagged = enforcement_findings(body, h)
        report["broad_claims"] += broad
        report["broad_untagged"] += untagged
        rel = os.path.relpath(f, root)
        for n, text, why in bad:
            report["violations"].append({"file": rel, "line": n, "text": text[:200],
                                         "why": why})
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for v in report["violations"]:
            print(f"{v['file']}:{v['line']}: {v['why']}\n    {v['text'][:160]}")
        print(f"# enforcement claims: {len(report['violations'])} unheld mechanism "
              f"claims; census {report['broad_untagged']} of "
              f"{report['broad_claims']} must/never/always lines carry no held_by, "
              f"ticket+expires or kind: observation ({report['files']} files)")
        if report["violations"]:
            print("  Fix: add `held_by: <wired script or test>`, or `ticket: ASK-n "
                  "expires: YYYY-MM-DD`, or correct the sentence to what the code does.")
    return 2 if report["violations"] else 0


def records(body: str, record_re: re.Pattern) -> list[tuple[int, str]]:
    """Each record starts on a line matching record_re and runs to the next
    record start or a markdown heading, so a tag on a continuation or sub-bullet
    line of the same entry counts."""
    lines = body.splitlines()
    out, start = [], None
    for i, line in enumerate(lines + ["# end"]):
        is_start = i < len(lines) and record_re.search(line)
        if start is not None and (is_start or line.startswith("#")):
            out.append((start + 1, "\n".join(lines[start:i])))
            start = None
        if is_start:
            start = i
    return out


def run_census(path: Path, record_re: str, root: Path | None, as_json: bool) -> int:
    """Strict reader: every record must be held, ticketed or an observation.
    Output (json): {file, records, held, ticketed, observation, missing:[...],
    broken:[...], ok}. Exit 0 when ok, 2 otherwise, 3 when the file is unreadable."""
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        print(json.dumps({"file": str(path), "error": str(e), "ok": False}))
        return 3
    if root is None:
        root = path.resolve().parent
        while root != root.parent and not (root / ".git").exists():
            root = root.parent
    h = Holders(root)
    rep = {"file": str(path), "root": str(root), "record_re": record_re,
           "records": 0, "held": 0, "ticketed": 0, "observation": 0,
           "missing": [], "broken": []}
    for n, block in records(body, re.compile(record_re)):
        rep["records"] += 1
        verdict, why = tag_verdict(block, h)
        first = block.splitlines()[0].strip()[:160]
        if verdict in ("held", "ticketed", "observation"):
            rep[verdict] += 1
        elif verdict == "missing":
            rep["missing"].append({"line": n, "text": first})
        else:
            rep["broken"].append({"line": n, "text": first, "why": why})
    rep["ok"] = rep["records"] > 0 and not rep["missing"] and not rep["broken"]
    if as_json:
        print(json.dumps(rep, indent=2))
    else:
        for m in rep["missing"]:
            print(f"{path}:{m['line']}: no held_by, ticket+expires or kind: observation\n    {m['text']}")
        for b in rep["broken"]:
            print(f"{path}:{b['line']}: {b['why']}\n    {b['text']}")
        print(f"# census {path}: {rep['records']} records, {rep['held']} held, "
              f"{rep['ticketed']} ticketed, {rep['observation']} observation, "
              f"{len(rep['missing'])} missing, {len(rep['broken'])} broken")
    return 0 if rep["ok"] else 2


# Hook census (ASK-3818, RCA 698). A hook entry whose command is `test -f X &&
# ...` or ends `|| true` cannot block when its script is gone or fails, so it is
# advisory whatever its rule says. The founder's 2026-11-06 count was 16 files
# in ~/.claude/hooks: 3 retired, 2 advisory, 3 deny; nothing printed it.
ADVISORY_CMD_RE = re.compile(r"^\s*test\s+-[fex]\s.*&&|\|\|\s*true\s*$")
# Review round 1: the bare key `permissionDecision` counted auto-approve-git.sh
# (which emits "allow") as a deny hook. Classify by the decision VALUE.
DENY_RE = re.compile(r"exit\s+2\b|sys\.exit\(\s*2\s*\)"
                     r"|[\"']?permissionDecision[\"']?\s*[:=]\s*\\?[\"']deny"
                     r"|[\"']?decision[\"']?\s*[:=]\s*\\?[\"']block")
RETIRED_RE = re.compile(r"\.(?:bak|orig|old|disabled)(?:\.|$)|~$")


def _hook_commands(settings: Path) -> list[str]:
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cmds = []
    for groups in (data.get("hooks") or {}).values():
        for g in groups or []:
            for hk in (g or {}).get("hooks") or []:
                c = (hk or {}).get("command")
                if isinstance(c, str):
                    cmds.append(c)
    return cmds


def hook_census(hooks_dir: Path, settings_files: list[Path]) -> dict:
    entries = []
    for s in settings_files:
        for c in _hook_commands(s):
            entries.append({"settings": str(s), "command": c,
                            "advisory": bool(ADVISORY_CMD_RE.search(c))})
    files = []
    if hooks_dir.is_dir():
        for f in sorted(hooks_dir.iterdir()):
            if not f.is_file():
                continue
            refs = [e for e in entries if f.name in e["command"]]
            if RETIRED_RE.search(f.name):
                cls, why = "retired", "backup copy"
            elif not refs:
                cls, why = "retired", "no settings entry runs it"
            else:
                try:
                    src = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    src = ""
                if all(e["advisory"] for e in refs):
                    cls, why = "advisory", "every entry is test -f && or || true"
                elif DENY_RE.search(src):
                    cls, why = "deny", "wired, has a deny or exit 2 path"
                else:
                    cls, why = "advisory", "wired, no deny or exit 2 path"
            files.append({"file": f.name, "class": cls, "why": why})
    counts = {k: sum(1 for x in files if x["class"] == k)
              for k in ("deny", "advisory", "retired")}
    return {"hooks_dir": str(hooks_dir), "files": files, "counts": counts,
            "entries": len(entries),
            "advisory_entries": sum(1 for e in entries if e["advisory"]),
            "advisory_commands": [e["command"] for e in entries if e["advisory"]]}


def run_hook_census(argv: list[str]) -> int:
    hooks_dir = Path(os.path.expanduser("~/.claude/hooks"))
    root = Path.cwd()
    as_json = "--json" in argv
    if "--hooks-dir" in argv:
        hooks_dir = Path(argv[argv.index("--hooks-dir") + 1])
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1])
    settings = [hooks_dir.parent / "settings.json", root / ".claude/settings.json"]
    uniq = list(dict.fromkeys(s.resolve() for s in settings if s.is_file()))
    rep = hook_census(hooks_dir, uniq)
    if as_json:
        print(json.dumps(rep, indent=2))
        return 0
    for f in rep["files"]:
        print(f"  {f['class']:<8} {f['file']}  ({f['why']})")
    c = rep["counts"]
    print(f"hook census {rep['hooks_dir']}: {c['deny']} deny, {c['advisory']} advisory, "
          f"{c['retired']} retired")
    print(f"advisory hook entries: {rep['advisory_entries']} of {rep['entries']} "
          "(test -f && or || true; they cannot block when the script fails or is gone)")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--all":
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
        if "--root" in argv:
            root = Path(argv[argv.index("--root") + 1])
        return run_all(root, "--json" in argv)
    if argv and argv[0] == "--census":
        if len(argv) < 2:
            print("usage: --census FILE [--record-re RE] [--root DIR] [--json]",
                  file=sys.stderr)
            return 3
        rr = "(?i)" + BROAD_RE.pattern
        if "--record-re" in argv:
            rr = argv[argv.index("--record-re") + 1]
        root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else None
        return run_census(Path(argv[1]), rr, root, "--json" in argv)
    if argv and argv[0] == "--hook-census":
        return run_hook_census(argv[1:])
    if argv and argv[0] == "--scan":
        total = 0
        for root in argv[1:]:
            files = scan(Path(root))
            n = 0
            for f in files:
                for line, text in lint_file(f):
                    n += 1
                    print(f"{f}:{line}: {text[:200]}")
            print(f"# {root}: {len(files)} in-scope files, {n} hits",
                  file=sys.stderr)
            total += n
        return 2 if total else 0
    if argv:
        rc = 0
        for a in argv:
            bad = lint_file(Path(a))
            if bad:
                sys.stderr.write(message(a, bad))
                rc = 2
        return rc
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = (ti.get("file_path") or ti.get("path") or "")
    if not fp or not in_scope(fp):
        return 0
    bad = lint_file(Path(fp))
    if not bad:
        return 0
    sys.stderr.write(message(fp, bad))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
