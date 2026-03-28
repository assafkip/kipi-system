from __future__ import annotations

import math
import pytest

from kipi_mcp.scorer import Scorer


@pytest.fixture
def scorer():
    return Scorer()


# ---------------------------------------------------------------------------
# score_lead
# ---------------------------------------------------------------------------

class TestScoreLead:
    def test_score_lead_hybrid_model_defaults(self, scorer):
        result = scorer.score_lead({}, [])
        assert result["model"] == "hybrid"
        assert result["mql_threshold"] == 65
        assert result["score"] == 0.0
        assert result["is_mql"] is False

    def test_score_lead_fit_attributes_summed(self, scorer):
        attrs = {
            "company_size": "201-1000",  # 20
            "title": "vp",              # 20
            "role": "decision_maker",   # 20
        }
        result = scorer.score_lead(attrs, [], model="hybrid")
        assert result["fit_score"] == 60.0
        assert result["breakdown"]["fit"]["company_size"] == 20
        assert result["breakdown"]["fit"]["title"] == 20
        assert result["breakdown"]["fit"]["role"] == 20

    def test_score_lead_unknown_attribute_values_ignored(self, scorer):
        attrs = {"company_size": "unknown_size", "industry": "unknown"}
        result = scorer.score_lead(attrs, [], model="hybrid")
        assert result["fit_score"] == 0.0

    @pytest.mark.parametrize("model,fit_w,eng_w,threshold", [
        ("plg", 0.3, 0.7, 60),
        ("enterprise", 0.6, 0.4, 75),
        ("hybrid", 0.5, 0.5, 65),
    ])
    def test_score_lead_model_weights_and_thresholds(self, scorer, model, fit_w, eng_w, threshold):
        attrs = {"company_size": "201-1000"}   # 20 fit
        signals = [{"type": "demo_request", "age_days": 0}]  # 30 engagement
        result = scorer.score_lead(attrs, signals, model=model)
        expected_raw = 20 * fit_w + 30 * eng_w
        assert result["score"] == pytest.approx(min(100, expected_raw), rel=1e-3)
        assert result["mql_threshold"] == threshold

    def test_score_lead_is_mql_true_when_above_threshold(self, scorer):
        # fit=85, engagement=55, hybrid score = 85*0.5 + 55*0.5 = 70 > 65
        attrs = {
            "company_size": "201-1000",  # 20
            "title": "c_suite",          # 25
            "role": "decision_maker",    # 20
            "industry": "primary",       # 20
        }
        signals = [
            {"type": "demo_request", "age_days": 0},   # 30
            {"type": "trial_signup", "age_days": 0},   # 25
        ]
        result = scorer.score_lead(attrs, signals, model="hybrid")
        assert result["is_mql"] is True

    def test_score_lead_engagement_decay(self, scorer):
        signals = [{"type": "pricing_page", "age_days": 14}]  # base=20, decay=5/week -> 20 - 5*2 = 10
        result = scorer.score_lead({}, signals, model="hybrid")
        assert result["engagement_score"] == pytest.approx(10.0, rel=1e-3)

    def test_score_lead_engagement_decay_floors_at_zero(self, scorer):
        signals = [{"type": "homepage_only", "age_days": 100}]  # base=1, decay=5/week, heavily decayed
        result = scorer.score_lead({}, signals, model="hybrid")
        assert result["engagement_score"] == 0.0

    def test_score_lead_no_decay_signals(self, scorer):
        signals = [
            {"type": "demo_request", "age_days": 999},   # decay=0, always 30
            {"type": "trial_signup", "age_days": 500},   # decay=0, always 25
        ]
        result = scorer.score_lead({}, signals, model="hybrid")
        assert result["engagement_score"] == pytest.approx(55.0, rel=1e-3)

    def test_score_lead_negative_scoring(self, scorer):
        attrs = {"negatives": ["competitor_domain", "personal_email"]}
        result = scorer.score_lead(attrs, [], model="hybrid")
        assert result["negative_score"] == pytest.approx(-60.0, rel=1e-3)
        assert len(result["breakdown"]["negatives"]) == 2

    def test_score_lead_spam_complaint_floors_to_zero(self, scorer):
        attrs = {
            "company_size": "201-1000",  # 20
            "negatives": ["spam_complaint"],  # -100
        }
        result = scorer.score_lead(attrs, [], model="hybrid")
        assert result["score"] == 0.0

    def test_score_lead_score_capped_at_100(self, scorer):
        attrs = {
            "company_size": "201-1000",  # 20
            "industry": "primary",        # 20
            "revenue": "100M+",           # 20
            "title": "c_suite",           # 25
            "department": "primary",      # 15
            "role": "decision_maker",     # 20
            "tech_fit": "replaces",       # 20
        }
        signals = [
            {"type": "demo_request", "age_days": 0},       # 30
            {"type": "contact_sales", "age_days": 0},      # 30
            {"type": "trial_signup", "age_days": 0},       # 25
            {"type": "core_feature_3x", "age_days": 0},   # 25
        ]
        result = scorer.score_lead(attrs, signals, model="hybrid")
        assert result["score"] == 100.0

    def test_score_lead_unknown_model_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_lead({}, [], model="bogus")

    def test_score_lead_breakdown_engagement_list(self, scorer):
        signals = [
            {"type": "email_click", "age_days": 7},
            {"type": "social_engage", "age_days": 0},
        ]
        result = scorer.score_lead({}, signals, model="hybrid")
        types = [s["type"] for s in result["breakdown"]["engagement"]]
        assert "email_click" in types
        assert "social_engage" in types

    def test_score_lead_unknown_signal_type_ignored(self, scorer):
        signals = [{"type": "nonexistent_signal", "age_days": 0}]
        result = scorer.score_lead({}, signals, model="hybrid")
        assert result["engagement_score"] == 0.0
        assert result["breakdown"]["engagement"] == []


