from __future__ import annotations

import pytest

from kipi_mcp.linter import Linter


@pytest.fixture
def linter():
    return Linter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_section(sid, title, items=None):
    return {"id": sid, "title": title, "items": items or []}


def _make_item(iid, title, energy="Quick Win", copy_text=None, needs_eyes=False, platform=""):
    item = {"id": iid, "title": title, "energy": energy, "needsEyes": needs_eyes, "platform": platform}
    if copy_text is not None:
        item["copyBlocks"] = [{"text": copy_text}]
    else:
        item["copyBlocks"] = []
    return item


# ===========================================================================
# voice_lint
# ===========================================================================

class TestVoiceLintClean:
    def test_clean_short_text_passes(self, linter):
        result = linter.voice_lint("We shipped a new feature. Users can now export reports.")
        assert result["pass"] is True
        assert result["violation_count"] == 0

    def test_empty_string_passes(self, linter):
        result = linter.voice_lint("")
        assert result["pass"] is True
        assert result["word_count"] == 0

    def test_returns_expected_keys(self, linter):
        result = linter.voice_lint("Short clean text.")
        assert set(result.keys()) == {
            "pass", "word_count", "sentence_count", "avg_sentence_length",
            "hedging_density", "violation_count", "violations",
        }


class TestVoiceLintBannedWords:
    @pytest.mark.parametrize("word", [
        "delve", "comprehensive", "robust", "synergy", "leverage",
        "utilize", "meticulously", "seamlessly",
    ])
    def test_banned_word_detected(self, linter, word):
        result = linter.voice_lint(f"We {word} the platform to get results.")
        assert result["pass"] is False
        types = [v["type"] for v in result["violations"]]
        assert "banned_word" in types

    def test_banned_phrase_game_changer(self, linter):
        result = linter.voice_lint("This is a real game-changer for teams.")
        assert result["pass"] is False
        assert any(v["type"] == "banned_phrase" for v in result["violations"])

    def test_emdash_flagged(self, linter):
        result = linter.voice_lint("Important point \u2014 very important.")
        assert result["pass"] is False
        assert any(v["type"] == "emdash" for v in result["violations"])


class TestVoiceLintSentenceLength:
    def test_long_avg_sentence_length_flagged(self, linter):
        long_sent = " ".join(["word"] * 25)
        result = linter.voice_lint(f"{long_sent}. {long_sent}.")
        assert result["pass"] is False
        assert any(v["type"] == "sentence_length" for v in result["violations"])

    def test_avg_sentence_length_at_limit_passes(self, linter):
        sent = " ".join(["word"] * 20)
        result = linter.voice_lint(f"{sent}.")
        sentence_violations = [v for v in result["violations"] if v["type"] == "sentence_length"]
        assert len(sentence_violations) == 0


class TestVoiceLintParagraphUniformity:
    def test_uniform_paragraphs_flagged(self, linter):
        para = "This is one sentence.\n\n"
        text = para * 4
        result = linter.voice_lint(text)
        assert any(v["type"] == "paragraph_uniformity" for v in result["violations"])

    def test_non_uniform_paragraphs_pass(self, linter):
        text = "One sentence.\n\nTwo sentences here. Second one.\n\nThree here. Two here. Done."
        result = linter.voice_lint(text)
        assert not any(v["type"] == "paragraph_uniformity" for v in result["violations"])


class TestVoiceLintFillerOpeners:
    @pytest.mark.parametrize("opener", [
        "I'm excited to announce our new product.",
        "Thrilled to share this update with you.",
        "Proud to say we hit our target.",
        "Humbled by the response from users.",
        "In today's world, everything is changing.",
    ])
    def test_filler_opener_detected(self, linter, opener):
        result = linter.voice_lint(opener)
        assert any(v["type"] == "filler_opener" for v in result["violations"])


class TestVoiceLintStructuralOpeners:
    @pytest.mark.parametrize("opener", [
        "Furthermore, we decided to act.",
        "Moreover, the data supports this.",
        "Additionally, the team agreed.",
    ])
    def test_structural_opener_detected(self, linter, opener):
        result = linter.voice_lint(opener)
        assert any(v["type"] == "structural_opener" for v in result["violations"])


