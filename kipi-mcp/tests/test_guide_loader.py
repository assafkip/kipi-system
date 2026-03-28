import pytest
from kipi_mcp.guide_loader import GuideLoader


def _create_guide(base, name, methodology="# Guide\nContent here", refs=None):
    guide_dir = base / name
    guide_dir.mkdir(parents=True)
    (guide_dir / "methodology.md").write_text(methodology)
    if refs:
        refs_dir = guide_dir / "references"
        refs_dir.mkdir()
        for ref_name, ref_content in refs.items():
            (refs_dir / f"{ref_name}.md").write_text(ref_content)


def test_list_topics(tmp_path):
    _create_guide(tmp_path, "copywriting")
    _create_guide(tmp_path, "seo-audit")
    loader = GuideLoader(tmp_path)
    assert loader.list_topics() == ["copywriting", "seo-audit"]


def test_list_topics_empty(tmp_path):
    loader = GuideLoader(tmp_path / "nonexistent")
    assert loader.list_topics() == []


def test_load_methodology_only(tmp_path):
    _create_guide(tmp_path, "copywriting", methodology="# Copywriting\nWrite good copy.")
    loader = GuideLoader(tmp_path)
    result = loader.load("copywriting", section="methodology")
    assert result == "# Copywriting\nWrite good copy."


def test_load_full_with_refs(tmp_path):
    _create_guide(tmp_path, "revops", methodology="# RevOps", refs={
        "scoring-models": "# Scoring\nPoints here.",
        "routing-rules": "# Routing\nRules here.",
    })
    loader = GuideLoader(tmp_path)
    result = loader.load("revops", section="full")
    assert "# RevOps" in result
    assert "# Scoring" in result
    assert "# Routing" in result


def test_load_specific_reference(tmp_path):
    _create_guide(tmp_path, "revops", refs={"scoring-models": "# Scoring\nContent."})
    loader = GuideLoader(tmp_path)
    result = loader.load("revops", section="scoring-models")
    assert result == "# Scoring\nContent."


def test_load_nonexistent_topic(tmp_path):
    _create_guide(tmp_path, "copywriting")
    loader = GuideLoader(tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        loader.load("nonexistent")


def test_load_nonexistent_section(tmp_path):
    _create_guide(tmp_path, "copywriting", refs={"frameworks": "stuff"})
    loader = GuideLoader(tmp_path)
    with pytest.raises(FileNotFoundError, match="not found.*Available"):
        loader.load("copywriting", section="nonexistent")


def test_load_full_no_refs(tmp_path):
    _create_guide(tmp_path, "simple", methodology="# Simple guide")
    loader = GuideLoader(tmp_path)
    result = loader.load("simple", section="full")
    assert result == "# Simple guide"