# ---------------------------------------------------------------------------
# ab_test_calc
# ---------------------------------------------------------------------------

class TestAbTestCalc:
    def test_ab_test_calc_returns_required_keys(self, scorer):
        result = scorer.ab_test_calc(baseline=0.05, mde=0.2, traffic=500)
        assert {"sample_per_variant", "total_sample", "duration_days", "feasibility", "params"}.issubset(result)

    def test_ab_test_calc_two_variants_total_is_double(self, scorer):
        result = scorer.ab_test_calc(baseline=0.05, mde=0.2, traffic=1000, variants=2)
        assert result["total_sample"] == result["sample_per_variant"] * 2

    def test_ab_test_calc_three_variants_applies_bonferroni_multiplier(self, scorer):
        r2 = scorer.ab_test_calc(baseline=0.05, mde=0.2, traffic=1000, variants=2)
        r3 = scorer.ab_test_calc(baseline=0.05, mde=0.2, traffic=1000, variants=3)
        # multiplier for 3 variants = 1 + (3-2)*0.5 = 1.5
        assert r3["sample_per_variant"] == math.ceil(r2["sample_per_variant"] * 1.5)

    def test_ab_test_calc_duration_minimum_seven_days(self, scorer):
        # Very high traffic -> duration would be < 7 without floor
        result = scorer.ab_test_calc(baseline=0.05, mde=0.5, traffic=1_000_000)
        assert result["duration_days"] >= 7

    @pytest.mark.parametrize("baseline,mde,traffic,expected_feasibility", [
        (0.05, 0.2, 10_000, "feasible"),   # 33d
        (0.05, 0.2, 200, "marginal"),       # 82d
        (0.05, 0.2, 10, "infeasible"),      # 1643d+
    ])
    def test_ab_test_calc_feasibility_levels(self, scorer, baseline, mde, traffic, expected_feasibility):
        result = scorer.ab_test_calc(baseline=baseline, mde=mde, traffic=traffic)
        assert result["feasibility"] == expected_feasibility

    def test_ab_test_calc_params_echoed(self, scorer):
        result = scorer.ab_test_calc(baseline=0.1, mde=0.15, traffic=300, variants=4)
        p = result["params"]
        assert p["baseline"] == 0.1
        assert p["mde"] == 0.15
        assert p["traffic_per_day"] == 300
        assert p["variants"] == 4
        assert p["confidence"] == 0.95
        assert p["power"] == 0.80

    def test_ab_test_calc_duration_computed_from_total_and_traffic(self, scorer):
        result = scorer.ab_test_calc(baseline=0.05, mde=0.2, traffic=500)
        expected_days = max(7, math.ceil(result["total_sample"] / 500))
        assert result["duration_days"] == expected_days

    def test_ab_test_calc_larger_mde_needs_fewer_samples(self, scorer):
        r_small = scorer.ab_test_calc(baseline=0.05, mde=0.1, traffic=1000)
        r_large = scorer.ab_test_calc(baseline=0.05, mde=0.5, traffic=1000)
        assert r_large["sample_per_variant"] < r_small["sample_per_variant"]