# ===========================================================================
# validate_schedule
# ===========================================================================

class TestValidateScheduleOrdering:
    def test_pipeline_before_leads_passes(self, linter):
        sections = [
            _make_section("pipeline-followups", "Follow-ups", [
                _make_item("f1", "Call Alice", copy_text="Hey Alice"),
                _make_item("f2", "Call Bob", copy_text="Hey Bob"),
                _make_item("f3", "Call Carol", copy_text="Hey Carol"),
            ]),
            _make_section("new-leads", "New Leads"),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "Quick task")]),
        ]
        result = linter.validate_schedule(sections)
        assert "pipeline-followups section must come before new-leads section" not in result["errors"]

    def test_leads_before_pipeline_errors(self, linter):
        sections = [
            _make_section("new-leads", "New Leads"),
            _make_section("pipeline-followups", "Follow-ups", [
                _make_item("f1", "A", copy_text="text"),
                _make_item("f2", "B", copy_text="text"),
                _make_item("f3", "C", copy_text="text"),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections)
        assert any("pipeline-followups" in e for e in result["errors"])


class TestValidateSchedulePipelineMinimum:
    def test_fewer_than_3_followups_errors(self, linter):
        sections = [
            _make_section("pipeline-followups", "Follow-ups", [
                _make_item("f1", "A", copy_text="text"),
                _make_item("f2", "B", copy_text="text"),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections)
        assert any("at least 3 items" in e for e in result["errors"])

    def test_item_without_copy_or_needs_eyes_errors(self, linter):
        sections = [
            _make_section("pipeline-followups", "Follow-ups", [
                _make_item("f1", "A", copy_text="text"),
                _make_item("f2", "B", copy_text="text"),
                _make_item("f3", "C"),  # no copy, no needsEyes
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections)
        assert any("f3" in e for e in result["errors"])

    def test_needs_eyes_true_satisfies_requirement(self, linter):
        sections = [
            _make_section("pipeline-followups", "Follow-ups", [
                _make_item("f1", "A", copy_text="text"),
                _make_item("f2", "B", copy_text="text"),
                _make_item("f3", "C", needs_eyes=True),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections)
        assert not any("f3" in e for e in result["errors"])


class TestValidateScheduleDaySpecific:
    @pytest.mark.parametrize("day", ["mon", "wed", "fri"])
    def test_mwf_missing_signal_errors(self, linter, day):
        sections = [
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "random task")]),
        ]
        result = linter.validate_schedule(sections, day=day)
        assert any("signal" in e or "x-post" in e for e in result["errors"])

    @pytest.mark.parametrize("day", ["mon", "wed", "fri"])
    def test_mwf_with_signal_passes(self, linter, day):
        sections = [
            _make_section("quick-wins", "Quick Wins", [
                _make_item("s1", "morning signal post"),
            ]),
        ]
        result = linter.validate_schedule(sections, day=day)
        assert not any("signal" in e or "x-post" in e for e in result["errors"])

    @pytest.mark.parametrize("day", ["tue", "thu"])
    def test_tt_missing_linkedin_post_errors(self, linter, day):
        sections = [
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "random task")]),
        ]
        result = linter.validate_schedule(sections, day=day)
        assert any("thought leadership" in e or "linkedin post" in e for e in result["errors"])

    @pytest.mark.parametrize("day", ["tue", "thu"])
    def test_tt_with_linkedin_post_passes(self, linter, day):
        sections = [
            _make_section("content", "Content", [
                _make_item("l1", "LinkedIn Post: Founder Story", platform="linkedin"),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections, day=day)
        assert not any("thought leadership" in e or "linkedin post" in e for e in result["errors"])

    def test_mon_missing_medium_warns(self, linter):
        sections = [
            _make_section("quick-wins", "Quick Wins", [
                _make_item("s1", "x-post signal", platform="twitter"),
            ]),
        ]
        result = linter.validate_schedule(sections, day="mon")
        assert any("medium" in w for w in result["warnings"])

    def test_mon_with_medium_no_warn(self, linter):
        sections = [
            _make_section("content", "Content", [
                _make_item("m1", "medium article draft"),
                _make_item("s1", "signal post x-post"),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections, day="mon")
        assert not any("medium" in w for w in result["warnings"])

    def test_wed_missing_kipi_warns(self, linter):
        sections = [
            _make_section("quick-wins", "Quick Wins", [
                _make_item("s1", "x-post signal"),
            ]),
        ]
        result = linter.validate_schedule(sections, day="wed")
        assert any("kipi" in w for w in result["warnings"])

    def test_wed_with_kipi_no_warn(self, linter):
        sections = [
            _make_section("content", "Content", [
                _make_item("k1", "kipi feature update x-post"),
            ]),
            _make_section("quick-wins", "Quick Wins", [_make_item("q1", "task")]),
        ]
        result = linter.validate_schedule(sections, day="wed")
        assert not any("kipi" in w for w in result["warnings"])


class TestValidateScheduleQuickWins:
    def test_missing_quick_wins_warns(self, linter):
        sections = [_make_section("other", "Other", [_make_item("x1", "task", energy="Deep Focus")])]
        result = linter.validate_schedule(sections)
        assert any("quick wins" in w.lower() for w in result["warnings"])


class TestValidateScheduleEnergyTags:
    def test_missing_energy_warns(self, linter):
        item = {"id": "x1", "title": "task", "copyBlocks": [], "needsEyes": False}
        sections = [
            _make_section("quick-wins", "Quick Wins", [item]),
        ]
        result = linter.validate_schedule(sections)
        assert any("energy" in w for w in result["warnings"])

    def test_present_energy_no_warn(self, linter):
        sections = [
            _make_section("quick-wins", "Quick Wins", [
                _make_item("q1", "task", energy="Quick Win"),
            ]),
        ]
        result = linter.validate_schedule(sections)
        assert not any("energy" in w for w in result["warnings"])


# ===========================================================================
# validate_ad_copy
# ===========================================================================

class TestValidateAdCopyGoogle:
    def test_clean_google_passes(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short headline"] * 5,
            descriptions=["A description under ninety chars."] * 2,
        )
        assert result["pass"] is True
        assert result["platform"] == "google"

    def test_google_headline_over_30_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["This headline is way too long for Google ads"],
            descriptions=["Desc."] * 2,
        )
        assert result["pass"] is False
        assert any(v["field"] == "headlines" for v in result["violations"])

    def test_google_description_over_90_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short"] * 3,
            descriptions=["x" * 91] * 2,
        )
        assert result["pass"] is False
        assert any(v["field"] == "descriptions" for v in result["violations"])

    def test_google_headline_count_too_few_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short"] * 2,
            descriptions=["Desc."] * 2,
        )
        assert result["pass"] is False

    def test_google_headline_count_too_many_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short"] * 16,
            descriptions=["Desc."] * 2,
        )
        assert result["pass"] is False

    def test_google_description_count_too_few_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short"] * 3,
            descriptions=["Desc."],
        )
        assert result["pass"] is False

    def test_google_description_count_too_many_fails(self, linter):
        result = linter.validate_ad_copy(
            "google",
            headlines=["Short"] * 3,
            descriptions=["Desc."] * 5,
        )
        assert result["pass"] is False


class TestValidateAdCopyMeta:
    def test_meta_headline_over_255_fails(self, linter):
        result = linter.validate_ad_copy(
            "meta",
            headlines=["x" * 256],
            descriptions=["Short desc."],
        )
        assert result["pass"] is False
        assert any(v["field"] == "headlines" for v in result["violations"])

    def test_meta_headline_over_recommended_warns(self, linter):
        result = linter.validate_ad_copy(
            "meta",
            headlines=["x" * 41],
            descriptions=["Short desc."],
        )
        assert result["pass"] is True
        assert any(w["field"] == "headlines" for w in result["warnings"])

    def test_meta_clean_passes(self, linter):
        result = linter.validate_ad_copy(
            "meta",
            headlines=["Short headline"],
            descriptions=["Short desc."],
        )
        assert result["pass"] is True
        assert result["violations"] == []


class TestValidateAdCopyLinkedin:
    def test_linkedin_headline_over_200_fails(self, linter):
        result = linter.validate_ad_copy(
            "linkedin",
            headlines=["x" * 201],
            descriptions=["Short."],
        )
        assert result["pass"] is False

    def test_linkedin_description_over_recommended_warns(self, linter):
        result = linter.validate_ad_copy(
            "linkedin",
            headlines=["Short"],
            descriptions=["x" * 101],
        )
        assert any(w["field"] == "descriptions" for w in result["warnings"])


class TestValidateAdCopyTwitter:
    def test_twitter_headline_over_70_fails(self, linter):
        result = linter.validate_ad_copy(
            "twitter",
            headlines=["x" * 71],
            descriptions=["Short"],
        )
        assert result["pass"] is False

    def test_twitter_clean_passes(self, linter):
        result = linter.validate_ad_copy(
            "twitter",
            headlines=["Short tweet headline"],
            descriptions=["Short card description."],
        )
        assert result["pass"] is True


class TestValidateAdCopyTiktok:
    def test_tiktok_description_over_100_fails(self, linter):
        result = linter.validate_ad_copy(
            "tiktok",
            headlines=["Short"],
            descriptions=["x" * 101],
        )
        assert result["pass"] is False

    def test_tiktok_description_over_recommended_warns(self, linter):
        result = linter.validate_ad_copy(
            "tiktok",
            headlines=["Short"],
            descriptions=["x" * 81],
        )
        assert any(w["field"] == "descriptions" for w in result["warnings"])

    def test_tiktok_headline_over_40_fails(self, linter):
        result = linter.validate_ad_copy(
            "tiktok",
            headlines=["x" * 41],
            descriptions=["Short"],
        )
        assert result["pass"] is False


# ===========================================================================
# seo_check
# ===========================================================================

class TestSeoCheckTitle:
    def test_empty_title_errors(self, linter):
        result = linter.seo_check(title="", meta="x" * 155)
        assert result["pass"] is False
        assert any("title" in e for e in result["errors"])

    def test_title_too_short_warns(self, linter):
        result = linter.seo_check(title="Too short", meta="x" * 155)
        assert any("title length" in w and "below" in w for w in result["warnings"])

    def test_title_too_long_warns(self, linter):
        result = linter.seo_check(title="x" * 61, meta="x" * 155)
        assert any("title length" in w and "exceeds" in w for w in result["warnings"])

    def test_title_ideal_no_warn(self, linter):
        result = linter.seo_check(title="x" * 55, meta="x" * 155)
        assert not any("title" in w for w in result["warnings"])


class TestSeoCheckMeta:
    def test_empty_meta_errors(self, linter):
        result = linter.seo_check(title="x" * 55, meta="")
        assert result["pass"] is False
        assert any("meta" in e for e in result["errors"])

    def test_meta_too_short_warns(self, linter):
        result = linter.seo_check(title="x" * 55, meta="Too short")
        assert any("meta description length" in w and "below" in w for w in result["warnings"])

    def test_meta_too_long_warns(self, linter):
        result = linter.seo_check(title="x" * 55, meta="x" * 161)
        assert any("meta description length" in w and "exceeds" in w for w in result["warnings"])


class TestSeoCheckHeadings:
    def test_no_h1_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            headings=[{"level": 2, "text": "Section"}, {"level": 3, "text": "Sub"}],
        )
        assert any("H1" in e for e in result["errors"])

    def test_multiple_h1_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            headings=[{"level": 1, "text": "Title"}, {"level": 1, "text": "Also title"}],
        )
        assert any("multiple H1" in e for e in result["errors"])

    def test_heading_level_skip_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            headings=[{"level": 1, "text": "Title"}, {"level": 3, "text": "Skipped H2"}],
        )
        assert any("skip" in e for e in result["errors"])

    def test_valid_heading_hierarchy_passes(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            headings=[
                {"level": 1, "text": "Title"},
                {"level": 2, "text": "Section"},
                {"level": 3, "text": "Sub"},
            ],
        )
        assert result["pass"] is True
        assert result["errors"] == []

    def test_h1_h2_h4_skip_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            headings=[
                {"level": 1, "text": "Title"},
                {"level": 2, "text": "Section"},
                {"level": 4, "text": "Deep skip"},
            ],
        )
        assert any("H2 to H4" in e or "H3" in e for e in result["errors"])


