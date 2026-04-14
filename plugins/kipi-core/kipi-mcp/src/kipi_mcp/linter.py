from __future__ import annotations

import re

from kipi_mcp.draft_scanner import DraftScanner

_ds = DraftScanner()

_FILLER_OPENERS = re.compile(
    r"(?:I'm excited to announce|thrilled to share|proud to say|humbled by|In today's world)",
    re.IGNORECASE,
)
_STRUCTURAL_OPENERS = re.compile(
    r"^(?:Furthermore|Moreover|Additionally),",
    re.IGNORECASE | re.MULTILINE,
)

_PLATFORM_LIMITS: dict[str, dict] = {
    "google": {
        "headlines": {"hard": 30, "count_min": 3, "count_max": 15},
        "descriptions": {"hard": 90, "count_min": 2, "count_max": 4},
    },
    "meta": {
        "headlines": {"hard": 255, "recommended": 40},
        "descriptions": {"hard": 255, "recommended": 30},
    },
    "linkedin": {
        "headlines": {"hard": 200, "recommended": 70},
        "descriptions": {"hard": 300, "recommended": 100},
    },
    "twitter": {
        "headlines": {"hard": 70},
        "descriptions": {"hard": 200},
    },
    "tiktok": {
        "headlines": {"hard": 40},
        "descriptions": {"hard": 100, "recommended": 80},
    },
}

_REPLACEMENTS: dict[str, str] = {
    "utilize": "use",
    "leverage": "use",
    "optimize": "improve",
    "facilitate": "help",
    "implement": "do",
    "commence": "start",
    "cease": "stop",
    "approximately": "about",
    "assistance": "help",
    "demonstrate": "show",
    "comprise": "include",
    "subsequently": "later",
    "furthermore": "also",
    "moreover": "also",
    "accordingly": "so",
    "nevertheless": "but",
    "due to the fact that": "because",
    "in order to": "to",
    "in addition to": "also",
}

_FILLER_WORDS = [
    "basically", "actually", "very", "really", "extremely",
    "incredibly", "just", "quite", "obviously", "of course",
]

_WEAK_INTENSIFIERS = {"very", "really", "extremely", "incredibly"}

_PASSIVE_RE = re.compile(r"\b(is|are|was|were|been|being)\s+\w+ed\b", re.IGNORECASE)

_RULE_OF_THREE_RE = re.compile(r"\b\w+,\s+\w+,\s+\w+\b")

_HASHTAG_RE = re.compile(r"#\w+")
_URL_RE = re.compile(r"https?://\S+")
_LINKEDIN_ALLOWED_DAYS = {"tue", "tuesday", "wed", "wednesday", "thu", "thursday"}

