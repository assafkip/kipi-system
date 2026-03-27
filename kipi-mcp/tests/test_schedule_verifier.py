from __future__ import annotations

import pytest

from kipi_mcp.schedule_verifier import ScheduleVerifier


@pytest.fixture
def verifier():
    return ScheduleVerifier()


def _make_item(item_id, energy="quick-win", copy_text="Follow up msg", needs_eyes=False):
    item = {"id": item_id, "energy": energy}
    if copy_text:
        item["copyBlocks"] = [{"text": copy_text}]
    if needs_eyes:
        item["needsEyes"] = True
    return item


def _make_section(section_id, items=None):
    return {"id": section_id, "items": items or []}


def _pipeline_section(count=3):
    items = [_make_item(f"pf-{i}", copy_text=f"Hey, following up on {i}") for i in range(count)]
    return _make_section("pipeline-followups", items)


def _signals_item():
    item = _make_item("signal-post", energy="deep-focus", copy_text="Signal: market is shifting")
    item["title"] = "Signals Post"
    return item


def _tl_item():
    item = _make_item("tl-post", energy="deep-focus", copy_text="Thought leadership post")
    item["title"] = "Thought Leadership Post"
    item["platform"] = "linkedin"
    return item


def _valid_monday():
    return {
        "date": "2026-03-23",
        "sections": [
            _make_section("quick-wins", [_make_item("qw-1")]),
            _pipeline_section(),
            _make_section("linkedin-engagement", [_make_item("le-1")]),
            _make_section("new-leads", [_make_item("nl-1")]),
            _make_section("posts", [_signals_item()]),
            _make_section("medium-draft", [{**_make_item("med-1", copy_text="Medium draft"), "title": "Medium Article Draft"}]),
        ],
    }


def _valid_tuesday():
    tl = _make_item("tl-linkedin", energy="deep-focus", copy_text="TL post")
    tl["platform"] = "linkedin"
    tl["title"] = "Thought Leadership Post"
    return {
        "date": "2026-03-24",
        "sections": [
            _make_section("quick-wins", [_make_item("qw-1")]),
            _pipeline_section(),
            _make_section("posts", [tl]),
        ],
    }


class TestVerifyValidSchedules:
    def test_valid_monday_passes(self, verifier):
        result = verifier.verify(_valid_monday(), "monday")
        assert result["pass"] is True
        assert result["errors"] == []

    def test_valid_tuesday_passes(self, verifier):
        result = verifier.verify(_valid_tuesday(), "tuesday")
        assert result["pass"] is True
        assert result["errors"] == []


class TestVerifyMissingSections:
    def test_missing_date_raises(self, verifier):
        with pytest.raises(ValueError, match="date"):
            verifier.verify({"sections": []}, "monday")

    def test_missing_sections_raises(self, verifier):
        with pytest.raises(ValueError, match="sections"):
            verifier.verify({"date": "2026-03-23"}, "monday")

    def test_missing_pipeline_followups(self, verifier):
        data = {
            "date": "2026-03-23",
            "sections": [_make_section("quick-wins", [_make_item("qw-1")])],
        }
        result = verifier.verify(data, "monday")
        assert result["pass"] is False
        assert any("pipeline-followups" in e for e in result["errors"])


class TestPipelineFollowups:
    def test_fewer_than_3_items_error(self, verifier):
        data = {
            "date": "2026-03-23",
            "sections": [_pipeline_section(count=2), _make_section("posts", [_signals_item()])],
        }
        result = verifier.verify(data, "monday")
        assert result["pass"] is False
        assert any("2 items" in e for e in result["errors"])

    def test_missing_copy_blocks_error(self, verifier):
        items = [_make_item(f"pf-{i}", copy_text="") for i in range(3)]
        data = {
            "date": "2026-03-23",
            "sections": [_make_section("pipeline-followups", items), _make_section("posts", [_signals_item()])],
        }
        result = verifier.verify(data, "monday")
        assert result["pass"] is False
        assert any("copy" in e.lower() for e in result["errors"])

    def test_needs_eyes_skips_copy_check(self, verifier):
        items = [
            _make_item("pf-0", copy_text="msg"),
            _make_item("pf-1", copy_text="msg"),
            _make_item("pf-2", copy_text="", needs_eyes=True),
        ]
        data = {
            "date": "2026-03-23",
            "sections": [_make_section("pipeline-followups", items), _make_section("posts", [_signals_item()])],
        }
        result = verifier.verify(data, "monday")
        copy_errors = [e for e in result["errors"] if "copy" in e.lower()]
        assert copy_errors == []


class TestDaySpecificContent:
    def test_missing_signals_on_wednesday(self, verifier):
        data = {
            "date": "2026-03-25",
            "sections": [_pipeline_section(), _make_section("posts", [_make_item("generic")])],
        }
        result = verifier.verify(data, "wednesday")
        assert any("signals" in e.lower() for e in result["errors"])

    def test_missing_tl_on_thursday(self, verifier):
        data = {
            "date": "2026-03-26",
            "sections": [_pipeline_section(), _make_section("posts", [_make_item("generic")])],
        }
        result = verifier.verify(data, "thursday")
        assert any("thought leadership" in e.lower() for e in result["errors"])

    def test_monday_missing_medium_warning(self, verifier):
        data = _valid_monday()
        data["sections"] = [s for s in data["sections"] if s["id"] != "medium-draft"]
        result = verifier.verify(data, "monday")
        assert any("medium" in w.lower() for w in result["warnings"])

    def test_wednesday_missing_kipi_warning(self, verifier):
        data = {
            "date": "2026-03-25",
            "sections": [_pipeline_section(), _make_section("posts", [_signals_item()])],
        }
        result = verifier.verify(data, "wednesday")
        assert any("kipi" in w.lower() for w in result["warnings"])


class TestSectionOrdering:
    def test_pipeline_after_new_leads_error(self, verifier):
        data = {
            "date": "2026-03-23",
            "sections": [
                _make_section("new-leads", [_make_item("nl-1")]),
                _pipeline_section(),
                _make_section("posts", [_signals_item()]),
            ],
        }
        result = verifier.verify(data, "monday")
        assert result["pass"] is False
        assert any("ordering" in e.lower() for e in result["errors"])


class TestEnergyTags:
    def test_missing_energy_tag_warning(self, verifier):
        item_no_energy = {"id": "no-energy", "copyBlocks": [{"text": "hi"}]}
        data = {
            "date": "2026-03-23",
            "sections": [_pipeline_section(), _make_section("posts", [item_no_energy, _signals_item()])],
        }
        result = verifier.verify(data, "monday")
        assert any("energy" in w.lower() for w in result["warnings"])


class TestDayDerivation:
    def test_empty_day_derives_from_date(self, verifier):
        data = _valid_monday()
        result = verifier.verify(data, "")
        assert result["pass"] is True

    def test_no_day_arg_derives_from_date(self, verifier):
        data = _valid_monday()
        result = verifier.verify(data)
        assert result["pass"] is True
