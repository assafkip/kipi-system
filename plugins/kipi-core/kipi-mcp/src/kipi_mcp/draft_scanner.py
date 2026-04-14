from __future__ import annotations

import re


class DraftScanner:

    TIER1_WORDS = [
        "delve", "comprehensive", "crucial", "vital", "pivotal", "robust",
        "innovative", "transformative", "intricate", "meticulous", "nuanced",
        "vibrant", "enduring", "unparalleled", "unwavering", "cutting-edge",
        "groundbreaking", "unprecedented", "tapestry", "synergy", "realm",
        "beacon", "interplay", "treasure trove", "paradigm", "cornerstone",
        "catalyst", "linchpin", "testament",
        "ecosystem", "landscape", "holistic", "scalable", "disruptive",
        "next-gen", "seamless",
    ]

    TIER1_VERBS = [
        "leverage", "utilize", "optimize", "foster", "underscore", "embark",
        "garner", "bolster", "showcase", "enhance", "empower", "unlock",
        "revolutionize", "streamline", "spearhead",
    ]

    TIER1_ADVERBS = [
        "meticulously", "effectively", "efficiently", "strategically",
        "consistently", "seamlessly", "furthermore", "moreover",
        "additionally", "indeed",
    ]

    BANNED_PHRASES = [
        r"in today's \S+",
        "let's dive in", "let's explore", "let's unpack",
        "it's important to note", "it's crucial to note", "it's worth noting",
        "generally speaking",
        "in conclusion", "to sum up",
        "that said", "with that in mind",
        "this is where .+ comes in",
        "game-changer", "unlock the potential", "revolutionize the way",
        "a pivotal moment", "new era", "let's face it",
        "great question", "that's a really interesting point",
        "i hope this helps",
        "circling back", "just checking in", "following up on my last message",
        "i'm excited to", "thrilled to share", "proud to say", "humbled by",
    ]

    HEDGING_WORDS = ["might", "could", "perhaps", "generally", "somewhat", "arguably"]

    EMDASH = "\u2014"

    COPY_FIELD_NAMES = {
        "copy", "linkedin_draft", "x_thread", "rewritten_copy",
        "full_post_text", "dm_text", "cr_text", "comment_text",
        "email_body", "subject", "body", "text", "draft",
    }

    _word_patterns = [
        re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
        for w in TIER1_WORDS + TIER1_VERBS + TIER1_ADVERBS
    ]
    _phrase_patterns = [re.compile(p, re.IGNORECASE) for p in BANNED_PHRASES]
    _hedge_patterns = [
        re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in HEDGING_WORDS
    ]

    def scan(self, data: dict) -> dict:
        text_fields = self._extract_text_fields(data)
        all_violations: list[dict] = []
        all_text = ""

        for field_path, text in text_fields:
            all_text += " " + text
            all_violations.extend(self._scan_text(field_path, text))

        density, hedge_count = self._compute_hedging_density(all_text)
        if density > 1.0:
            all_violations.append({
                "type": "hedging_density",
                "word": f"{hedge_count} hedging words",
                "field": "all_fields",
                "context": f"Density: {density:.1f} per 500 words (max 1.0)",
            })

        word_count = len(all_text.split())

        return {
            "pass": len(all_violations) == 0,
            "file": "",
            "fields_scanned": len(text_fields),
            "words_scanned": word_count,
            "violation_count": len(all_violations),
            "hedging_density": round(density, 2),
            "violations": all_violations,
        }

    def _extract_text_fields(self, data, prefix: str = "") -> list[tuple[str, str]]:
        texts: list[tuple[str, str]] = []
        if isinstance(data, dict):
            for key, val in data.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(val, str) and key in self.COPY_FIELD_NAMES:
                    texts.append((path, val))
                elif isinstance(val, (dict, list)):
                    texts.extend(self._extract_text_fields(val, path))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                texts.extend(self._extract_text_fields(item, f"{prefix}[{i}]"))
        return texts

    def _scan_text(self, field_path: str, text: str) -> list[dict]:
        violations: list[dict] = []

        for pattern in self._word_patterns:
            for match in pattern.finditer(text):
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                violations.append({
                    "type": "banned_word",
                    "word": match.group(),
                    "field": field_path,
                    "context": text[start:end].replace("\n", " "),
                })

        for pattern in self._phrase_patterns:
            for match in pattern.finditer(text):
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                violations.append({
                    "type": "banned_phrase",
                    "word": match.group(),
                    "field": field_path,
                    "context": text[start:end].replace("\n", " "),
                })

        emdash_count = text.count(self.EMDASH)
        if emdash_count > 0:
            violations.append({
                "type": "emdash",
                "word": "emdash",
                "field": field_path,
                "context": f"{emdash_count} emdash(es) found",
            })

        return violations

    def _compute_hedging_density(self, all_text: str) -> tuple[float, int]:
        words = all_text.split()
        word_count = len(words)
        if word_count == 0:
            return 0.0, 0

        hedge_count = 0
        for pattern in self._hedge_patterns:
            hedge_count += len(pattern.findall(all_text))

        density = hedge_count / (word_count / 500) if word_count >= 50 else 0.0
        return density, hedge_count
