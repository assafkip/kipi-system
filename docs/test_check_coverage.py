#!/usr/bin/env python3
"""Negative self-tests for docs/check_coverage.py: the gate must go RED for the reason
we care about, in each direction, before its green means anything.

Every case works on a COPY of the docs tree under tmp_path, never the live docs
(fable-discipline: never a live data path). Direction one: a surface named in the code but
removed from the docs copy. Direction two: a page missing a diagram, a caption, or the
reader section. Direction three: a reference catalog that drifted. Plus the floor: an
enumerator class that comes back empty raises instead of passing.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inventory  # noqa: E402

spec = importlib.util.spec_from_file_location("check_coverage", HERE / "check_coverage.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def docs_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "docs"
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def test_enumerator_has_every_class_and_a_floor():
    surfaces = inventory.enumerate_surfaces()
    classes = {s.cls for s in surfaces}
    assert classes == set(inventory.ORDER)
    assert len(surfaces) > 500
    # The floor: a broken enumerator raises, it never returns "nothing to document".
    saved = inventory.MCP_SERVER
    inventory.MCP_SERVER = "plugins/kipi-core/kipi-mcp/src/kipi_mcp/__init__.py"
    try:
        with pytest.raises(RuntimeError, match="floor"):
            inventory.enumerate_surfaces()
    finally:
        inventory.MCP_SERVER = saved


def test_live_docs_pass_and_a_removed_name_goes_red(tmp_path):
    docs = docs_copy(tmp_path)
    assert cc.main(["--docs", str(docs), "--quiet"]) == 0, "live docs must be complete before mutation"
    surfaces = inventory.enumerate_surfaces()
    victim = next(s for s in surfaces if s.cls == "mcp_tool" and s.name == "kipi_voice_lint")
    hit = False
    for p in (docs / "systems").glob("*.md"):
        t = p.read_text()
        if victim.name in t:
            p.write_text(t.replace(victim.name, "REDACTED_TOOL"))
            hit = True
    assert hit
    assert cc.check_surfaces(docs, surfaces) == [f"mcp_tool: {victim.name}  ({victim.path})"]


def test_a_script_added_to_the_code_but_not_the_docs_goes_red(tmp_path):
    docs = docs_copy(tmp_path)
    surfaces = inventory.enumerate_surfaces()
    ghost = inventory.Surface("script", "ghost-not-documented.py", "q-system/.q-system/scripts/ghost-not-documented.py", "")
    missing = cc.check_surfaces(docs, surfaces + [ghost])
    assert missing == ["script: ghost-not-documented.py  (q-system/.q-system/scripts/ghost-not-documented.py)"]


def test_a_suffix_of_a_documented_name_is_not_documented(tmp_path):
    """Codex on PR #306: under a bare substring test `lint.py`, `guard.py` and `notify.py`
    came back documented, riding on `voice-lint.py`, `token-guard.py` and `rca-notify.py`."""
    docs = docs_copy(tmp_path)
    text = cc.systems_text(docs)
    assert "voice-lint.py" in text and "token-guard.py" in text and "rca-notify.py" in text
    ghosts = [inventory.Surface("script", "lint.py", "q-system/.q-system/scripts/lint.py", ""),
              inventory.Surface("script", "guard.py", "q-system/.q-system/scripts/guard.py", ""),
              inventory.Surface("hook", "notify.py", ".claude/settings.json", "")]
    missing = cc.check_surfaces(docs, ghosts)
    assert sorted(missing) == sorted(f"{g.cls}: {g.name}  ({g.path})" for g in ghosts), missing
    # A real name preceded by a path separator or a backtick still counts as documented.
    real = [inventory.Surface("script", "voice-lint.py", "q-system/.q-system/scripts/voice-lint.py", "")]
    assert cc.check_surfaces(docs, real) == []


def test_cli_verb_must_appear_as_a_kipi_command(tmp_path):
    docs = docs_copy(tmp_path)
    surfaces = [inventory.Surface("cli_verb", "zzz-verb", "kipi", "")]
    assert cc.check_surfaces(docs, surfaces), "an undocumented verb is red"
    (docs / "systems" / "zz.md").write_text("Run `kipi zzz-verb` to do the thing.\n")
    assert cc.check_surfaces(docs, surfaces) == []


def test_missing_diagram_caption_and_reader_section_go_red(tmp_path):
    docs = docs_copy(tmp_path)
    assert cc.check_diagrams(docs) == [] and cc.check_concepts(docs) == []
    page = sorted((docs / "systems").glob("*.md"))[0]
    text = page.read_text()
    page.write_text(text.replace("```mermaid", "```text", 1))
    probs = cc.check_diagrams(docs)
    assert any(page.name in p for p in probs), probs
    page.write_text(text)
    # Caption: strip the paragraph after the first diagram.
    i = text.find("```mermaid"); j = text.find("```", i + 10) + 3
    k = text.find("\n\n", j + 1)
    page.write_text(text[:j] + "\n\n## Next\n" + text[k:])
    probs = cc.check_diagrams(docs)
    assert any("caption" in p and page.name in p for p in probs), probs
    page.write_text(text)
    concept = sorted((docs / "concepts").glob("*.md"))[0]
    ct = concept.read_text()
    concept.write_text(ct.replace(cc.READER_SECTION, "## Something else"))
    assert any(concept.name in p for p in cc.check_concepts(docs))


def test_reference_drift_goes_red(tmp_path):
    docs = docs_copy(tmp_path)
    assert cc.check_reference(docs) == []
    ref = docs / "reference" / "mcp-tools.md"
    ref.write_text(ref.read_text().replace("kipi_voice_lint", "kipi_voice_lint_renamed", 1))
    probs = cc.check_reference(docs)
    assert any("mcp-tools.md drifted" in p for p in probs), probs


def test_retired_heading_required(tmp_path):
    docs = docs_copy(tmp_path)
    assert cc.check_retired(docs) == []
    for p in (docs / "systems").glob("*.md"):
        p.write_text(p.read_text().replace("## Retired", "## Old"))
    assert cc.check_retired(docs)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