class TestSeoCheckCwv:
    def test_bad_lcp_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            cwv={"lcp": 3.0, "inp": 100, "cls": 0.05},
        )
        assert any("LCP" in e for e in result["errors"])

    def test_bad_inp_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            cwv={"lcp": 1.5, "inp": 250, "cls": 0.05},
        )
        assert any("INP" in e for e in result["errors"])

    def test_bad_cls_errors(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            cwv={"lcp": 1.5, "inp": 100, "cls": 0.15},
        )
        assert any("CLS" in e for e in result["errors"])

    def test_good_cwv_passes(self, linter):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            cwv={"lcp": 2.0, "inp": 150, "cls": 0.05},
        )
        assert result["pass"] is True

    @pytest.mark.parametrize("lcp,inp,cls", [
        (2.5, 100, 0.05),
        (1.5, 200, 0.05),
        (1.5, 100, 0.1),
    ])
    def test_cwv_at_boundary_fails(self, linter, lcp, inp, cls):
        result = linter.seo_check(
            title="x" * 55, meta="x" * 155,
            cwv={"lcp": lcp, "inp": inp, "cls": cls},
        )
        assert result["pass"] is False


class TestSeoCheckReturnShape:
    def test_return_shape(self, linter):
        result = linter.seo_check(title="x" * 55, meta="x" * 155)
        assert set(result.keys()) == {"pass", "errors", "warnings", "title_length", "meta_length"}
        assert result["title_length"] == 55
        assert result["meta_length"] == 155


