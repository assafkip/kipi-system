"""Wiring contract for the execution-discipline layer (fable-discipline merge).

prd-fable-discipline-2026-07-04, issue fable-merge-into-prd-os. Single-writer
rule: exactly ONE plugin owns fable-discipline-lint. After the merge that
owner is prd-os; a copy left wired in kipi-core would fire the hook twice on
every edit (the pre-0.5.0 double-fire scar, see CHANGELOG "Removed").
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRD_OS_HOOKS = REPO / "plugins/prd-os/hooks/hooks.json"
KIPI_CORE_HOOKS = REPO / "plugins/kipi-core/hooks/hooks.json"
SKILL_DIR = REPO / "plugins/prd-os/skills/fable-discipline"


def _commands(hooks_path: Path) -> list[str]:
    data = json.loads(hooks_path.read_text())
    out = []
    for entries in (data.get("hooks") or {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                out.append(hook.get("command", ""))
    return out


def test_prd_os_owns_fable_discipline_lint():
    cmds = [c for c in _commands(PRD_OS_HOOKS) if "fable-discipline-lint" in c]
    assert cmds, "fable-discipline-lint is not wired in prd-os hooks.json"
    assert all("${CLAUDE_PLUGIN_ROOT}" in c for c in cmds), (
        "lint hook must resolve via CLAUDE_PLUGIN_ROOT, not a repo path"
    )


def test_kipi_core_no_longer_wires_the_lint():
    cmds = [c for c in _commands(KIPI_CORE_HOOKS) if "fable-discipline-lint" in c]
    assert not cmds, f"kipi-core still wires fable-discipline-lint: {cmds}"


def test_skill_lives_in_prd_os_with_lint_and_test():
    assert (SKILL_DIR / "SKILL.md").is_file()
    assert (SKILL_DIR / "scripts/fable-discipline-lint.py").is_file()
    assert (SKILL_DIR / "scripts/test_fable_discipline_lint.py").is_file()
    assert (SKILL_DIR / "references/checklist.md").is_file()


def test_no_second_copy_of_the_lint_script():
    copies = [
        p for p in REPO.glob("plugins/*/skills/*/scripts/fable-discipline-lint.py")
    ]
    assert copies == [SKILL_DIR / "scripts/fable-discipline-lint.py"], (
        f"expected exactly one lint copy under prd-os, found: {copies}"
    )