# ---------------------------------------------------------------------------
# churn_health_score
# ---------------------------------------------------------------------------

class TestChurnHealthScore:
    def _all_equal(self, v):
        return {k: v for k in ("login_frequency", "feature_usage", "support_sentiment", "billing_health", "engagement")}

    @pytest.mark.parametrize("value,expected_tier,expected_action", [
        (90, "healthy", "upsell_opportunity"),
        (80, "healthy", "upsell_opportunity"),
        (65, "attention", "proactive_checkin"),
        (50, "at_risk", "intervention_campaign"),
        (20, "critical", "personal_outreach"),
    ])
    def test_churn_health_score_tier_assignment(self, scorer, value, expected_tier, expected_action):
        signals = self._all_equal(value)
        result = scorer.churn_health_score(signals)
        assert result["tier"] == expected_tier
        assert result["action"] == expected_action

    def test_churn_health_score_formula_correctness(self, scorer):
        signals = {"login_frequency": 80, "feature_usage": 60, "support_sentiment": 40, "billing_health": 100, "engagement": 50}
        result = scorer.churn_health_score(signals)
        expected = 80 * 0.30 + 60 * 0.25 + 40 * 0.15 + 100 * 0.15 + 50 * 0.15
        assert result["score"] == pytest.approx(expected, rel=1e-3)

    def test_churn_health_score_missing_signals_default_to_zero(self, scorer):
        result = scorer.churn_health_score({})
        assert result["score"] == 0.0
        assert result["tier"] == "critical"

    def test_churn_health_score_clamped_to_100(self, scorer):
        signals = {k: 200 for k in ("login_frequency", "feature_usage", "support_sentiment", "billing_health", "engagement")}
        result = scorer.churn_health_score(signals)
        assert result["score"] == 100.0

    def test_churn_health_score_risk_flags_present(self, scorer):
        signals = {
            "login_frequency": 80,
            "feature_usage": 80,
            "support_sentiment": 80,
            "billing_health": 80,
            "engagement": 80,
            "data_export": True,
            "nps_below_6": True,
        }
        result = scorer.churn_health_score(signals)
        assert "critical: data export initiated" in result["risk_flags"]
        assert "medium_risk: NPS below 6" in result["risk_flags"]

    def test_churn_health_score_no_risk_flags_when_none_set(self, scorer):
        result = scorer.churn_health_score({"login_frequency": 90})
        assert result["risk_flags"] == []

    @pytest.mark.parametrize("flag_key,expected_label", [
        ("login_drop_50pct", "high_risk: login frequency dropped 50%+"),
        ("feature_usage_stopped", "high_risk: key feature usage stopped"),
        ("support_spike_then_stop", "high_risk: support tickets spiked then stopped"),
        ("billing_page_visits", "high_risk: billing page visits increasing"),
        ("seats_removed", "high_risk: team seats removed"),
        ("data_export", "critical: data export initiated"),
        ("nps_below_6", "medium_risk: NPS below 6"),
    ])
    def test_churn_health_score_each_risk_flag(self, scorer, flag_key, expected_label):
        signals = {flag_key: True}
        result = scorer.churn_health_score(signals)
        assert expected_label in result["risk_flags"]

    def test_churn_health_score_components_returned(self, scorer):
        signals = {"login_frequency": 80, "feature_usage": 60}
        result = scorer.churn_health_score(signals)
        assert "login_frequency" in result["components"]
        assert "feature_usage" in result["components"]
        assert result["components"]["login_frequency"] == pytest.approx(80 * 0.30, rel=1e-3)