# ===========================================================================
# validate_cold_email
# ===========================================================================

class TestValidateColdEmailClean:
    def test_clean_email_passes(self, linter):
        result = linter.validate_cold_email(
            subject="Quick question",
            body="Saw your post on onboarding friction. We cut drop-off by half for teams like yours. Worth a 20-min call?",
        )
        assert result["pass"] is True
        assert result["errors"] == []

    def test_return_shape(self, linter):
        result = linter.validate_cold_email(subject="Test subject", body="Short clean body text here.")
        assert set(result.keys()) == {
            "pass", "subject_word_count", "body_word_count",
            "avg_sentence_length", "errors", "warnings",
        }


class TestValidateColdEmailSubject:
    def test_subject_word_count_outside_range_warns(self, linter):
        result = linter.validate_cold_email(
            subject="This subject has way too many words for an effective cold email subject line",
            body="Clean body text here to avoid other issues.",
        )
        assert any("subject word count" in w for w in result["warnings"])

    def test_subject_single_word_warns(self, linter):
        result = linter.validate_cold_email(
            subject="Hello",
            body="Clean body text here.",
        )
        assert any("subject word count" in w for w in result["warnings"])

    @pytest.mark.parametrize("subject,expected_warn", [
        ("Boost your ROI today", "salesy"),
        ("ASAP urgent response needed", "urgency"),
        ("Free guarantee act now!!", "spam"),
    ])
    def test_subject_flags(self, linter, subject, expected_warn):
        result = linter.validate_cold_email(
            subject=subject,
            body="Clean body text here that is long enough.",
        )
        assert len(result["warnings"]) > 0

    def test_subject_excessive_punctuation_warns(self, linter):
        result = linter.validate_cold_email(
            subject="Quick question??",
            body="Clean body text here.",
        )
        assert any("punctuation" in w for w in result["warnings"])

    def test_subject_with_percentage_warns(self, linter):
        result = linter.validate_cold_email(
            subject="Cut costs 30%",
            body="Clean body text here.",
        )
        assert any("numbers" in w for w in result["warnings"])


