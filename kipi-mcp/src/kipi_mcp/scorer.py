from __future__ import annotations

import math


COMPANY_SIZE_SCORES = {"1-10": 5, "11-50": 10, "51-200": 15, "201-1000": 20, "1000+": 15}
INDUSTRY_SCORES = {"primary": 20, "secondary": 10, "other": 0}
REVENUE_SCORES = {"<1M": 5, "1M-10M": 10, "10M-100M": 15, "100M+": 20}
TITLE_SCORES = {"c_suite": 25, "vp": 20, "director": 15, "manager": 10, "ic": 5}
DEPARTMENT_SCORES = {"primary": 15, "adjacent": 5, "other": 0}
ROLE_SCORES = {"decision_maker": 20, "influencer": 10, "end_user": 5}
TECH_SCORES = {"replaces": 20, "complementary": 15, "competitor": 10, "modern": 10, "legacy": 5}

SIGNAL_SCORES: dict[str, tuple[float, float]] = {
    "demo_request": (30, 0),
    "pricing_page": (20, 5),
    "trial_signup": (25, 0),
    "contact_sales": (30, 0),
    "case_study": (15, 2.5),
    "comparison_page": (15, 5),
    "roi_calculator": (20, 2.5),
    "webinar_register": (10, 1.25),
    "webinar_attend": (15, 1.25),
    "whitepaper": (10, 1.25),
    "blog_visit_3": (10, 2.5),
    "email_click": (5, 0.5),
    "email_open_3": (5, 0.5),
    "social_engage": (5, 0.5),
    "single_blog": (2, 0.5),
    "newsletter_open": (2, 0.25),
    "single_email_open": (1, 0.25),
    "homepage_only": (1, 5),
    "account_created": (15, 0),
    "onboarding_complete": (20, 0),
    "core_feature_3x": (25, 1.25),
    "invited_member": (25, 0),
    "hit_usage_limit": (20, 2.5),
    "data_export": (10, 1.25),
    "connected_integration": (15, 0),
    "daily_active_5d": (20, 2.5),
}

NEGATIVE_SCORES = {
    "competitor_domain": -50,
    "student_email": -30,
    "personal_email": -10,
    "unsubscribe": -20,
    "hard_bounce": -50,
    "spam_complaint": -100,
    "student_title": -25,
    "consultant_title": -10,
    "no_visit_90d": -15,
    "invalid_phone": -10,
    "careers_only": -30,
}

MODEL_CONFIG = {
    "plg": {"weights": (0.3, 0.7), "mql_threshold": 60},
    "enterprise": {"weights": (0.6, 0.4), "mql_threshold": 75},
    "hybrid": {"weights": (0.5, 0.5), "mql_threshold": 65},
}

OFFER_MAP = {
    "too_expensive": {"primary": "discount_20_30_pct_2_3_months", "fallback": "downgrade_plan"},
    "not_using": {"primary": "pause_1_3_months", "fallback": "free_onboarding_session"},
    "missing_feature": {"primary": "roadmap_preview_timeline", "fallback": "workaround_guide"},
    "switching_competitor": {"primary": "competitive_comparison_discount", "fallback": "feedback_session"},
    "technical_issues": {"primary": "escalate_support_immediately", "fallback": "credit_priority_fix"},
    "temporary": {"primary": "pause_subscription", "fallback": "downgrade_temporarily"},
    "business_closed": {"primary": "skip_offer", "fallback": None},
}

RISK_FLAG_MAP = {
    "login_drop_50pct": "high_risk: login frequency dropped 50%+",
    "feature_usage_stopped": "high_risk: key feature usage stopped",
    "support_spike_then_stop": "high_risk: support tickets spiked then stopped",
    "billing_page_visits": "high_risk: billing page visits increasing",
    "seats_removed": "high_risk: team seats removed",
    "data_export": "critical: data export initiated",
    "nps_below_6": "medium_risk: NPS below 6",
}


