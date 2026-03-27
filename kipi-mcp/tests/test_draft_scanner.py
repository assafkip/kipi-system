from __future__ import annotations

import pytest

from kipi_mcp.draft_scanner import DraftScanner


@pytest.fixture
def scanner():
    return DraftScanner()


def _wrap(text, field="text"):
    return {field: text}


class TestCleanText:
    def test_clean_text_passes(self, scanner):
        data = _wrap("This is a normal sentence about work.")
        result = scanner.scan(data)
        assert result["pass"] is True
        assert result["violation_count"] == 0
        assert result["fields_scanned"] == 1

    def test_empty_data_passes(self, scanner):
        result = scanner.scan({})
        assert result["pass"] is True
        assert result["fields_scanned"] == 0
        assert result["words_scanned"] == 0


class TestBannedWords:
    def test_delve_detected(self, scanner):
        data = _wrap("Let me delve into this topic.")
        result = scanner.scan(data)
        assert result["pass"] is False
        assert result["violation_count"] >= 1
        violations = [v for v in result["violations"] if v["word"].lower() == "delve"]
        assert len(violations) == 1
        assert violations[0]["type"] == "banned_word"

    def test_leverage_detected(self, scanner):
        data = _wrap("We leverage AI to do things.")
        result = scanner.scan(data)
        assert result["pass"] is False
        assert any(v["word"].lower() == "leverage" for v in result["violations"])

    def test_adverb_detected(self, scanner):
        data = _wrap("We meticulously check everything.")
        result = scanner.scan(data)
        assert result["pass"] is False
        assert any(v["word"].lower() == "meticulously" for v in result["violations"])


class TestBannedPhrases:
    def test_lets_dive_in(self, scanner):
        data = _wrap("Let's dive in to the details.")
        result = scanner.scan(data)
        assert result["pass"] is False
        phrases = [v for v in result["violations"] if v["type"] == "banned_phrase"]
        assert len(phrases) >= 1

    def test_game_changer(self, scanner):
        data = _wrap("This is a real game-changer for the industry.")
        result = scanner.scan(data)
        assert result["pass"] is False
        assert any(v["type"] == "banned_phrase" for v in result["violations"])


class TestEmdash:
    def test_emdash_detected(self, scanner):
        data = _wrap("This is important \u2014 very important.")
        result = scanner.scan(data)
        assert result["pass"] is False
        emdash_violations = [v for v in result["violations"] if v["type"] == "emdash"]
        assert len(emdash_violations) == 1


class TestHedgingDensity:
    def test_high_hedging_density_fails(self, scanner):
        words = "might could perhaps generally somewhat arguably " * 20
        padding = "word " * 200
        data = _wrap(words + padding)
        result = scanner.scan(data)
        assert result["hedging_density"] > 1.0
        hedging = [v for v in result["violations"] if v["type"] == "hedging_density"]
        assert len(hedging) == 1

    def test_low_hedging_passes(self, scanner):
        data = _wrap("This might work. " + "Normal sentence here now. " * 500)
        result = scanner.scan(data)
        hedging = [v for v in result["violations"] if v["type"] == "hedging_density"]
        assert len(hedging) == 0


class TestNestedStructure:
    def test_nested_json_fields_scanned(self, scanner):
        data = {
            "items": [
                {"copy": "We leverage AI.", "title": "ignored title"},
                {"body": "This is clean."},
                {"nested": {"text": "Also clean content."}},
            ]
        }
        result = scanner.scan(data)
        assert result["fields_scanned"] == 3
        assert result["violation_count"] >= 1

    def test_non_copy_fields_ignored(self, scanner):
        data = {"title": "We delve into innovation", "name": "leverage corp"}
        result = scanner.scan(data)
        assert result["pass"] is True
        assert result["fields_scanned"] == 0


class TestResultShape:
    def test_result_has_expected_keys(self, scanner):
        result = scanner.scan(_wrap("clean text"))
        expected_keys = {"pass", "file", "fields_scanned", "words_scanned", "violation_count", "hedging_density", "violations"}
        assert set(result.keys()) == expected_keys

    def test_violation_has_expected_keys(self, scanner):
        result = scanner.scan(_wrap("delve into this"))
        assert len(result["violations"]) > 0
        v = result["violations"][0]
        assert set(v.keys()) == {"type", "word", "field", "context"}