# ---------------------------------------------------------------------------
# cancel_flow_offer
# ---------------------------------------------------------------------------

class TestCancelFlowOffer:
    @pytest.mark.parametrize("reason,expected_primary", [
        ("too_expensive", "discount_20_30_pct_2_3_months"),
        ("not_using", "pause_1_3_months"),
        ("missing_feature", "roadmap_preview_timeline"),
        ("switching_competitor", "competitive_comparison_discount"),
        ("technical_issues", "escalate_support_immediately"),
        ("temporary", "pause_subscription"),
        ("business_closed", "skip_offer"),
    ])
    def test_cancel_flow_offer_known_reasons(self, scorer, reason, expected_primary):
        result = scorer.cancel_flow_offer(reason, mrr=50)
        assert result["primary_offer"] == expected_primary

    def test_cancel_flow_offer_business_closed_has_no_fallback(self, scorer):
        result = scorer.cancel_flow_offer("business_closed", mrr=100)
        assert result["fallback_offer"] is None

    def test_cancel_flow_offer_unknown_reason_returns_skip_offer(self, scorer):
        result = scorer.cancel_flow_offer("aliens", mrr=0)
        assert result["primary_offer"] == "skip_offer"
        assert result["fallback_offer"] is None

    @pytest.mark.parametrize("mrr,expected_routing", [
        (0, "automated"),
        (99.99, "automated"),
        (100, "automated_cs_flag"),
        (499.99, "automated_cs_flag"),
        (500, "route_to_cs"),
        (1999.99, "route_to_cs"),
        (2000, "block_self_serve"),
        (9999, "block_self_serve"),
    ])
    def test_cancel_flow_offer_mrr_routing(self, scorer, mrr, expected_routing):
        result = scorer.cancel_flow_offer("too_expensive", mrr=mrr)
        assert result["mrr_routing"] == expected_routing

    def test_cancel_flow_offer_discount_ladder_constant(self, scorer):
        result = scorer.cancel_flow_offer("too_expensive", mrr=200)
        assert result["discount_ladder"] == ["15_pct", "25_pct", "let_go"]

    def test_cancel_flow_offer_pause_config_structure(self, scorer):
        result = scorer.cancel_flow_offer("not_using", mrr=50)
        pc = result["pause_config"]
        assert pc["options"] == [1, 2, 3]
        assert pc["max_months"] == 3
        assert pc["repeat_limit"] == "1_per_12_months"

    def test_cancel_flow_offer_reason_echoed(self, scorer):
        result = scorer.cancel_flow_offer("too_expensive", mrr=0)
        assert result["reason"] == "too_expensive"


# ---------------------------------------------------------------------------
# crack_detect
# ---------------------------------------------------------------------------

