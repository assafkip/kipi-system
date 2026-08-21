#!/usr/bin/env python3
"""settings.local.json is not authoritative wiring (ASK-965, finding-13).

Pairs with `plugins/kipi-core/scripts/skill-hook-audit.py`.

WHY THIS TEST EXISTS (the scar it pins):
`skill-hook-audit.py` read `.claude/settings.local.json` as one of the configs
that prove a hook is WIRED. `apply_claude_changes.py` lines 512-532 documents
that same file as untracked, machine-local, and deliberately outside the
auditable sanctioned path -- it is REFUSED there rather than merely unchecked,
because "a change here leaves no reviewable trace".

Those two positions cannot both hold. If a local override counts as wiring, then
one developer's untracked file can make the fleet-wide audit report a skeleton
hook as wired, and the orphan bug the audit exists to catch walks straight past
it. The audit answers a question about the SHIPPED tree, so it may only read
configs that ship.

The negative self-test is the point: `test_local_only_is_wired_before_fix` is
written to describe the OLD behaviour and is expected to fail once the fix
lands. It is kept, inverted, as `test_local_only_is_an_orphan`, so a future
regression that re-adds the local reader turns this file red instead of silent.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_AUDIT = Path(__file__).resolve().parents[3] / "plugins" / "kipi-core" / "scripts" / "skill-hook-audit.py"


def _load_audit():
    """Import the audit module by path (its filename has dashes, so no plain import)."""
    spec = importlib.util.spec_from_file_location("skill_hook_audit", _AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_hook_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fixture_tree(root: Path, *, config_name: str) -> None:
    """A minimal repo whose ONLY reference to the hook lives in `config_name`.

    Built from the audit's own contract rather than invented shape: the skill
    glob it searches (`plugins/*/skills/*/SKILL.md`), a search root it walks for
    the script (`q-system`), and a config file it reads. A fixture I invent
    tests my assumption; this one is derived from the producer.
    """
    skill_dir = root / "plugins" / "demo-plugin" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo skill\n")

    qs = root / "q-system"
    qs.mkdir(parents=True)
    (qs / "demo-lint.py").write_text("#!/usr/bin/env python3\nraise SystemExit(2)\n")

    claude = root / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text(json.dumps({"hooks": {}}))
    (claude / config_name).write_text(json.dumps({
        "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "python3 q-system/demo-lint.py"}]}]}
    }))
    (claude / "skill-hook-manifest.json").write_text(json.dumps({
        "skills": {"demo-skill": {"status": "wired", "hooks": ["demo-lint.py"]}},
        "debt_baseline": [],
    }))


def test_tracked_settings_still_counts_as_wiring(tmp_path):
    """Control. A hook referenced in the TRACKED settings.json is wired.

    Without this the fix could pass by making every 'wired' claim fail, which is
    a check that cannot tell right from broken.
    """
    _fixture_tree(tmp_path, config_name="settings.json")
    # The control writes the reference into settings.json itself, so overwrite
    # the empty one the fixture laid down first.
    assert _load_audit().run_audit(tmp_path) == 0


def test_local_only_is_an_orphan(tmp_path):
    """THE INVARIANT. A hook referenced ONLY in settings.local.json is an ORPHAN.

    settings.local.json is untracked and machine-local, so it proves nothing
    about the shipped tree. Before the fix this returned 0 (reported wired) and
    that is precisely the false green this test exists to make impossible.
    """
    _fixture_tree(tmp_path, config_name="settings.local.json")
    assert _load_audit().run_audit(tmp_path) == 1


def test_local_settings_is_not_in_the_reader(tmp_path):
    """Structural twin of the behavioural test above.

    The behavioural test can be satisfied by a special case somewhere downstream;
    this one pins the actual reader, so re-adding the file to `wired_config_files`
    is caught even if some later filter happens to mask its effect.
    """
    audit = _load_audit()
    _fixture_tree(tmp_path, config_name="settings.local.json")
    names = {p.name for p in audit.wired_config_files(tmp_path)}
    assert "settings.local.json" not in names
    assert "settings.json" in names