class Scorer:
    def score_lead(
        self,
        attributes: dict,
        signals: list[dict],
        model: str = "hybrid",
    ) -> dict:
        if model not in MODEL_CONFIG:
            raise ValueError(f"Unknown model: {model}. Must be one of {list(MODEL_CONFIG)}")

        fit_breakdown: dict[str, int] = {}
        fit_score = 0.0

        score_maps = [
            ("company_size", COMPANY_SIZE_SCORES),
            ("industry", INDUSTRY_SCORES),
            ("revenue", REVENUE_SCORES),
            ("title", TITLE_SCORES),
            ("department", DEPARTMENT_SCORES),
            ("role", ROLE_SCORES),
            ("tech_fit", TECH_SCORES),
        ]
        for key, score_map in score_maps:
            val = attributes.get(key)
            if val in score_map:
                points = score_map[val]
                fit_breakdown[key] = points
                fit_score += points

        engagement_breakdown: list[dict] = []
        engagement_score = 0.0

        for signal in signals:
            signal_type = signal.get("type", "")
            age_days = signal.get("age_days", 0)
            if signal_type not in SIGNAL_SCORES:
                continue
            base, decay_per_week = SIGNAL_SCORES[signal_type]
            decayed = max(0.0, base - decay_per_week * (age_days / 7))
            engagement_breakdown.append({"type": signal_type, "age_days": age_days, "score": decayed})
            engagement_score += decayed

        negatives_applied: list[dict] = []
        negative_total = 0.0

        for neg_key in attributes.get("negatives", []):
            if neg_key in NEGATIVE_SCORES:
                pts = NEGATIVE_SCORES[neg_key]
                negatives_applied.append({"signal": neg_key, "score": pts})
                negative_total += pts

        cfg = MODEL_CONFIG[model]
        fit_weight, engage_weight = cfg["weights"]
        mql_threshold = cfg["mql_threshold"]

        raw = fit_score * fit_weight + engagement_score * engage_weight + negative_total
        final = max(0.0, min(100.0, raw))

        return {
            "score": round(final, 2),
            "fit_score": round(fit_score, 2),
            "engagement_score": round(engagement_score, 2),
            "negative_score": round(negative_total, 2),
            "model": model,
            "mql_threshold": mql_threshold,
            "is_mql": final >= mql_threshold,
            "breakdown": {
                "fit": fit_breakdown,
                "engagement": engagement_breakdown,
                "negatives": negatives_applied,
            },
        }

    def ab_test_calc(
        self,
        baseline: float,
        mde: float,
        traffic: int,
        variants: int = 2,
    ) -> dict:
        p1 = baseline
        p2 = baseline * (1 + mde)
        p_bar = (p1 + p2) / 2

        n_per_variant = (
            (1.96 * math.sqrt(2 * p_bar * (1 - p_bar)) + 0.84 * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
        ) / ((p2 - p1) ** 2)
        n_per_variant = math.ceil(n_per_variant)

        if variants > 2:
            multiplier = 1 + (variants - 2) * 0.5
            n_per_variant = math.ceil(n_per_variant * multiplier)

        total_sample = n_per_variant * variants
        duration_days = max(7, math.ceil(total_sample / traffic))

        if duration_days <= 56:
            feasibility = "feasible"
        elif duration_days <= 84:
            feasibility = "marginal"
        else:
            feasibility = "infeasible"

        return {
            "sample_per_variant": n_per_variant,
            "total_sample": total_sample,
            "duration_days": duration_days,
            "feasibility": feasibility,
            "params": {
                "baseline": baseline,
                "mde": mde,
                "traffic_per_day": traffic,
                "variants": variants,
                "confidence": 0.95,
                "power": 0.80,
            },
        }

    def churn_health_score(self, signals: dict) -> dict:
        components = {
            "login_frequency": signals.get("login_frequency", 0) * 0.30,
            "feature_usage": signals.get("feature_usage", 0) * 0.25,
            "support_sentiment": signals.get("support_sentiment", 0) * 0.15,
            "billing_health": signals.get("billing_health", 0) * 0.15,
            "engagement": signals.get("engagement", 0) * 0.15,
        }
        score = max(0.0, min(100.0, sum(components.values())))

        if score >= 80:
            tier, action = "healthy", "upsell_opportunity"
        elif score >= 60:
            tier, action = "attention", "proactive_checkin"
        elif score >= 40:
            tier, action = "at_risk", "intervention_campaign"
        else:
            tier, action = "critical", "personal_outreach"

        risk_flags = [
            label
            for key, label in RISK_FLAG_MAP.items()
            if signals.get(key) is True
        ]

        return {
            "score": round(score, 2),
            "tier": tier,
            "action": action,
            "risk_flags": risk_flags,
            "components": {k: round(v, 4) for k, v in components.items()},
        }

    def cancel_flow_offer(self, reason: str, mrr: float = 0) -> dict:
        offers = OFFER_MAP.get(reason, {"primary": "skip_offer", "fallback": None})

        if mrr < 100:
            mrr_routing = "automated"
        elif mrr < 500:
            mrr_routing = "automated_cs_flag"
        elif mrr < 2000:
            mrr_routing = "route_to_cs"
        else:
            mrr_routing = "block_self_serve"

        return {
            "reason": reason,
            "primary_offer": offers["primary"],
            "fallback_offer": offers["fallback"],
            "mrr_routing": mrr_routing,
            "discount_ladder": ["15_pct", "25_pct", "let_go"],
            "pause_config": {
                "options": [1, 2, 3],
                "max_months": 3,
                "repeat_limit": "1_per_12_months",
            },
        }

    def crack_detect(
        self,
        contacts: list[dict],
        loops: list[dict] | None = None,
    ) -> dict:
        overdue: list[dict] = []
        exclude: list[str] = []
        auto_close: list[dict] = []
        stalled: list[dict] = []

        for c in contacts:
            name = c["name"]
            days = c["last_contact_days"]
            touches = c.get("touches", 0)
            status = c.get("status", "")

            if days <= 2:
                exclude.append(name)
                continue

            if touches >= 3 and days >= 21:
                auto_close.append({"name": name, "reason": f"{touches} touches, {days}d since last contact"})
                continue

            if touches >= 2 and days >= 21:
                stalled.append({"name": name, "reason": f"{touches} touches, {days}d since last contact"})
                continue

            if days > 7 and status in ("active", "warm"):
                overdue.append({"name": name, "days": days, "action": "follow_up"})

        stale_loops: list[dict] = []
        for loop in (loops or []):
            age = loop.get("age_days", 0)
            if loop.get("status") != "open":
                continue
            if age >= 14:
                stale_loops.append({"id": loop["id"], "age_days": age, "level": 3})
            elif age >= 7:
                stale_loops.append({"id": loop["id"], "age_days": age, "level": 2})

        return {
            "overdue": overdue,
            "exclude": exclude,
            "auto_close": auto_close,
            "stalled": stalled,
            "stale_loops": stale_loops,
            "summary": {
                "overdue_count": len(overdue),
                "exclude_count": len(exclude),
                "auto_close_count": len(auto_close),
                "stale_loop_count": len(stale_loops),
            },
        }