class TestCrackDetect:
    def _contact(self, name, last_contact_days, touches=1, status="active"):
        return {"name": name, "last_contact_days": last_contact_days, "touches": touches, "status": status}

    def test_crack_detect_overdue_active_contact(self, scorer):
        contacts = [self._contact("Alice", last_contact_days=10, status="active")]
        result = scorer.crack_detect(contacts)
        assert any(c["name"] == "Alice" for c in result["overdue"])

    def test_crack_detect_overdue_warm_contact(self, scorer):
        contacts = [self._contact("Bob", last_contact_days=8, status="warm")]
        result = scorer.crack_detect(contacts)
        assert any(c["name"] == "Bob" for c in result["overdue"])

    def test_crack_detect_non_active_not_overdue(self, scorer):
        contacts = [self._contact("Carol", last_contact_days=15, status="cold")]
        result = scorer.crack_detect(contacts)
        assert not any(c["name"] == "Carol" for c in result["overdue"])

    def test_crack_detect_exclude_recent_contact(self, scorer):
        contacts = [self._contact("Dave", last_contact_days=2, status="active")]
        result = scorer.crack_detect(contacts)
        assert "Dave" in result["exclude"]
        assert not any(c["name"] == "Dave" for c in result["overdue"])

    def test_crack_detect_exclude_zero_days(self, scorer):
        contacts = [self._contact("Eve", last_contact_days=0, status="warm")]
        result = scorer.crack_detect(contacts)
        assert "Eve" in result["exclude"]

    def test_crack_detect_auto_close_three_touches_21d(self, scorer):
        contacts = [self._contact("Frank", last_contact_days=21, touches=3, status="active")]
        result = scorer.crack_detect(contacts)
        assert any(c["name"] == "Frank" for c in result["auto_close"])
        assert not any(c["name"] == "Frank" for c in result["overdue"])

    def test_crack_detect_stalled_two_touches_21d(self, scorer):
        contacts = [self._contact("Grace", last_contact_days=21, touches=2, status="active")]
        result = scorer.crack_detect(contacts)
        assert any(c["name"] == "Grace" for c in result["stalled"])
        assert not any(c["name"] == "Grace" for c in result["auto_close"])

    def test_crack_detect_stalled_not_triggered_below_21d(self, scorer):
        contacts = [self._contact("Hank", last_contact_days=20, touches=2, status="active")]
        result = scorer.crack_detect(contacts)
        assert not any(c["name"] == "Hank" for c in result["stalled"])

    def test_crack_detect_stale_loop_level_3_at_14d(self, scorer):
        loops = [{"id": "loop-1", "age_days": 14, "status": "open"}]
        result = scorer.crack_detect([], loops=loops)
        assert any(l["id"] == "loop-1" and l["level"] == 3 for l in result["stale_loops"])

    def test_crack_detect_stale_loop_level_2_at_7d(self, scorer):
        loops = [{"id": "loop-2", "age_days": 7, "status": "open"}]
        result = scorer.crack_detect([], loops=loops)
        assert any(l["id"] == "loop-2" and l["level"] == 2 for l in result["stale_loops"])

    def test_crack_detect_closed_loop_not_stale(self, scorer):
        loops = [{"id": "loop-3", "age_days": 30, "status": "closed"}]
        result = scorer.crack_detect([], loops=loops)
        assert result["stale_loops"] == []

    def test_crack_detect_loop_below_7d_not_stale(self, scorer):
        loops = [{"id": "loop-4", "age_days": 6, "status": "open"}]
        result = scorer.crack_detect([], loops=loops)
        assert result["stale_loops"] == []

    def test_crack_detect_no_loops_arg(self, scorer):
        result = scorer.crack_detect([])
        assert result["stale_loops"] == []

    def test_crack_detect_summary_counts(self, scorer):
        contacts = [
            self._contact("A", last_contact_days=10, status="active"),  # overdue
            self._contact("B", last_contact_days=1, status="active"),   # exclude
            self._contact("C", last_contact_days=25, touches=3, status="active"),  # auto_close
        ]
        loops = [{"id": "L1", "age_days": 14, "status": "open"}]
        result = scorer.crack_detect(contacts, loops=loops)
        assert result["summary"]["overdue_count"] == 1
        assert result["summary"]["exclude_count"] == 1
        assert result["summary"]["auto_close_count"] == 1
        assert result["summary"]["stale_loop_count"] == 1

    def test_crack_detect_overdue_action_field(self, scorer):
        contacts = [self._contact("Z", last_contact_days=9, status="warm")]
        result = scorer.crack_detect(contacts)
        assert result["overdue"][0]["action"] == "follow_up"
        assert result["overdue"][0]["days"] == 9