class TestValidateColdEmailBody:
    def test_body_over_150_words_errors(self, linter):
        long_body = " ".join(["word"] * 151)
        result = linter.validate_cold_email(subject="Quick ask", body=long_body)
        assert result["pass"] is False
        assert any("150 word limit" in e for e in result["errors"])

    def test_body_under_25_words_warns(self, linter):
        result = linter.validate_cold_email(subject="Quick ask", body="Too short.")
        assert any("25-75" in w for w in result["warnings"])

    def test_body_over_75_words_warns(self, linter):
        body = " ".join(["word"] * 80)
        result = linter.validate_cold_email(subject="Quick ask", body=body)
        assert any("25-75" in w for w in result["warnings"])

    def test_body_ai_pattern_warns(self, linter):
        result = linter.validate_cold_email(
            subject="Quick ask",
            body="I hope this email finds you well. We have a great product.",
        )
        assert any("AI pattern" in w for w in result["warnings"])

    def test_body_multiple_questions_warns(self, linter):
        result = linter.validate_cold_email(
            subject="Quick ask",
            body="Can you review this? Does it work for you? Would you like a demo?",
        )
        assert any("question marks" in w for w in result["warnings"])


# ===========================================================================
# copy_edit_lint
# ===========================================================================

class TestCopyEditLintClean:
    def test_clean_text_passes(self, linter):
        result = linter.copy_edit_lint("We help teams ship faster.")
        assert result["pass"] is True
        assert result["total_issues"] == 0

    def test_empty_string_passes(self, linter):
        result = linter.copy_edit_lint("")
        assert result["pass"] is True
        assert result["word_count"] == 0

    def test_return_shape(self, linter):
        result = linter.copy_edit_lint("Clean text.")
        assert set(result.keys()) == {
            "pass", "word_count", "replacements", "filler_words",
            "passive_voice", "total_issues",
        }


