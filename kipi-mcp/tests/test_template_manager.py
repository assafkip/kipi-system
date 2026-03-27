import json

import pytest

from kipi_mcp.template_manager import TemplateManager


@pytest.fixture
def manager(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    tmpl = templates_dir / "deck"
    tmpl.mkdir()
    (tmpl / "README.md").write_text("# {{OUTPUT_NAME}}\nDate: {{DATE}}")
    (tmpl / "slides.md").write_text("Slide content for {{OUTPUT_NAME}}")
    (tmpl / "data.json").write_text('{"key": "value"}')

    return TemplateManager(templates_dir, output_dir), templates_dir, output_dir


def test_create_copies_template(manager):
    mgr, _, output_dir = manager
    result = mgr.create("deck", "my-deck")
    dest = output_dir / "my-deck"
    assert dest.is_dir()
    assert (dest / "README.md").exists()
    assert (dest / "slides.md").exists()
    assert (dest / "data.json").exists()
    assert result["created"] == str(dest)
    assert "README.md" in result["files"]


def test_create_replaces_placeholders(manager):
    from datetime import date

    mgr, _, output_dir = manager
    mgr.create("deck", "my-deck")
    readme = (output_dir / "my-deck" / "README.md").read_text()
    assert "my-deck" in readme
    assert date.today().isoformat() in readme
    assert "{{OUTPUT_NAME}}" not in readme
    assert "{{DATE}}" not in readme

    slides = (output_dir / "my-deck" / "slides.md").read_text()
    assert "my-deck" in slides
    assert "{{OUTPUT_NAME}}" not in slides


def test_create_skips_non_md(manager):
    mgr, _, output_dir = manager
    mgr.create("deck", "my-deck")
    data = (output_dir / "my-deck" / "data.json").read_text()
    assert data == '{"key": "value"}'


def test_create_template_not_found(manager):
    mgr, _, _ = manager
    with pytest.raises(ValueError, match="Template not found"):
        mgr.create("nonexistent", "out")


def test_create_output_exists(manager):
    mgr, _, output_dir = manager
    (output_dir / "existing").mkdir()
    with pytest.raises(ValueError, match="Output already exists"):
        mgr.create("deck", "existing")


def test_list_templates(manager):
    mgr, templates_dir, _ = manager
    assert mgr.list_templates() == ["deck"]
    (templates_dir / "outreach").mkdir()
    assert mgr.list_templates() == ["deck", "outreach"]


def test_build_schedule(tmp_path):
    template_html = "<html>var data = __SCHEDULE_DATA__;</html>"
    template_file = tmp_path / "template.html"
    template_file.write_text(template_html)

    json_file = tmp_path / "schedule.json"
    data = {"blocks": [{"time": "09:00", "task": "standup"}]}
    json_file.write_text(json.dumps(data))

    mgr = TemplateManager(tmp_path, tmp_path, schedule_template=template_file)
    result = mgr.build_schedule(str(json_file))
    assert "html" in result
    assert '"blocks"' in result["html"]
    assert "__SCHEDULE_DATA__" not in result["html"]

    out_file = tmp_path / "output.html"
    result2 = mgr.build_schedule(str(json_file), str(out_file))
    assert result2 == {"built": str(out_file)}
    assert out_file.read_text() == result["html"]


def test_build_schedule_with_verification(tmp_path):
    template_file = tmp_path / "template.html"
    template_file.write_text("<html>__SCHEDULE_DATA__</html>")
    json_file = tmp_path / "schedule.json"
    json_file.write_text('{"blocks": []}')

    def bad_verify(data):
        raise ValueError("Missing required fields")

    mgr = TemplateManager(
        tmp_path, tmp_path, schedule_template=template_file, verify_schedule_fn=bad_verify
    )
    result = mgr.build_schedule(str(json_file))
    assert result["blocked"] is True
    assert "Missing required fields" in result["error"]


def test_build_schedule_no_template(tmp_path):
    mgr = TemplateManager(tmp_path, tmp_path)
    with pytest.raises(ValueError, match="No schedule template configured"):
        mgr.build_schedule("whatever.json")
