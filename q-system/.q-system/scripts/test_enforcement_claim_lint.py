#!/usr/bin/env python3
"""Reproducer + negative self-tests for the enforcement-claim half of
capability-claim-lint.py (ASK-3818, RULE-2026-11-06-A).

RED FIRST: `.claude/rules/no-orphan-findings.md:37` said "`gates run` fails while
any item is open". No `gates` executable exists here, and prd-os's real one fails
only on items attributable to the run's scope. The fixture below is that line;
the lint must exit 2 naming it.

The real-repo test pins the rule sections this change corrected. Their Rule-IDs
live here because rule_gate.py (RULE-2026-11-08-CODE) wants each section's
enforcer to name it:
  RULE-2026-11-25-BACKSTOP  no-orphan-findings.md, "Deterministic backstops"
  RULE-2026-11-25-WIDEN     instrument-discipline.md, "Why it guards /output/ now"
  RULE-2026-11-25-CALLER    repair-first-generation.md, "The caller's obligation"
  RULE-2026-11-25-FABLEINV  fable-discipline-auto-invoke.md (the whole file)
  RULE-2026-11-25-TIERA     fable-escalation.md, "Tier A"

Everything runs in temp dirs with a temp HOME. Run: python3 test_enforcement_claim_lint.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE / "capability-claim-lint.py"
MEMV = HERE / "memory-confidence-validator.py"
REPO = HERE.parents[2]

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        if detail:
            print("    " + str(detail)[:1500])


def run(args, cwd=None, env_extra=None, stdin=None):
    home = tempfile.mkdtemp(prefix="ecl-home-")
    env = dict(os.environ, HOME=home)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, *args], cwd=cwd, env=env, input=stdin,
                       capture_output=True, text=True, check=False)
    return r.returncode, r.stdout + r.stderr


def tree(rule_body: str, extra: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="ecl-root-"))
    (root / ".claude/rules").mkdir(parents=True)
    (root / ".claude/rules/r.md").write_text(rule_body)
    for rel, text in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


GATES_LINE = "- `gates run` fails while any item is open (the enforcement of last resort).\n"


def test_red_on_the_ticket_line():
    root = tree("## Backstops\n\n" + GATES_LINE)
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("red: the no-orphan-findings:37 shape exits 2", rc == 2, out)
    check("red: the finding names file:line", ".claude/rules/r.md:3:" in out, out)


def test_bullet_neighbour_does_not_hold():
    # Scar: with a +/-1 line window the next bullet's wired script vouched for line 37.
    body = ("## Backstops\n\n" + GATES_LINE +
            "- `spill-check.py` (daily launchd) retries failed filings.\n")
    root = tree(body, {"lefthook.yml": "x:\n  run: python3 spill-check.py\n",
                       "spill-check.py": "import sys\nsys.exit(2)\n"})
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("a wired script on the NEXT bullet does not hold this one", rc == 2, out)


def test_wrapped_line_is_held_by_the_line_above():
    body = ("## B\n\nThe hook `spill-check.py` runs at commit and the\n"
            "`--strict` flag exits 1 on findings.\n")
    root = tree(body, {"lefthook.yml": "run: python3 spill-check.py\n",
                       "spill-check.py": "x\n"})
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("a continuation line is held by the wired script it wraps from", rc == 0, out)


def test_wired_subject_holds_unwired_does_not():
    line = "- `deny-thing.py` blocks the write.\n"
    wired = tree("## B\n\n" + line, {"deny-thing.py": "x\n",
                                      ".claude/settings.json": '{"c": "deny-thing.py"}'})
    rc, out = run([str(LINT), "--all", "--root", str(wired)])
    check("a subject that is a wired script holds itself", rc == 0, out)
    unwired = tree("## B\n\n" + line, {"deny-thing.py": "x\n"})
    rc, out = run([str(LINT), "--all", "--root", str(unwired)])
    check("the same script with no config naming it does not", rc == 2, out)


def test_tags():
    held = tree("## B\n\n" + GATES_LINE.rstrip("\n") + " held_by: tests/test_gate.py\n",
                {"tests/test_gate.py": "def test_x(): pass\n",
                 "lefthook.yml": "t:\n  run: python3 tests/test_gate.py\n"})
    rc, out = run([str(LINT), "--all", "--root", str(held)])
    check("held_by naming a run test passes", rc == 0, out)

    # Review round 1: a 0-byte test_*.py held any claim.
    for body, name in (("", "an empty test file"),
                       ("def test_x(): pass\n", "an untracked, unrun test")):
        t = tree("## B\n\n" + GATES_LINE.rstrip("\n") + " held_by: tests/test_gate.py\n",
                 {"tests/test_gate.py": body})
        rc, out = run([str(LINT), "--all", "--root", str(t)])
        check(f"held_by naming {name} is refused", rc == 2, out)

    ghost = tree("## B\n\n" + GATES_LINE.rstrip("\n") + " held_by: tests/test_ghost.py\n")
    rc, out = run([str(LINT), "--all", "--root", str(ghost)])
    check("held_by naming a missing file is refused", rc == 2 and "resolves to no file" in out, out)

    unrun = tree("## B\n\n- Things are never shipped. held_by: tools/x.py\n",
                 {"tools/x.py": "x\n"})
    rc, out = run([str(LINT), "--all", "--root", str(unrun)])
    check("held_by naming a script nothing runs is refused", rc == 2 and "nothing runs it" in out, out)

    for tag, want, name in (
        ("ticket: ASK-1", 2, "ticket without expires is refused"),
        ("ticket: ASK-1 expires: 2020-01-01", 2, "an expired ticket is refused"),
        ("ticket: ASK-1 expires: 2999-01-01", 0, "a live ticket with expiry passes"),
        ("kind: observation", 0, "kind: observation passes (RCA 696)"),
    ):
        root = tree("## B\n\n" + GATES_LINE.rstrip("\n") + " " + tag + "\n")
        rc, out = run([str(LINT), "--all", "--root", str(root)])
        check(name, rc == want, out)


def test_plain_prose_claims():
    # Review round 1: the scar sentence with its backticks removed walked past.
    root = tree("## B\n\n- gates run fails while any item is open.\n")
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("the scar sentence without backticks is red", rc == 2, out)
    root = tree("## B\n\n- The fable-discipline lint hook also blocks deferral language.\n")
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("a plain 'X hook also blocks' claim is red", rc == 2, out)
    for line, name in (("Common blocks and what to do:", "a noun 'blocks'"),
                       ("A repair step that fails must be loud.", "a relative clause"),
                       ("If the push fails, retry it.", "a condition"),
                       ("The hook never blocks.", "a negation")):
        root = tree("## B\n\n" + line + "\n")
        rc, out = run([str(LINT), "--all", "--root", str(root)])
        check(f"{name} is not a mechanism claim", rc == 0, out)


def test_pronoun_takes_the_paragraph_above():
    wired = {"lefthook.yml": "run: python3 null-lint.py\n", "null-lint.py": "x\n"}
    root = tree("## B\n\n`null-lint.py` runs on every write.\n\nIt blocks a null claim.\n",
                wired)
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("'It blocks' is held by the wired script the paragraph above names", rc == 0, out)
    root = tree("## B\n\nSome prose.\n\nIt blocks a null claim.\n", wired)
    rc, out = run([str(LINT), "--all", "--root", str(root)])
    check("'It blocks' with no enforcer above is red", rc == 2, out)


def test_user_settings_do_not_hold_in_all_mode():
    # Review round 1: --all read ~/.claude/settings.json, so a holder wired only
    # there passed on the laptop and failed in CI.
    root = tree("## B\n\n- `glob-hook.py` blocks the write.\n", {"glob-hook.py": "x\n"})
    home = Path(tempfile.mkdtemp(prefix="ecl-us-"))
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text('{"c": "glob-hook.py"}')
    rc, out = run([str(LINT), "--all", "--root", str(root)], env_extra={"HOME": str(home)})
    check("--all ignores a holder wired only in ~/.claude/settings.json", rc == 2, out)


def test_census_reader():
    body = ("# Decisions\n\n"
            "- **DEC-1 [USER-DIRECTED]: never send mail unattended.**\n"
            "  held_by: tests/test_send.py\n"
            "- **DEC-2: pings are rejected.** ticket: ASK-9 expires: 2999-01-01\n"
            "- **DEC-3: a measured fact.** kind: observation\n"
            "- **DEC-4: no Gmail drafts, PERMANENT.**\n")
    root = tree("## x\n", {"crm.md": body, "tests/test_send.py": "def test_x(): pass\n",
                            "lefthook.yml": "run: python3 tests/test_send.py\n"})
    (root / ".git").mkdir()
    rr = r"^\s*[-*]\s*\**DEC-\d+"
    rc, out = run([str(LINT), "--census", str(root / "crm.md"), "--record-re", rr, "--json"])
    try:
        rep = json.loads(out)
    except ValueError:
        rep = {}
    check("census exits 2 while a record is missing", rc == 2, out)
    check("census counts held/ticketed/observation",
          (rep.get("records"), rep.get("held"), rep.get("ticketed"), rep.get("observation"))
          == (4, 1, 1, 1), rep)
    check("census names the missing record's line",
          [m["line"] for m in rep.get("missing", [])] == [7], rep)
    (root / "crm.md").write_text(body.replace("PERMANENT.**", "PERMANENT.** held_by: tests/test_send.py"))
    rc, out = run([str(LINT), "--census", str(root / "crm.md"), "--record-re", rr, "--json"])
    check("census exits 0 once every record is held", rc == 0, out)
    (root / "empty.md").write_text("# nothing\n")
    rc, out = run([str(LINT), "--census", str(root / "empty.md"), "--record-re", rr, "--json"])
    check("census over zero records is not ok (a wrong regex cannot read green)", rc == 2, out)
    rc, out = run([str(LINT), "--census", str(root / "absent.md"), "--json"])
    check("census of an unreadable file exits 3", rc == 3, out)


def test_hook_census():
    home = Path(tempfile.mkdtemp(prefix="ecl-hc-"))
    hooks = home / ".claude/hooks"
    hooks.mkdir(parents=True)
    (hooks / "deny.sh").write_text("#!/bin/sh\nexit 2\n")
    (hooks / "soft.sh").write_text("#!/bin/sh\nexit 2\n")
    (hooks / "talk.sh").write_text("#!/bin/sh\necho hi\n")
    (hooks / "allow.sh").write_text('echo \'{"permissionDecision": "allow"}\'\n')
    (hooks / "denyjson.sh").write_text('echo \'{"permissionDecision": "deny"}\'\n')
    (hooks / "old.sh.bak").write_text("exit 2\n")
    (hooks / "orphan.sh").write_text("exit 2\n")
    settings = {"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": "bash ~/.claude/hooks/deny.sh"},
        {"type": "command", "command": "bash ~/.claude/hooks/allow.sh"},
        {"type": "command", "command": "bash ~/.claude/hooks/denyjson.sh"},
        {"type": "command", "command": "bash ~/.claude/hooks/soft.sh || true"},
        {"type": "command", "command": "test -f ~/.claude/hooks/talk.sh && bash ~/.claude/hooks/talk.sh"},
    ]}]}}
    (home / ".claude/settings.json").write_text(json.dumps(settings))
    rc, out = run([str(LINT), "--hook-census", "--hooks-dir", str(hooks),
                   "--root", str(home), "--json"])
    rep = json.loads(out) if rc == 0 else {}
    cls = {f["file"]: f["class"] for f in rep.get("files", [])}
    check("hook census classifies deny/advisory/retired",
          cls == {"deny.sh": "deny", "soft.sh": "advisory", "talk.sh": "advisory",
                  "old.sh.bak": "retired", "orphan.sh": "retired",
                  "allow.sh": "advisory", "denyjson.sh": "deny"}, cls)
    check("hook census counts advisory entries", rep.get("advisory_entries") == 2, rep)
    rc, out = run([str(LINT), "--hook-census", "--hooks-dir", str(hooks), "--root", str(home)])
    check("text census prints the advisory count line",
          "advisory hook entries: 2 of 5" in out, out)


def test_memory_note_refusal():
    home = Path(tempfile.mkdtemp(prefix="ecl-mem-"))
    note = home / ".claude/projects/p/memory/feedback_x.md"
    note.parent.mkdir(parents=True)

    def write(text):
        note.write_text(text)
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(note)}})
        return run([str(MEMV)], stdin=payload, env_extra={"HOME": str(home),
                                                           "CLAUDE_PROJECT_DIR": str(home)})

    fm = "---\nname: x\ndescription: y\nmetadata:\n  type: feedback\n---\n"
    # Review round 1: 689 of 964 existing notes would have been refused. A note
    # that existed when the baseline was taken passes while unchanged.
    old = note.parent / "feedback_old.md"
    old_text = fm + "Always run the suite before pushing.\n"
    old.write_text(old_text)
    rc, out = write(fm + "Never push on Fridays.\n")
    base = home / ".config/kipi/memory-claim-baseline.json"
    check("the first write records the baseline", base.is_file(), out)
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(old)}})
    rc2, out2 = run([str(MEMV)], stdin=payload, env_extra={"HOME": str(home),
                                                            "CLAUDE_PROJECT_DIR": str(home)})
    check("an old untagged note, unchanged, passes", rc2 == 0, out2)
    old.write_text(old_text + "Also on Mondays.\n")
    rc2, out2 = run([str(MEMV)], stdin=payload, env_extra={"HOME": str(home),
                                                            "CLAUDE_PROJECT_DIR": str(home)})
    check("the same old note, changed, is refused", rc2 == 2 and "ASK-3818" in out2, out2)
    check("a 'never' memory note with no holder is refused", rc == 2 and "ASK-3818" in out, out)
    rc, out = write(fm + "Never push on Fridays.\nkind: observation\n")
    check("the same note as kind: observation passes", rc == 0, out)
    rc, out = write(fm + "Never push on Fridays.\nticket: ASK-1 expires: 2999-01-01\n")
    check("the same note with ticket+expires passes", rc == 0, out)
    rc, out = write(fm + "The deploy took 4 minutes.\n")
    check("a note with no directive word passes untouched", rc == 0, out)


def test_real_repo_is_clean():
    # Pins RULE-2026-11-25-BACKSTOP, -WIDEN, -CALLER, -FABLEINV and -TIERA:
    # the corrected lines carry their holders, and the repo's own rules lint clean.
    rc, out = run([str(LINT), "--all", "--root", str(REPO)])
    check("this repo's rule files carry no unheld mechanism claim", rc == 0, out)
    line37 = (REPO / ".claude/rules/no-orphan-findings.md").read_text()
    check("no-orphan-findings no longer claims gates run fails on ANY open item",
          "fails while any item is open" not in line37)
    # Review round 1: an inherited blocker DOES turn gates run red, and the
    # sentence must say so, held by the test that seeds an inherited blocker.
    check("the backstop line states the inherited-blocker floor",
          "inherited item only when it is a `blocker`" in line37
          and "test_spillover_combined_rule.py" in line37)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)