class TestCopyEditLintReplacements:
    @pytest.mark.parametrize("word,plain", [
        ("utilize", "use"),
        ("leverage", "use"),
        ("facilitate", "help"),
        ("commence", "start"),
        ("approximately", "about"),
        ("subsequently", "later"),
        ("furthermore", "also"),
    ])
    def test_replacement_detected(self, linter, word, plain):
        result = linter.copy_edit_lint(f"We {word} the process.")
        assert result["pass"] is False
        assert any(r["suggested"] == plain for r in result["replacements"])

    def test_multi_word_phrase_replacement(self, linter):
        result = linter.copy_edit_lint("We do this due to the fact that it works.")
        assert any(r["suggested"] == "because" for r in result["replacements"])

    def test_in_order_to_replacement(self, linter):
        result = linter.copy_edit_lint("In order to succeed, we must act.")
        assert any(r["suggested"] == "to" for r in result["replacements"])


class TestCopyEditLintFillerWords:
    @pytest.mark.parametrize("word", ["basically", "actually", "very", "really", "just", "quite"])
    def test_filler_word_detected(self, linter, word):
        result = linter.copy_edit_lint(f"This is {word} important.")
        assert any(fw["word"] == word for fw in result["filler_words"])

    def test_filler_word_count_accurate(self, linter):
        result = linter.copy_edit_lint("This is very important. Very clear.")
        very = next((fw for fw in result["filler_words"] if fw["word"] == "very"), None)
        assert very is not None
        assert very["count"] == 2


class TestCopyEditLintPassiveVoice:
    def test_passive_voice_detected(self, linter):
        result = linter.copy_edit_lint("The report was reviewed by the team.")
        assert len(result["passive_voice"]) > 0
        assert result["total_issues"] > 0

    def test_active_voice_not_flagged(self, linter):
        result = linter.copy_edit_lint("The team reviewed the report.")
        assert result["passive_voice"] == []

    def test_passive_voice_context_present(self, linter):
        result = linter.copy_edit_lint("The report was reviewed by the team.")
        assert "context" in result["passive_voice"][0]


class TestCopyEditLintTotalIssues:
    def test_total_issues_counts_all_categories(self, linter):
        text = "The report was written by the team. We basically utilize this."
        result = linter.copy_edit_lint(text)
        expected = len(result["replacements"]) + len(result["filler_words"]) + len(result["passive_voice"])
        assert result["total_issues"] == expected


# ===========================================================================
# linkedin_gate
# ===========================================================================

_CLEAN_DRAFT = (
    "Four companies. Same broken loop.\n\n"
    "I watched four trust teams fight the same problem.\n\n"
    "None of it compounded. The loop breaks because tagging is manual.\n\n"
    "If you run trust ops and feel this, how do you route the signal today?"
)


