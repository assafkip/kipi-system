"""Every headless model call site is either the metered wrapper or a NAMED exception.

why (ASK-2008, Step 2 of the ticket-flood plan). The per-bot usage ledger lives in
`plugins/kipi-core/voiceloop/prompt_render.run_model`; a script that shells
`claude -p` on its own is invisible to that ledger, so the Step 4 breaker
(ASK-2010) cannot see what it spends. On 2026-09-12 the fleet hit the weekly
limit and nothing could say which bot spent it. This test is the inventory the
breaker's blind spot is measured against.

THE LIST ONLY SHRINKS. A new direct call site fails this test until it goes
through the wrapper; an allowlisted site that starts going through the wrapper
(or disappears) fails it too, so the row has to be removed. `ALLOWLIST_CEILING`
pins the size and only ever goes down.

WHAT THE DETECTOR SEES, and what it does not, stated so its silence reads right:
  .py  an argv list or tuple literal holding the string "-p" right after a
       string ending in `claude` or a variable (the binary). A Python caller
       that assembles `claude -p` inside a shell string is NOT seen.
  .sh  a non-comment line running `claude -p` / `claude --print`, or a
       `$CLAUDE*` variable with `-p`, anywhere on the line (inside a `bash -c`
       string included, which is how linear-worker.sh calls it).
Test directories are skipped: a test that spends a real call is a token
problem, not a metering one, and their fixtures quote the pattern in prose.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: The one metered chokepoint. Everything else with a call is an exception.
WRAPPER = "plugins/kipi-core/voiceloop/prompt_render.py"

#: path -> why it still shells the model on its own. Removing a row is the
#: only edit this dict expects; adding one is a review question.
ALLOWLIST = {
    "plugins/prd-os/scripts/judgment_compiler.py":
        "builds argv for prd-os judgments; runs under linear-worker, unmetered",
    "q-system/.q-system/scripts/audhd-output-eval.py":
        "on-demand eval, founder-launched, never scheduled",
    "q-system/.q-system/scripts/design-reader-gate.py":
        "hook-time reader with --safe-mode, its own argv shape",
    "q-system/.q-system/scripts/fable-escalate.py":
        "the fable escalation caller, Popen with a stdin prompt, unmetered",
    "q-system/.q-system/scripts/granola-voice-synthesize.py":
        "on-demand synthesis, founder-launched",
    "q-system/.q-system/scripts/lessons-distill.py":
        "scheduled distiller, two direct calls, unmetered",
    "q-system/.q-system/scripts/linear-dor-drafter.py":
        "scheduled drafter with --tools '', unmetered",
    "q-system/.q-system/scripts/linear-triage.py":
        "scheduled triage, unmetered",
    "q-system/.q-system/scripts/linear-worker.sh":
        "the worker itself; bash -c string, the biggest unmetered spender",
    "q-system/.q-system/scripts/morning-brief.py":
        "scheduled brief with --allowedTools, unmetered",
    "q-system/.q-system/scripts/open-loops-heartbeat.sh":
        "headless call per instance (sp-c2dcebad), unmetered",
    "q-system/.q-system/scripts/pr-review-agent.sh":
        "the 2400s reviewer (sp-3bcc9e16), unmetered",
    "q-system/.q-system/scripts/probe_hook_envelope.py":
        "one-shot probe, founder-launched",
    "q-system/.q-system/scripts/skill-trigger-eval.py":
        "on-demand eval, founder-launched, never scheduled",
    "plugins/kipi-core/voiceloop/revise.py":
        "routed through run_model by PR #410; this row goes when that lands",
}
#: Only ever goes down. 15 measured 2026-09-22 on origin/main e838c03e.
ALLOWLIST_CEILING = 15

_TEST_DIR = re.compile(r"(^|/)(tests?|test)/|(^|/)test[_-]")
# Tracked review scratch trees (.review-tmp-pr11/, .review-scratch/) hold copies
# of the scripts above. They are not runtime and never scheduled; they are also
# tracked junk, which is a hygiene item and not this test's.
_SCRATCH = re.compile(r"^\.review-")
_PY_TEXT = re.compile(r""",\s*["']-p["']""")
_SH_CALL = re.compile(
    r"""(^|[\s"'(;&|`])(claude|\$\{?CLAUDE[A-Z_]*\}?)\s+(-p|--print)(\s|"|'|\\|$)""")


def _binary_like(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.endswith("claude")
    return isinstance(node, (ast.Name, ast.Attribute, ast.Subscript))


def _py_calls(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file this Python cannot parse is not thereby innocent: fall back to
        # the text shape of an argv element, so a caller cannot hide behind a
        # syntax the AST rejects.
        return bool(_PY_TEXT.search(text))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        elts = node.elts
        for i in range(1, len(elts)):
            e = elts[i]
            if (isinstance(e, ast.Constant) and e.value == "-p"
                    and _binary_like(elts[i - 1])):
                return True
    return False


def _sh_calls(text: str) -> bool:
    for line in text.splitlines():
        code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        if _SH_CALL.search(code):
            return True
    return False


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--", "*.py", "*.sh"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def call_sites(root: Path) -> set[str]:
    """Every tracked .py/.sh outside test directories that shells the model."""
    found = set()
    for rel in tracked(root):
        if _TEST_DIR.search(rel) or _SCRATCH.search(rel):
            continue
        try:
            text = (root / rel).read_text(errors="replace")
        except OSError:
            continue
        hit = _py_calls(text) if rel.endswith(".py") else _sh_calls(text)
        if hit:
            found.add(rel)
    return found


def unlisted(root: Path, allowlist=None) -> tuple[set, set]:
    """(sites with no row, rows with no site). Both must be empty."""
    rows = set(ALLOWLIST if allowlist is None else allowlist)
    sites = call_sites(root) - {WRAPPER}
    return sites - rows, rows - sites


def test_the_wrapper_is_a_call_site():
    # The detector must see the one site it exists to distinguish from the rest.
    assert WRAPPER in call_sites(ROOT)


def test_every_direct_model_call_is_a_named_exception():
    new, stale = unlisted(ROOT)
    assert not new, f"direct claude -p call with no allowlist row: {sorted(new)}"
    assert not stale, f"allowlist row with no call site left (remove it): {sorted(stale)}"


def test_the_allowlist_only_shrinks():
    assert len(ALLOWLIST) <= ALLOWLIST_CEILING


def test_a_planted_caller_is_seen(tmp_path):
    # Negative self-test on a throwaway repo: a real line from linear-triage.py
    # and a real line from linear-worker.sh, planted outside any test dir, must
    # both surface; the same lines under tests/ must not.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    py = 'res = subprocess.run([binary, "-p", prompt],\n                     capture_output=True)\n'
    sh = ('  if run_bounded "$T" bash -c "cd \'$TREE\' && KIPI_AGENT=\'$A\' claude -p '
          '\\"\\$1\\" </dev/null >>\'$LOG\' 2>&1" _ "$PROMPT"; then\n    :\n  fi\n')
    (tmp_path / "a.py").write_text("import subprocess\n" + py)
    (tmp_path / "b.sh").write_text("#!/bin/bash\n" + sh)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "c.py").write_text("import subprocess\n" + py)
    (tmp_path / "d.sh").write_text("#!/bin/bash\n# claude -p in a comment only\necho hi\n")
    (tmp_path / "e.py").write_text('MSG = "we run claude -p here"\n')
    # unparseable under this Python, still a caller: the text fallback sees it
    (tmp_path / "f.py").write_text('print "x"\nargv = [CLAUDE, "-p", prompt]\n')
    (tmp_path / ".review-scratch").mkdir()
    (tmp_path / ".review-scratch" / "g.sh").write_text("#!/bin/bash\n" + sh)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    assert call_sites(tmp_path) == {"a.py", "b.sh", "f.py"}
    new, stale = unlisted(tmp_path, allowlist={"a.py": "x", "f.py": "x", "gone.py": "x"})
    assert new == {"b.sh"} and stale == {"gone.py"}


if __name__ == "__main__":
    for site in sorted(call_sites(ROOT)):
        print(("wrapper  " if site == WRAPPER else "listed   " if site in ALLOWLIST else "UNLISTED ") + site)
    sys.exit(0)