_SUBJECT_SALESY = re.compile(
    r"\b(increase|boost|ROI)\b", re.IGNORECASE
)
_SUBJECT_URGENCY = re.compile(r"\b(ASAP|urgent)\b", re.IGNORECASE)
_SUBJECT_SPAM = re.compile(
    r"\b(free|guarantee|act now)\b", re.IGNORECASE
)
_BODY_AI_PHRASES = re.compile(
    r"(I hope this email finds you well|I came across your profile"
    r"|leverage|synergy|best-in-class)",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _context_around(text: str, match: re.Match, pad: int = 40) -> str:
    start = max(0, match.start() - pad)
    end = min(len(text), match.end() + pad)
    return text[start:end].replace("\n", " ")


class Linter:

    def voice_lint(self, text: str) -> dict:
        violations: list[dict] = []

        words = text.split()
        word_count = len(words)
        sents = _sentences(text)
        sentence_count = len(sents)
        avg_sentence_length = (
            sum(len(s.split()) for s in sents) / sentence_count
            if sentence_count else 0.0
        )

        if avg_sentence_length > 20:
            violations.append({
                "type": "sentence_length",
                "detail": f"avg sentence length {avg_sentence_length:.1f} words (target 8-15, max 20)",
                "context": "",
            })

        paras = _paragraphs(text)
        if len(paras) >= 3:
            counts = [len(_sentences(p)) for p in paras]
            if len(set(counts)) == 1:
                violations.append({
                    "type": "paragraph_uniformity",
                    "detail": f"all {len(paras)} paragraphs have {counts[0]} sentence(s) each",
                    "context": "",
                })

        for pattern in _ds._word_patterns:
            for match in pattern.finditer(text):
                violations.append({
                    "type": "banned_word",
                    "detail": f"banned word: {match.group()}",
                    "context": _context_around(text, match),
                })

        for pattern in _ds._phrase_patterns:
            for match in pattern.finditer(text):
                violations.append({
                    "type": "banned_phrase",
                    "detail": f"banned phrase: {match.group()}",
                    "context": _context_around(text, match),
                })

        emdash_count = text.count(_ds.EMDASH)
        if emdash_count:
            violations.append({
                "type": "emdash",
                "detail": f"{emdash_count} em-dash(es) found",
                "context": "",
            })

        for match in _FILLER_OPENERS.finditer(text):
            violations.append({
                "type": "filler_opener",
                "detail": f"filler opening phrase: {match.group()}",
                "context": _context_around(text, match),
            })

        for match in _STRUCTURAL_OPENERS.finditer(text):
            violations.append({
                "type": "structural_opener",
                "detail": f"structural anti-pattern opener: {match.group()}",
                "context": _context_around(text, match),
            })

        for match in _RULE_OF_THREE_RE.finditer(text):
            violations.append({
                "type": "rule_of_three",
                "severity": "warning",
                "detail": f"possible rule-of-three list: {match.group()}",
                "context": _context_around(text, match),
            })

        hedge_count = sum(
            len(p.findall(text)) for p in _ds._hedge_patterns
        )
        hedging_density = (
            hedge_count / (word_count / 500) if word_count >= 50 else 0.0
        )

        blocking_count = sum(
            1 for v in violations if v.get("severity") != "warning"
        )

        return {
            "pass": blocking_count == 0,
            "word_count": word_count,
            "sentence_count": sentence_count,
            "avg_sentence_length": round(avg_sentence_length, 2),
            "hedging_density": round(hedging_density, 2),
            "violation_count": len(violations),
            "violations": violations,
        }

    def validate_schedule(self, items: list[dict], day: str = "") -> dict:
        errors: list[str] = []
        warnings: list[str] = []

        section_ids = [s.get("id", "") for s in items]
        has_pipeline = any("pipeline-followups" in sid for sid in section_ids)
        has_new_leads = any("new-leads" in sid for sid in section_ids)

        if has_pipeline and has_new_leads:
            pipeline_idx = next(
                (i for i, s in enumerate(items) if "pipeline-followups" in s.get("id", "")), -1
            )
            leads_idx = next(
                (i for i, s in enumerate(items) if "new-leads" in s.get("id", "")), -1
            )
            if pipeline_idx > leads_idx:
                errors.append("pipeline-followups section must come before new-leads section")

        if has_pipeline:
            pipeline_section = next(
                (s for s in items if "pipeline-followups" in s.get("id", "")), None
            )
            if pipeline_section:
                followup_items = pipeline_section.get("items", [])
                if len(followup_items) < 3:
                    errors.append(
                        f"pipeline-followups requires at least 3 items, found {len(followup_items)}"
                    )
                for item in followup_items:
                    has_copy = bool(
                        item.get("copyBlocks") and any(
                            b.get("text") for b in item["copyBlocks"]
                            if isinstance(b, dict)
                        )
                    )
                    needs_eyes = item.get("needsEyes", False)
                    if not has_copy and not needs_eyes:
                        errors.append(
                            f"pipeline item '{item.get('id', '?')}' must have copyBlocks text or needsEyes: true"
                        )

        all_items = [item for section in items for item in section.get("items", [])]
        all_titles = [i.get("title", "").lower() for i in all_items]

        day = day.lower()
        if day in ("mon", "wed", "fri"):
            if not any("signal" in t or "x-post" in t for t in all_titles):
                errors.append(f"{day}: must have item with 'signal' or 'x-post' in title")

        if day in ("tue", "thu"):
            tl_items = [
                i for i in all_items
                if ("thought leadership" in i.get("title", "").lower()
                    or "linkedin post" in i.get("title", "").lower())
                and i.get("platform", "").lower() == "linkedin"
            ]
            if not tl_items:
                errors.append(
                    f"{day}: must have item with 'thought leadership' or 'linkedin post' title and platform==linkedin"
                )

        if day == "mon" and not any("medium" in t for t in all_titles):
            warnings.append("mon: no item with 'medium' in title")

        if day == "wed" and not any("kipi" in t for t in all_titles):
            warnings.append("wed: no item with 'kipi' in title")

        has_quick_wins = any(
            "quick" in s.get("id", "").lower() or "quick" in s.get("title", "").lower()
            for s in items
        )
        if not has_quick_wins:
            warnings.append("quick wins section missing or empty")
        else:
            qw_section = next(
                (s for s in items
                 if "quick" in s.get("id", "").lower() or "quick" in s.get("title", "").lower()),
                None
            )
            if qw_section and not qw_section.get("items"):
                warnings.append("quick wins section is empty")

        for item in all_items:
            if not item.get("energy"):
                warnings.append(f"item '{item.get('id', '?')}' missing energy field")

        return {
            "pass": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def validate_ad_copy(
        self,
        platform: str,
        headlines: list[str],
        descriptions: list[str],
    ) -> dict:
        violations: list[dict] = []
        warnings: list[dict] = []

        p = platform.lower()
        limits = _PLATFORM_LIMITS.get(p, {})
        hl_limits = limits.get("headlines", {})
        desc_limits = limits.get("descriptions", {})

        if p == "google":
            count_min = hl_limits.get("count_min", 3)
            count_max = hl_limits.get("count_max", 15)
            if not (count_min <= len(headlines) <= count_max):
                violations.append({
                    "field": "headlines",
                    "index": -1,
                    "length": len(headlines),
                    "limit": count_max,
                    "text": f"count {len(headlines)} outside [{count_min}, {count_max}]",
                })
            desc_count_min = desc_limits.get("count_min", 2)
            desc_count_max = desc_limits.get("count_max", 4)
            if not (desc_count_min <= len(descriptions) <= desc_count_max):
                violations.append({
                    "field": "descriptions",
                    "index": -1,
                    "length": len(descriptions),
                    "limit": desc_count_max,
                    "text": f"count {len(descriptions)} outside [{desc_count_min}, {desc_count_max}]",
                })

        for i, h in enumerate(headlines):
            hard = hl_limits.get("hard")
            if hard and len(h) > hard:
                violations.append({
                    "field": "headlines",
                    "index": i,
                    "length": len(h),
                    "limit": hard,
                    "text": h,
                })
            rec = hl_limits.get("recommended")
            if rec and len(h) > rec:
                warnings.append({
                    "field": "headlines",
                    "index": i,
                    "length": len(h),
                    "recommended": rec,
                })

        for i, d in enumerate(descriptions):
            hard = desc_limits.get("hard")
            if hard and len(d) > hard:
                violations.append({
                    "field": "descriptions",
                    "index": i,
                    "length": len(d),
                    "limit": hard,
                    "text": d,
                })
            rec = desc_limits.get("recommended")
            if rec and len(d) > rec:
                warnings.append({
                    "field": "descriptions",
                    "index": i,
                    "length": len(d),
                    "recommended": rec,
                })

        return {
            "pass": len(violations) == 0,
            "platform": platform,
            "violations": violations,
            "warnings": warnings,
        }

    def seo_check(
        self,
        title: str = "",
        meta: str = "",
        headings: list[dict] | None = None,
        cwv: dict | None = None,
    ) -> dict:
        errors: list[str] = []
        warnings: list[str] = []

        title_length = len(title)
        meta_length = len(meta)

        if not title:
            errors.append("title is empty")
        elif title_length < 50:
            warnings.append(f"title length {title_length} is below 50 chars (ideal 50-60)")
        elif title_length > 60:
            warnings.append(f"title length {title_length} exceeds 60 chars (ideal 50-60)")

        if not meta:
            errors.append("meta description is empty")
        elif meta_length < 150:
            warnings.append(f"meta description length {meta_length} is below 150 chars (ideal 150-160)")
        elif meta_length > 160:
            warnings.append(f"meta description length {meta_length} exceeds 160 chars (ideal 150-160)")

        if headings is not None:
            levels = [h.get("level", 0) for h in headings]
            h1_count = levels.count(1)
            if h1_count == 0:
                errors.append("no H1 found")
            elif h1_count > 1:
                errors.append(f"multiple H1 tags found ({h1_count})")

            unique_levels = sorted(set(levels))
            if unique_levels:
                for a, b in zip(unique_levels, unique_levels[1:]):
                    if b - a > 1:
                        errors.append(
                            f"heading level skip: H{a} to H{b} without H{a + 1}"
                        )

        if cwv is not None:
            lcp = cwv.get("lcp")
            inp = cwv.get("inp")
            cls = cwv.get("cls")
            if lcp is not None and lcp >= 2.5:
                errors.append(f"LCP {lcp}s exceeds 2.5s threshold")
            if inp is not None and inp >= 200:
                errors.append(f"INP {inp}ms exceeds 200ms threshold")
            if cls is not None and cls >= 0.1:
                errors.append(f"CLS {cls} exceeds 0.1 threshold")

        return {
            "pass": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "title_length": title_length,
            "meta_length": meta_length,
        }

    def validate_cold_email(self, subject: str, body: str) -> dict:
        errors: list[str] = []
        warnings: list[str] = []

        subject_words = subject.split()
        subject_word_count = len(subject_words)
        if not (2 <= subject_word_count <= 4):
            warnings.append(
                f"subject word count {subject_word_count} outside optimal range 2-4"
            )

        if _SUBJECT_SALESY.search(subject):
            warnings.append("subject contains salesy words (increase/boost/ROI)")
        if _SUBJECT_URGENCY.search(subject):
            warnings.append("subject contains urgency language (ASAP/urgent)")
        if len(re.findall(r"[!?]", subject)) >= 2:
            warnings.append("subject has excessive punctuation (2+ ! or ?)")
        if re.search(r"\d+%?", subject):
            warnings.append("subject contains numbers or percentages")
        if re.search(r"[^\x00-\x7F]", subject):
            warnings.append("subject contains emojis or non-ASCII characters")
        if _SUBJECT_SPAM.search(subject):
            warnings.append("subject contains spam trigger words (free/guarantee/act now)")

        body_words = body.split()
        body_word_count = len(body_words)

        if body_word_count > 150:
            errors.append(f"body word count {body_word_count} exceeds 150 word limit")
        elif not (25 <= body_word_count <= 75):
            warnings.append(
                f"body word count {body_word_count} outside optimal range 25-75"
            )

        body_sents = _sentences(body)
        avg_sentence_length = (
            sum(len(s.split()) for s in body_sents) / len(body_sents)
            if body_sents else 0.0
        )
        if avg_sentence_length > 15:
            warnings.append(
                f"avg sentence length {avg_sentence_length:.1f} words suggests high reading complexity"
            )

        for match in _BODY_AI_PHRASES.finditer(body):
            warnings.append(f"AI pattern detected: '{match.group()}'")

        question_count = body.count("?")
        if question_count > 1:
            warnings.append(f"body has {question_count} question marks — consider a single CTA")

        return {
            "pass": len(errors) == 0,
            "subject_word_count": subject_word_count,
            "body_word_count": body_word_count,
            "avg_sentence_length": round(avg_sentence_length, 2),
            "errors": errors,
            "warnings": warnings,
        }

    def linkedin_gate(
        self,
        draft: str,
        kind: str = "post",
        day_of_week: str = "",
        override_day: bool = False,
    ) -> dict:
        kind_norm = kind.strip().lower() or "post"
        if kind_norm not in ("post", "comment", "dm", "about"):
            raise ValueError(
                f"kind must be one of post|comment|dm|about, got '{kind}'"
            )

        voice = self.voice_lint(draft)
        copy_edit = self.copy_edit_lint(draft)

        violations: list[dict] = []

        hashtag_matches = _HASHTAG_RE.findall(draft)
        hashtag_count = len(hashtag_matches)
        if hashtag_count > 1:
            violations.append({
                "type": "hashtag_count",
                "detail": f"{hashtag_count} hashtags found (max 1)",
                "context": ", ".join(hashtag_matches[:5]),
            })

        body_links = _URL_RE.findall(draft)
        if kind_norm == "post" and body_links:
            violations.append({
                "type": "body_link",
                "detail": f"{len(body_links)} link(s) in body — move to first comment",
                "context": body_links[0],
            })

        day_ok = True
        day_norm = day_of_week.strip().lower()
        if kind_norm == "post" and day_norm and not override_day:
            if day_norm not in _LINKEDIN_ALLOWED_DAYS:
                day_ok = False
                violations.append({
                    "type": "day_of_week",
                    "detail": f"ship day={day_of_week} — allowed Tue/Wed/Thu (pass override_day=true to bypass)",
                    "context": "",
                })

        return {
            "pass": (
                voice["pass"]
                and copy_edit["pass"]
                and len(violations) == 0
            ),
            "kind": kind_norm,
            "lint_voice": voice,
            "lint_copy": copy_edit,
            "hashtag_count": hashtag_count,
            "body_links": body_links,
            "day_ok": day_ok,
            "violations": violations,
        }

    def copy_edit_lint(self, text: str) -> dict:
        replacements: list[dict] = []
        filler_map: dict[str, int] = {}
        passive_voice: list[dict] = []

        for complex_form, plain in _REPLACEMENTS.items():
            pattern = re.compile(r"\b" + re.escape(complex_form) + r"\b", re.IGNORECASE)
            for match in pattern.finditer(text):
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                replacements.append({
                    "original": match.group(),
                    "suggested": plain,
                    "context": text[start:end].replace("\n", " "),
                })

        for word in _FILLER_WORDS:
            pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            count = len(pattern.findall(text))
            if count:
                filler_map[word] = filler_map.get(word, 0) + count

        filler_words = [{"word": w, "count": c} for w, c in filler_map.items()]

        for match in _PASSIVE_RE.finditer(text):
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            passive_voice.append({
                "context": text[start:end].replace("\n", " "),
            })

        total_issues = len(replacements) + len(filler_words) + len(passive_voice)

        return {
            "pass": total_issues == 0,
            "word_count": len(text.split()),
            "replacements": replacements,
            "filler_words": filler_words,
            "passive_voice": passive_voice,
            "total_issues": total_issues,
        }