class TestLinkedInGateClean:
    def test_clean_draft_no_day_passes(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT)
        assert r["pass"] is True
        assert r["violations"] == []
        assert r["hashtag_count"] == 0
        assert r["body_links"] == []

    def test_clean_draft_allowed_day_passes(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT, day_of_week="tue")
        assert r["pass"] is True
        assert r["day_ok"] is True


class TestLinkedInGateHashtags:
    def test_single_hashtag_passes(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT + " #trust")
        assert r["hashtag_count"] == 1
        assert not any(v["type"] == "hashtag_count" for v in r["violations"])

    def test_two_hashtags_blocks(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT + " #trust #safety")
        assert r["pass"] is False
        assert r["hashtag_count"] == 2
        assert any(v["type"] == "hashtag_count" for v in r["violations"])


class TestLinkedInGateBodyLinks:
    def test_body_link_blocks_post(self, linter):
        draft = _CLEAN_DRAFT + "\n\nSee https://example.com/post for more."
        r = linter.linkedin_gate(draft)
        assert r["pass"] is False
        assert len(r["body_links"]) == 1
        assert any(v["type"] == "body_link" for v in r["violations"])

    @pytest.mark.parametrize("kind", ["comment", "dm", "about"])
    def test_body_link_allowed_non_post(self, linter, kind):
        draft = _CLEAN_DRAFT + "\n\nSee https://example.com/post for more."
        r = linter.linkedin_gate(draft, kind=kind)
        assert not any(v["type"] == "body_link" for v in r["violations"])
        assert len(r["body_links"]) == 1


class TestLinkedInGateDayOfWeek:
    @pytest.mark.parametrize("day", ["tue", "tuesday", "wed", "wednesday", "thu", "thursday"])
    def test_allowed_days_pass(self, linter, day):
        r = linter.linkedin_gate(_CLEAN_DRAFT, day_of_week=day)
        assert r["day_ok"] is True
        assert not any(v["type"] == "day_of_week" for v in r["violations"])

    @pytest.mark.parametrize("day", ["mon", "fri", "sat", "sun"])
    def test_disallowed_days_block_post(self, linter, day):
        r = linter.linkedin_gate(_CLEAN_DRAFT, day_of_week=day)
        assert r["pass"] is False
        assert r["day_ok"] is False

    def test_override_day_bypasses_gate(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT, day_of_week="mon", override_day=True)
        assert r["pass"] is True
        assert r["day_ok"] is True

    @pytest.mark.parametrize("kind", ["comment", "dm", "about"])
    def test_day_gate_skipped_for_non_posts(self, linter, kind):
        r = linter.linkedin_gate(_CLEAN_DRAFT, kind=kind, day_of_week="mon")
        assert r["pass"] is True
        assert not any(v["type"] == "day_of_week" for v in r["violations"])

    def test_empty_day_skips_gate(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT)
        assert r["day_ok"] is True


class TestLinkedInGateKind:
    def test_rejects_unknown_kind(self, linter):
        with pytest.raises(ValueError):
            linter.linkedin_gate(_CLEAN_DRAFT, kind="story")

    def test_hashtag_rule_universal(self, linter):
        r = linter.linkedin_gate(_CLEAN_DRAFT + " #a #b", kind="comment")
        assert r["pass"] is False
        assert any(v["type"] == "hashtag_count" for v in r["violations"])

    def test_voice_rule_universal(self, linter):
        r = linter.linkedin_gate(
            "We leverage the platform. " + _CLEAN_DRAFT, kind="dm",
        )
        assert r["pass"] is False
        assert r["lint_voice"]["pass"] is False


class TestLinkedInGateWrapsLinters:
    def test_banned_word_in_draft_blocks(self, linter):
        draft = "We leverage the platform. " + _CLEAN_DRAFT
        r = linter.linkedin_gate(draft)
        assert r["pass"] is False
        assert r["lint_voice"]["pass"] is False

    def test_passive_voice_in_draft_blocks(self, linter):
        draft = "The report was reviewed by the team. " + _CLEAN_DRAFT
        r = linter.linkedin_gate(draft)
        assert r["pass"] is False
        assert r["lint_copy"]["pass"] is False
