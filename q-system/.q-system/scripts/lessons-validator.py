#!/usr/bin/env python3
"""Allowlist validator for q-system/lessons/ lesson files.

PostToolUse(Edit|Write) hook wired in the skeleton .claude/settings.json. Guards
founder writes where lessons are authored; instances are read-only consumers so it
is moot there. Pairs with the lessons corpus (PRD prd-cross-instance-learning-2026-06-19).

Reads hook JSON on stdin. Exit 0 (allow) unless the edited file is a lesson under
q-system/lessons/ that violates the frontmatter contract -> exit 2 (block, stderr
fed back to Claude). Self-scoped: any path outside q-system/lessons/ (or README.md)
exits 0 fast. stdlib only.

K5 (ASK-4339, PRD prd-voicegate-skeleton-2026-11-09): a NEW or CHANGED lesson must also
say who holds it, in one of two fields:
  held_by         a repo-relative path to a hook, script or test that exists and contains
                  the lesson id. Same linkage rule_gate.py enforces for RULE-2026-11-08-CODE.
  prose_accepted  "YYYY-MM-DD reason": a dated, explicit decision that this lesson has no
                  deterministic check.
Why: the corpus was prose only. A lesson nobody can point to code for is an aspiration, and
the founder ruled (RULE-2026-11-08-CODE) that prose does not get to stand in for code
silently. Lessons already on origin/main without either field are DEBT: counted and
printed on every run, never refused, or the gate would be red on its own population and
get switched off.

Limit, said out loud: this proves LINKAGE (the named file exists, is code, mentions the
id). A file that only mentions the id in a comment passes. Review proves it enforces.

Modes (stdin hook JSON is the default):
  --debt [DIR]            print the debt count for DIR (default: this repo's lessons dir)
  --check-changed REPO    validate every changed or untracked lesson under REPO; exit 2 if
                          any is refused (lessons-daily.sh calls this and only reports)
  --check-note FILE       a lesson-note.sh intake note must have a title and a body
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

BASE_KEYS = {"id", "kind", "title", "date"}
HOLDER_KEYS = {"held_by", "prose_accepted"}
ALLOWED_KEYS = BASE_KEYS | HOLDER_KEYS
ALLOWED_KINDS = {"pattern", "methodology"}
# client-token denylist (mirrors kipi-push-upstream.sh line 26); structural backstop on the
# content fields that fan eagerly to every instance. K5 widened it from the title to EVERY
# value: a new free-text field (prose_accepted) is a new leak path, and a denylist that
# guards one field while the next one ships unguarded is the shape this repo keeps relearning.
TOKEN_RE = re.compile(r"KTLYST|CISO|re-breach|Assaf|/Users/", re.IGNORECASE)
CODE_EXT = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb"}
LESSONS_MARK = "q-system/lessons/"
PROSE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[:,;-]?\s*(.*)$")
MAX_HOLDER_BYTES = 4_000_000


def block(msg):
    sys.stderr.write("lessons-validator: " + msg + "\n")
    sys.exit(2)


def parse_frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = {}
    for line in text[3:end].strip("\n").splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _git_env():
    # A hook exports GIT_DIR, which outranks `git -C`; scrub or a fixture reads the wrong repo.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=_git_env())


def repo_root_of(path):
    """The directory above q-system/lessons/. By path, not by `git rev-parse`, so a lesson
    in a tmp dir with no .git still resolves a root for held_by."""
    norm = os.path.abspath(path).replace("\\", "/")
    i = norm.find(LESSONS_MARK)
    return norm[:i].rstrip("/") or "/" if i >= 0 else None


def baseline_content(root, relpath):
    """The lesson as it is on origin/main, or None when it is not there (new lesson).

    origin/main when it resolves, else HEAD. Never both: a lesson committed on a feature
    branch is on HEAD but not on origin/main, and counting it as legacy would let a
    field-less lesson ride in as debt just by being committed first. No git, no baseline:
    the lesson reads as new, which is the strict direction.
    """
    ref = os.environ.get("KIPI_LESSONS_BASELINE_REF")
    if not ref:
        ref = "origin/main" if _git(root, "rev-parse", "--verify", "-q", "origin/main").returncode == 0 else "HEAD"
    r = _git(root, "show", f"{ref}:{relpath}")
    return r.stdout if r.returncode == 0 else None


def check_held_by(value, lesson_id, root):
    if not value:
        return "held_by is empty"
    if re.search(r"[\s,;]", value):
        return "held_by must be ONE repo-relative path (no spaces, commas or lists)"
    if value.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", value) or ".." in value.replace("\\", "/").split("/"):
        return "held_by must be a repo-relative path (no absolute path, ~ or ..)"
    full = os.path.join(root, value)
    if not os.path.isfile(full):
        return "held_by names a file that does not exist: " + value
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_root, os.path.realpath(full)]) != real_root:
        return "held_by must resolve to a file inside the repo (symlink escapes it): " + value
    # Judge the REAL file too: a code-named symlink to a lesson would otherwise contain its own id.
    real = os.path.realpath(full).replace("\\", "/")
    if (os.path.splitext(value)[1].lower() not in CODE_EXT or LESSONS_MARK in value
            or os.path.splitext(real)[1].lower() not in CODE_EXT or LESSONS_MARK in real):
        return "held_by must be a hook, script or test file (code), got: " + value
    try:
        with open(full, "rb") as f:
            blob = f.read(MAX_HOLDER_BYTES).decode("utf-8", "ignore")
    except OSError as e:
        return "held_by cannot be read: " + str(e)
    if lesson_id not in blob:
        return "held_by file does not contain the lesson id '" + lesson_id + "': " + value
    return None


def check_prose_accepted(value):
    m = PROSE_RE.match(value or "")
    if not m:
        return "prose_accepted must start with a YYYY-MM-DD date, then the reason"
    try:
        when = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return "prose_accepted date is not a real YYYY-MM-DD date: " + m.group(1)
    if when.date() > datetime.now(timezone.utc).date():
        return "prose_accepted date is in the future: " + m.group(1)
    reason = m.group(2).strip()
    if len(reason) < 5 or not re.search(r"[A-Za-z]", reason):
        return "prose_accepted needs a reason after the date"
    return None


def check_text(text, name, root, legacy=False):
    """Every refusal for one lesson's text, as a list of strings (empty = valid).

    `legacy` = the lesson is byte-identical to origin/main: the holder requirement is waived
    (debt), but a holder field that IS present still has to be valid, and every other check
    still applies. lessons-distill.py imports this so a writer and the hook share ONE judge.
    """
    fm = parse_frontmatter(text)
    if fm is None:
        return [name + ": no/invalid YAML frontmatter"]
    errs = []
    extra = set(fm) - ALLOWED_KEYS
    if extra:
        errs.append("frontmatter keys outside " + str(sorted(ALLOWED_KEYS)) + ": " + str(sorted(extra)) + " (allowlist)")
    missing = BASE_KEYS - set(fm)
    if missing:
        errs.append("frontmatter missing required keys: " + str(sorted(missing)))
    if fm.get("kind") not in ALLOWED_KINDS:
        errs.append("kind=" + repr(fm.get("kind")) + " not in " + str(sorted(ALLOWED_KINDS)) + " (scar/rca forbidden)")
    for k, v in fm.items():
        if TOKEN_RE.search(str(v)):
            errs.append(k + " matches client-token denylist (no client identifiers in a fanned field)")
    has_held, has_prose = "held_by" in fm, "prose_accepted" in fm
    if has_held:
        e = check_held_by(fm["held_by"], fm.get("id", ""), root) if fm.get("id") else "held_by needs an id to link to"
        if e:
            errs.append(e)
    if has_prose:
        e = check_prose_accepted(fm["prose_accepted"])
        if e:
            errs.append(e)
    if not legacy and not (has_held or has_prose):
        errs.append("a new or changed lesson needs a linked held_by (path to a hook, script or test that contains "
                    "its id) or a dated prose_accepted (YYYY-MM-DD reason)")
    return errs


def debt(lessons_dir):
    """(lessons with neither holder field, total lessons)."""
    total = bad = 0
    try:
        names = sorted(os.listdir(lessons_dir))
    except OSError:
        return 0, 0
    for n in names:
        if n == "README.md" or not n.endswith(".md"):
            continue
        try:
            with open(os.path.join(lessons_dir, n)) as f:
                fm = parse_frontmatter(f.read())
        except OSError:
            continue
        total += 1
        if fm is None or not (set(fm) & HOLDER_KEYS):
            bad += 1
    return bad, total


def debt_line(lessons_dir):
    bad, total = debt(lessons_dir)
    return ("lessons-validator: debt: %d of %d lessons carry neither held_by nor prose_accepted "
            "(existing lessons, counted not refused)" % (bad, total))


def validate_file(path):
    """Errors for one lesson file on disk, deciding legacy-vs-new from the git baseline."""
    with open(path) as f:
        content = f.read()
    root = repo_root_of(path)
    rel = os.path.relpath(os.path.abspath(path), root) if root else None
    legacy = bool(root) and baseline_content(root, rel) == content
    return check_text(content, os.path.basename(path), root or os.path.dirname(os.path.abspath(path)), legacy)


def main_check_changed(repo):
    r = _git(repo, "status", "--porcelain=v1", "-uall", "--", "q-system/lessons")
    if r.returncode != 0:
        # Fail closed: an unreadable repo is not "no changed lessons" (review round 1, major).
        print("lessons-validator refused: cannot list changed lessons (git status failed): " + r.stderr.strip()[:200])
        return 2
    changed = []
    for line in r.stdout.splitlines():
        status, rel = line[:2], line[3:].strip().strip('"')
        if "D" in status or os.path.basename(rel) == "README.md" or not rel.endswith(".md"):
            continue
        changed.append(rel)
    refusals = []
    for rel in changed:
        try:
            errs = validate_file(os.path.join(repo, rel))
        except OSError:
            continue
        if errs:
            refusals.append("%s (%s)" % (os.path.basename(rel)[:-3], errs[0]))
    print(debt_line(os.path.join(repo, "q-system", "lessons")))
    if refusals:
        print("lessons-validator refused %d of %d changed lesson(s): %s" % (len(refusals), len(changed), "; ".join(refusals)))
        return 2
    return 0


def main_check_note(path):
    try:
        with open(path) as f:
            lines = [ln for ln in f.read().splitlines()]
    except OSError as e:
        print("lessons-validator: cannot read note: %s" % e, file=sys.stderr)
        return 2
    title = lines[0].lstrip("# ").strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    if not title or not body:
        print("lessons-validator: a learning note needs a title and a body", file=sys.stderr)
        return 2
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--debt":
        d = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lessons")
        print(debt_line(d))
        sys.exit(0)
    if argv and argv[0] == "--check-changed" and len(argv) > 1:
        sys.exit(main_check_changed(argv[1]))
    if argv and argv[0] == "--check-note" and len(argv) > 1:
        sys.exit(main_check_note(argv[1]))
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = payload.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ""
    if not fp:
        sys.exit(0)
    norm = fp.replace("\\", "/")
    if LESSONS_MARK not in norm:
        sys.exit(0)
    if os.path.basename(norm) == "README.md":
        sys.exit(0)
    try:
        errs = validate_file(fp)
    except OSError:
        sys.exit(0)  # PostToolUse: file is on disk; unreadable -> nothing to validate. OSError only: a bug in the checks must crash loud, not read as a pass.
    if errs:
        block("; ".join(errs))
    sys.stderr.write(debt_line(os.path.dirname(os.path.abspath(fp))) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
