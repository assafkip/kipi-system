#!/usr/bin/env python3
"""review-tier.py -- deterministic ESCALATE/SELF classifier for review routing.

Answers ONE question from a diff: does this change need an independent (Codex)
review, or is self-review sufficient? The answer is derived from the changed
paths and the changed lines. Never from a description, a commit body, or an
agent's opinion of its own work.

WHY THIS EXISTS (founder directive 2026-08-01): the Linear agent was going to
decide for itself when to hand off to Codex. An agent that judges whether it
needs checking will under-call it -- that is self-assessment, which is what a
prompt gives you, not a gate. Measured the same night: ~15 PRs got Codex, one of
them a 13-line comment-only change, several four or five rounds deep. Meanwhile
linear-dor-drafter.py had six layers of one defect, each caught by a fresh pass,
and a seventh caught only by mutation testing inside the fix. Same treatment for
both is wrong in both directions.

THE ASYMMETRY (this is the whole point):
  exit 0  = SELF      -- and exit 0 is the ONLY code that authorizes self-review
  exit 10 = ESCALATE  -- independent review required
  exit 2  = ERROR     -- unclassifiable input

Callers MUST spell the contract `review-tier.py ... || run_independent_review`.
Every non-zero code, including a crash or an unparseable diff, means "do not
self-review". A gate fails closed; a filter fails open. This one is a gate.

An agent may escalate UPWARD on instinct. It may never de-escalate below what
this returns. NOTE: this file is the CLASSIFIER, not the enforcement. Nothing
here stops a caller from ignoring the exit code -- that needs a hook on the
review-dispatch path, which is a separate, not-yet-built step. Do not describe
this script alone as enforcement.

PRECEDENCE: every escalate trigger is evaluated across all files FIRST. Only if
none fire do we ask whether every changed file is self-safe. Anything matching
neither list escalates. Unknown is not safe.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

TIER_SELF = "SELF"
TIER_ESCALATE = "ESCALATE"
EXIT_SELF = 0
EXIT_ESCALATE = 10
EXIT_ERROR = 2

# --- escalate: scripts the autonomous loop executes ---------------------------
# Founder-named, 2026-08-01. These run unattended: a defect here is not caught by
# a human noticing odd output, because no human is watching when they run.
LOOP_CRITICAL = {
    "linear-worker.sh", "converge.sh", "kipi-dispatch.sh", "pr-review-agent.sh",
    "linear-dor-drafter.py", "slack-notify.sh", "token-guard.py",
    "attempts-ledger.py",
}

# --- escalate: wiring surfaces / required checks ------------------------------
WIRING_FILES = {
    ".claude/settings.json", ".claude/settings.local.json",
    "settings-template.json",
}
# capability-manifest.json holds expected_tests (the fleet's required-test
# roster); gates.jsonl holds registered bypass gates. Editing either adds or
# removes a required check.
REQUIRED_CHECK_FILES = {
    "q-system/.q-system/capability-manifest.json",
    ".prd-os/gates.jsonl",
}
REQUIRED_CHECK_KEY = re.compile(r"^\s*(-\s*)?required_checks\s*:|required_checks")

# Prose the runtime LOADS is not documentation. Editing a rule, skill, command
# or plugin manifest changes behaviour exactly as much as editing code.
# Scar (2026-06-20): a gap-class checklist was "wired" into an instance's
# plugins/ dir; the runtime loaded the marketplace clone, so the edit sat inert
# for weeks. Prose-as-code is why a .md suffix alone never proves "just docs".
EXECUTABLE_PROSE = re.compile(
    r"(^|/)(CLAUDE\.md|SKILL\.md|plugin\.json|hooks\.json)$"
    r"|(^|/)\.claude/"
    r"|(^|/)(rules|commands|agents|skills|hooks)/"
    r"|^\.prd-os/"
)

# --- escalate: declared data paths and single-writer stores -------------------
# system-manifest.json + evidence.jsonl are the declared data-path manifest and
# its evidence ledger (.claude/rules/evidence-ledger.md). Any *.jsonl here is an
# append-only ledger, and every real DB suffix is a live store. The lint that
# guards tests uses the same DB-suffix set (fable-discipline-lint _DBPATH).
DATA_PATH = re.compile(
    r"(^|/)canonical/(system-manifest\.json|evidence\.jsonl)$"
    r"|\.jsonl$"
    r"|\.(db|sqlite|sqlite3|duckdb)$"
)
# No machine-readable single-writer registry exists; chokepoints are marked in
# code by this phrase (q-system/lessons/single-writer-chokepoint.md).
SINGLE_WRITER = re.compile(r"single[-\s]writer|chokepoint", re.IGNORECASE)

# --- escalate: scar comments --------------------------------------------------
# No single canonical token. Three real forms in this corpus: the word scar, a
# spillover id, an issue/RCA id.
#
# The id alone is NOT high-signal, measured 2026-08-01: the first draft of this
# script flagged `"identifier": "ASK-901"` -- Linear FIXTURE DATA in a test -- as
# a scar comment. So an id counts only on a comment-leading line. The word
# "scar" survives anywhere in a code file, because the docstring form
# (`Scar (2026-07-02, <instance>): ...`) carries the word but often no id.
# Skipped for prose files, where these ids are ordinary references.
SCAR_ID = re.compile(r"\bsp-[0-9a-f]{8}\b|\bASK-\d+\b"
                     r"|\brca-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\b"
                     r"|\bRULE-\d{4}-\d{2}-\d{2}")
SCAR_WORD = re.compile(r"\bscars?\b", re.IGNORECASE)
COMMENT_LEADING = re.compile(r"^\s*(#|//|\*|--)")

# --- self-safe: tests and docs ------------------------------------------------
TEST_PATH = re.compile(
    r"(^|/)tests?/"
    r"|(^|/)test[_-][^/]*\.(py|sh|bash)$"
    r"|(^|/)[^/]*[_-]test\.(py|sh|bash)$"
)
DOC_SUFFIX = {".md", ".markdown", ".txt", ".rst"}

# --- self-safe: config VALUE allowlist ----------------------------------------
# DELIBERATELY EMPTY. The rule is "a config VALUE inside an explicit allowlist";
# an allowlist nobody has populated must admit nothing, or the category becomes a
# catch-all that swallows real changes. Same contract as prd-os's empty
# allowed_files meaning deny-all. Add a path only with a named reason: every
# addition widens what skips independent review.
CONFIG_VALUE_ALLOWLIST: set = set()

# --- comment tokens -----------------------------------------------------------
# Shell is deliberately ABSENT. Measured 2026-08-01 on this repo: linear-worker.sh
# carries 34 '#'-leading lines INSIDE heredocs and converge.sh one more. A diff
# hunk does not carry the heredoc state needed to prove a '#' line is a comment
# rather than data (pr-review-agent.sh:676 uses an UNQUOTED `<<EOF`, where such a
# line is expanded and live). Rather than guess, shell files are never eligible
# for the comment-only class. Costs some false escalates; a false SELF is the
# unrecoverable direction.
COMMENT_TOKEN = {
    ".py": "#", ".toml": "#", ".yml": "#", ".yaml": "#", ".cfg": "#", ".ini": "#",
    ".js": "//", ".ts": "//", ".jsx": "//", ".tsx": "//", ".go": "//",
    ".c": "//", ".h": "//", ".java": "//", ".rs": "//",
}

REVERT_SUBJECT = re.compile(r"^\s*revert[:\s\"']", re.IGNORECASE)


class DiffError(Exception):
    pass


def parse_diff(text):
    """Unified diff -> {path: {"added": [str], "removed": [str], "status": str}}."""
    files = {}
    cur = None
    for line in text.split("\n"):
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if m:
            apath, bpath = m.group(1), m.group(2)
            cur = bpath if bpath != "/dev/null" else apath
            files[cur] = {"added": [], "removed": [], "status": "modified"}
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            files[cur]["status"] = "added"
        elif line.startswith("deleted file mode"):
            files[cur]["status"] = "deleted"
        elif line.startswith("rename from") or line.startswith("rename to"):
            files[cur]["status"] = "renamed"
        elif line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("+"):
            files[cur]["added"].append(line[1:])
        elif line.startswith("-"):
            files[cur]["removed"].append(line[1:])
    if not files:
        raise DiffError("no `diff --git` headers found; not a unified diff")
    return files


def wired_scripts(root):
    """Script basenames referenced from the settings files.

    Read from the repo, never hardcoded: a hook wired tomorrow must escalate
    tomorrow without anyone remembering to edit this list.
    """
    out = set()
    for rel in (".claude/settings.json", "settings-template.json",
                ".claude/settings.local.json"):
        p = root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text()
        except OSError:
            continue
        for hit in re.findall(r"[\w./${}-]+\.(?:py|sh)", text):
            out.add(os.path.basename(hit))
    return out


def registered_instances(root):
    """-> [(name, absolute path)] from instance-registry.json."""
    p = root / "instance-registry.json"
    if not p.is_file():
        return []
    try:
        reg = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for entry in reg.get("instances", []) or []:
        if entry.get("path"):
            out.append((entry.get("name") or entry["path"],
                        entry["path"].rstrip("/")))
    return out


def is_prose(path):
    return pathlib.Path(path).suffix.lower() in DOC_SUFFIX


def scar_lines(path, info):
    """Changed lines carrying a scar marker. Code files only."""
    if is_prose(path):
        return []
    hits = []
    for raw in info["added"] + info["removed"]:
        if SCAR_WORD.search(raw):
            hits.append(raw)
        elif COMMENT_LEADING.match(raw) and SCAR_ID.search(raw):
            hits.append(raw)
    return hits


def is_comment_only(path, info):
    """True only if every changed line is provably a comment or blank."""
    token = COMMENT_TOKEN.get(pathlib.Path(path).suffix)
    if token is None:
        return False
    lines = info["added"] + info["removed"]
    if not lines:
        return False
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith(token):
            return False
    return True


def self_safe(path, info):
    """(bool, category). The four self-sufficient categories, in order."""
    if EXECUTABLE_PROSE.search(path):
        return False, None
    if TEST_PATH.search(path):
        return True, "test-only file"
    if is_prose(path):
        return True, "pure docs/markdown"
    if path in CONFIG_VALUE_ALLOWLIST:
        return True, "config value in explicit allowlist"
    if is_comment_only(path, info):
        return True, "comment-only hunks"
    return False, None


def classify(files, root, subject=""):
    """-> (tier, [reason]). Escalate triggers beat every self-safe category."""
    reasons = []
    wired = wired_scripts(root)
    instances = registered_instances(root)
    root_str = str(root)

    if subject and REVERT_SUBJECT.match(subject):
        reasons.append(f'change is a revert (subject: "{subject.strip()[:60]}")')

    for name, ipath in instances:
        if root_str == ipath or root_str.startswith(ipath + "/"):
            reasons.append(
                f"change lands inside registered client repo {name} ({ipath})")
            break

    for path, info in sorted(files.items()):
        base = os.path.basename(path)
        changed = info["added"] + info["removed"]

        if base in LOOP_CRITICAL:
            reasons.append(f"{path}: script the autonomous loop executes ({base})")

        if path in WIRING_FILES or base in WIRING_FILES:
            reasons.append(f"{path}: settings wiring surface")

        if path in REQUIRED_CHECK_FILES or base in REQUIRED_CHECK_FILES:
            reasons.append(f"{path}: adds or removes a required check")
        elif path.startswith(".prd-os/issues/") and any(
                REQUIRED_CHECK_KEY.search(ln) for ln in changed):
            reasons.append(f"{path}: edits required_checks on an issue spec")

        if base in wired and base not in LOOP_CRITICAL:
            reasons.append(
                f"{path}: gate/hook/validator wired from settings.json "
                f"or settings-template.json")

        if DATA_PATH.search(path):
            reasons.append(f"{path}: declared data path or append-only ledger")
        elif (not TEST_PATH.search(path) and not is_prose(path)
                and any(SINGLE_WRITER.search(ln) for ln in changed)):
            # Tests and docs are excluded on purpose: a test that only NAMES the
            # chokepoint does not write to the store, and the founder's own list
            # makes a test-only file self-sufficient. Measured 2026-08-01: the
            # first draft escalated a 1177-line test purely for the phrase.
            reasons.append(f"{path}: touches a single-writer chokepoint")

        for name, ipath in instances:
            if path.startswith(ipath.lstrip("/")) or ipath in path:
                reasons.append(f"{path}: registered client-repo path ({name})")
                break

        scars = scar_lines(path, info)
        if scars:
            reasons.append(
                f"{path}: hunk carries a scar comment ({scars[0].strip()[:60]})")

    if reasons:
        return TIER_ESCALATE, reasons

    unsafe, safe_notes = [], []
    for path, info in sorted(files.items()):
        ok, category = self_safe(path, info)
        (safe_notes if ok else unsafe).append(
            f"{path}: {category}" if ok else path)

    if unsafe:
        return TIER_ESCALATE, [
            f"{p}: matches no self-review category (unknown is not safe)"
            for p in unsafe]
    return TIER_SELF, safe_notes


def load_diff(args):
    if args.diff_file:
        return pathlib.Path(args.diff_file).read_text(), args.subject or ""
    env = dict(os.environ)
    env.setdefault("KIPI_NOTIFY", "/usr/bin/true")
    if args.pr:
        diff = subprocess.run(["gh", "pr", "diff", str(args.pr)],
                              capture_output=True, text=True, env=env)
        if diff.returncode != 0:
            raise DiffError(f"gh pr diff {args.pr} failed: "
                            f"{diff.stderr.strip()[:200]}")
        subject = args.subject
        if not subject:
            meta = subprocess.run(
                ["gh", "pr", "view", str(args.pr), "--json", "title"],
                capture_output=True, text=True, env=env)
            if meta.returncode == 0:
                try:
                    subject = json.loads(meta.stdout).get("title", "")
                except ValueError:
                    subject = ""
        return diff.stdout, subject or ""
    if args.range:
        diff = subprocess.run(["git", "diff", args.range], capture_output=True,
                              text=True, cwd=args.root, env=env)
        if diff.returncode != 0:
            raise DiffError(f"git diff {args.range} failed: "
                            f"{diff.stderr.strip()[:200]}")
        subject = args.subject
        if not subject:
            log = subprocess.run(["git", "log", "--format=%s", args.range],
                                 capture_output=True, text=True, cwd=args.root,
                                 env=env)
            subject = log.stdout.strip().split("\n")[0] if log.returncode == 0 else ""
        return diff.stdout, subject or ""
    raise DiffError("one of --pr, --range or --diff-file is required")


def main():
    ap = argparse.ArgumentParser(
        description="Decide whether a change needs independent (Codex) review.")
    ap.add_argument("--pr", type=int, help="PR number (uses gh pr diff)")
    ap.add_argument("--range", help="git range, e.g. main..HEAD")
    ap.add_argument("--diff-file", help="read a unified diff from a file")
    ap.add_argument("--subject", default="",
                    help="commit/PR subject, for revert detection")
    ap.add_argument("--root", default=os.environ.get("KIPI_ROOT", "."),
                    help="repo root holding settings.json / instance-registry.json")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    try:
        text, subject = load_diff(args)
        files = parse_diff(text)
        tier, reasons = classify(files, pathlib.Path(args.root).resolve(), subject)
    except (DiffError, OSError) as exc:
        # Fail closed. Input we cannot classify is not a self-review licence.
        print(f"ERROR: {exc}", file=sys.stderr)
        print("ERROR unclassifiable input -- treat as ESCALATE", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps({"tier": tier, "reasons": reasons,
                          "files": sorted(files)}, indent=2))
    else:
        print(tier)
        for r in reasons:
            print(f"  - {r}")
    return EXIT_SELF if tier == TIER_SELF else EXIT_ESCALATE


if __name__ == "__main__":
    sys.exit(main())
