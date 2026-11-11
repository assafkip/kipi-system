"""K5 (ASK-4339): every new or changed lesson carries a linked held_by or a dated prose_accepted.

Pairs with lessons-validator.py and the three lesson writers (lessons-distill.py,
lessons-daily.sh, lesson-note.sh). The linkage rule is the one rule_gate.py enforces for
RULE-2026-11-08-CODE: the named holder exists, is code, and contains the id.

Every fixture lives in a tmp dir; nothing here touches the real lessons corpus.
Each refusal case has a paired accept case (test_each_refusal_has_an_accept_twin), so a
validator that refuses everything cannot pass.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
VALIDATOR = SCRIPTS / "lessons-validator.py"
DISTILL = SCRIPTS / "lessons-distill.py"
DAILY = SCRIPTS / "lessons-daily.sh"
NOTE = SCRIPTS / "lesson-note.sh"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# A hook runs this suite with GIT_DIR exported; it outranks `git -C` and a fixture commit
# would land in the real repo. Scrub for every subprocess we start.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.pop("KIPI_LESSONS_BASELINE_REF", None)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=CLEAN_ENV)


def make_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "q-system" / "lessons").mkdir(parents=True)
    (root / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (root / "q-system" / ".q-system" / "scripts" / "holder.sh").write_text("#!/bin/sh\n# guards: my-lesson\n")
    (root / "q-system" / ".q-system" / "scripts" / "other.sh").write_text("#!/bin/sh\n# unrelated\n")
    (root / "notes.md").write_text("my-lesson is mentioned in prose only\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed", "--no-gpg-sign")
    return root


def lesson(root, name="my-lesson", extra="", kind="pattern", title="Guard every mutation with one writer", date="2026-11-01"):
    p = root / "q-system" / "lessons" / f"{name}.md"
    p.write_text(f"---\nid: {name}\nkind: {kind}\ntitle: {title}\ndate: {date}\n{extra}---\n\nbody\n")
    return p


def hook(path, cwd=None):
    r = subprocess.run([sys.executable, str(VALIDATOR)], input=json.dumps({"tool_input": {"file_path": str(path)}}),
                       capture_output=True, text=True, env=CLEAN_ENV, cwd=cwd)
    return r.returncode, r.stderr + r.stdout


def refused(rc_out, needle=None):
    rc, out = rc_out
    assert rc == 2, f"expected exit 2, got {rc}: {out}"
    if needle:
        assert needle in out, f"refusal did not name {needle!r}: {out}"


def accepted(rc_out):
    rc, out = rc_out
    assert rc == 0, f"expected exit 0, got {rc}: {out}"


# ---- the holder requirement ----

def test_new_lesson_with_neither_field_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root)), "held_by")


def test_held_by_naming_a_missing_file_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/nope.sh\n")), "does not exist")


def test_held_by_file_without_the_lesson_id_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/other.sh\n")), "my-lesson")


def test_held_by_absolute_path_is_refused(tmp_path):
    root = make_repo(tmp_path)
    holder = root / "q-system" / ".q-system" / "scripts" / "holder.sh"
    refused(hook(lesson(root, extra=f"held_by: {holder}\n")), "repo-relative")


def test_held_by_parent_escape_is_refused(tmp_path):
    root = make_repo(tmp_path)
    outside = tmp_path / "outside.sh"
    outside.write_text("# my-lesson\n")
    refused(hook(lesson(root, extra="held_by: ../outside.sh\n")), "repo-relative")


def test_held_by_symlink_out_of_the_repo_is_refused(tmp_path):
    root = make_repo(tmp_path)
    outside = tmp_path / "outside.sh"
    outside.write_text("# my-lesson\n")
    link = root / "q-system" / ".q-system" / "scripts" / "link.sh"
    link.symlink_to(outside)
    refused(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/link.sh\n")), "inside the repo")


def test_held_by_prose_file_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra="held_by: notes.md\n")), "hook, script or test")


def test_valid_held_by_is_accepted(tmp_path):
    root = make_repo(tmp_path)
    accepted(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/holder.sh\n")))


# ---- prose_accepted ----

def test_prose_accepted_with_reason_and_date_is_accepted(tmp_path):
    root = make_repo(tmp_path)
    accepted(hook(lesson(root, extra=f"prose_accepted: {TODAY} judgment call, no deterministic check exists\n")))


def test_prose_accepted_without_a_date_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra="prose_accepted: judgment call, no deterministic check exists\n")), "YYYY-MM-DD")


def test_prose_accepted_with_an_impossible_date_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra="prose_accepted: 2026-13-45 judgment call\n")), "YYYY-MM-DD")


def test_prose_accepted_with_no_reason_is_refused(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra=f"prose_accepted: {TODAY}\n")), "reason")


# ---- the denylist runs over every value, not only the title ----

def test_denylist_runs_over_prose_accepted(tmp_path):
    root = make_repo(tmp_path)
    refused(hook(lesson(root, extra=f"prose_accepted: {TODAY} learned at KTLYST during a rollout\n")), "denylist")


def test_denylist_runs_over_held_by(tmp_path):
    root = make_repo(tmp_path)
    d = root / "q-system" / ".q-system" / "scripts" / "assaf-guard.sh"
    d.write_text("# my-lesson\n")
    refused(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/assaf-guard.sh\n")), "denylist")


# ---- existing lessons are debt, counted and printed, never refused ----

def test_unchanged_legacy_lesson_passes_and_the_debt_is_printed(tmp_path):
    root = make_repo(tmp_path)
    p = lesson(root, name="legacy-one")
    lesson(root, name="legacy-two")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "legacy", "--no-gpg-sign")
    rc, out = hook(p)
    assert rc == 0, out
    assert "debt: 2 of 2" in out, out


def test_changed_legacy_lesson_is_refused(tmp_path):
    root = make_repo(tmp_path)
    p = lesson(root, name="legacy-one")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "legacy", "--no-gpg-sign")
    p.write_text(p.read_text() + "an edit that makes it a changed lesson\n")
    refused(hook(p), "held_by")


def test_debt_flag_prints_the_number(tmp_path):
    root = make_repo(tmp_path)
    lesson(root, name="a-one")
    lesson(root, name="a-two", extra=f"prose_accepted: {TODAY} judgment call\n")
    r = subprocess.run([sys.executable, str(VALIDATOR), "--debt", str(root / "q-system" / "lessons")],
                       capture_output=True, text=True, env=CLEAN_ENV)
    assert r.returncode == 0, r.stderr
    assert "debt: 1 of 2" in r.stdout, r.stdout


def test_each_refusal_has_an_accept_twin(tmp_path):
    # Negative self-test of the suite: the same lesson flips from refused to accepted when
    # only the holder field is added, so a validator that refuses everything fails here.
    root = make_repo(tmp_path)
    refused(hook(lesson(root)))
    accepted(hook(lesson(root, extra="held_by: q-system/.q-system/scripts/holder.sh\n")))


# ---- the writers ----

def run_distill(tmp_path, kind_dir="rca"):
    inst = tmp_path / "projects" / "acme"
    src_dir = inst / "q-system" / "output" / kind_dir
    src_dir.mkdir(parents=True)
    src = src_dir / "src-1.md"
    src.write_text("# a source\n\n## Structural root cause\ngeneric cause.\n")
    import hashlib
    h = hashlib.sha1(src.read_text().encode()).hexdigest()[:16]
    (tmp_path / "registry.json").write_text(json.dumps({"instances": [{"name": "acme", "path": str(inst)}]}))
    (tmp_path / "distilled.json").write_text(json.dumps({h: {"title": "Guard shared mutations",
                                                              "body": "Route every mutation through one writer.", "kind": "pattern"}}))
    lessons = tmp_path / "lessons"
    r = subprocess.run([sys.executable, str(DISTILL), "--registry", str(tmp_path / "registry.json"), "--lessons-dir", str(lessons),
                        "--held-dir", str(tmp_path / "held"), "--ledger", str(tmp_path / "ledger.json"),
                        "--distilled-file", str(tmp_path / "distilled.json"), "--test-verify", "clean"],
                       capture_output=True, text=True, env=CLEAN_ENV)
    assert r.returncode == 0, r.stderr
    return lessons


def test_distill_writes_a_lesson_the_validator_accepts(tmp_path):
    for kind_dir in ("rca", "learnings"):
        sub = tmp_path / kind_dir
        sub.mkdir()
        lessons = run_distill(sub, kind_dir)
        files = list(lessons.glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text()
        assert "prose_accepted: " in text, text
        accepted(hook(files[0]))


def test_lesson_note_runs_the_validator_and_writes_a_note(tmp_path):
    qroot = tmp_path / "q-system"
    (qroot / ".q-system" / "scripts").mkdir(parents=True)
    for f in (NOTE, VALIDATOR):
        (qroot / ".q-system" / "scripts" / f.name).write_text(f.read_text())
    ok = subprocess.run(["bash", str(qroot / ".q-system" / "scripts" / "lesson-note.sh"), "A real title", "A real body"],
                        capture_output=True, text=True, env=CLEAN_ENV)
    assert ok.returncode == 0, ok.stderr
    assert len(list((qroot / "output" / "learnings").glob("NOTE-*.md"))) == 1
    bad = subprocess.run(["bash", str(qroot / ".q-system" / "scripts" / "lesson-note.sh"), "A title with no body"],
                         input="   \n", capture_output=True, text=True, env=CLEAN_ENV)
    assert bad.returncode != 0, "a note with an empty body must be refused"
    assert len(list((qroot / "output" / "learnings").glob("NOTE-*.md"))) == 1, "the refused note must not stay on disk"


def test_daily_reports_a_lesson_the_validator_refuses(tmp_path):
    root = make_repo(tmp_path)
    for f in (DAILY, VALIDATOR):
        dst = root / "q-system" / ".q-system" / "scripts" / f.name
        dst.write_text(f.read_text())
    git(root, "add", "-A")
    git(root, "commit", "-qm", "scripts", "--no-gpg-sign")
    lesson(root, name="bare-lesson")  # new, neither field
    lesson(root, name="good-lesson", extra=f"prose_accepted: {TODAY} judgment call\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/bash\nexit 0\n")
    (bin_dir / "claude").chmod(0o755)
    (tmp_path / "summary.json").write_text('{"scanned": 2, "published": ["a"], "held": []}')
    env = dict(CLEAN_ENV, PATH=f"{bin_dir}:{os.environ['PATH']}",
               KIPI_DISTILL_CMD=f"cat '{tmp_path}/summary.json'", KIPI_PROPAGATE_CMD="true", KIPI_NOTION_SYNC_CMD="true",
               KIPI_NOTIFY_CMD=f"printf '%s\\n' \"$1\" >> '{tmp_path}/notify.txt'",
               KIPI_LESSONS_LOG=str(tmp_path / "daily.log"), KIPI_STREAK_FILE=str(tmp_path / "streak.json"),
               KIPI_ESCALATIONS_FILE=str(tmp_path / "esc.jsonl"))
    subprocess.run(["bash", str(root / "q-system" / ".q-system" / "scripts" / "lessons-daily.sh")],
                   capture_output=True, text=True, env=env, timeout=120)
    log = (tmp_path / "daily.log").read_text()
    assert "lessons-validator refused" in log and "bare-lesson" in log, log
    assert "good-lesson" not in log.split("lessons-validator refused", 1)[1].split("\n", 1)[0], log


def test_held_by_symlink_to_the_lesson_itself_is_refused(tmp_path):
    root = make_repo(tmp_path)
    p = lesson(root, extra="held_by: q-system/.q-system/scripts/selfy.py\n")
    (root / "q-system" / ".q-system" / "scripts" / "selfy.py").symlink_to(p)
    refused(hook(p), "hook, script or test")


def test_check_changed_outside_a_git_repo_is_refused(tmp_path):
    r = subprocess.run([sys.executable, str(VALIDATOR), "--check-changed", str(tmp_path)],
                       capture_output=True, text=True, env=CLEAN_ENV)
    assert r.returncode == 2, r.stdout + r.stderr
