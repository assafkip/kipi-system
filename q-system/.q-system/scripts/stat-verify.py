#!/usr/bin/env python3
"""
stat-verify.py — deterministic verification of numeric and source-cited
claims in agent-pipeline bus content + published markdown against the
instance's canonical stat registry.

Background: on 2026-05-21 the morning content pipeline shipped a tweet
claiming "SIEMs are missing 76% of ATT&CK coverage" while the canonical
fact (CardinalOps 2025) is "21% coverage / data for 90%+". The compliance
reviewer agent signed it off because it pattern-matched tone, not stats.
This script closes that gap with a closed-world lookup against
canonical/stat-registry.json.

Scope:
    PostToolUse hook on Edit|Write|MultiEdit. Self-scopes by path.
    In-scope paths:
      - **/agent-pipeline/bus/**/*.json  (agent-produced content)
      - **/output/*-post-*.md
      - **/output/*-draft-*.md
      - **/output/linkedin-*.md / medium-*.md / substack-*.md
      - **/marketing/**.md
      - **/output/articles/**.md
    For JSON files, only content fields are inspected (keys that look like
    draft/body/text/comment/thread/post/reply/hot_take/message/dm).
    Pipeline metadata files (_meta.json, preflight.json, state-checksums.json,
    schemas, etc.) are out of scope.

Exit codes:
    0 — clean or out-of-scope.
    2 — at least one numeric or source claim could not be matched against
        the canonical stat-registry and no inline opt-out was present.

Opt-outs:
    - Inline tag {{UNVALIDATED}} or {{NEEDS_PROOF}} within 80 chars before
      or after the claim suppresses that single claim.
    - File-level marker  stat-verify-skip  (in any line) suppresses the
      whole file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date as _date
from pathlib import Path


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

IN_SCOPE_PATTERNS = [
    re.compile(r"agent-pipeline/bus/[^/]+/[^/]+\.json$"),
    re.compile(r"output/articles/.*\.md$"),
    re.compile(r"marketing/.*\.md$"),
    re.compile(r"output/.*-post-.*\.md$"),
    re.compile(r"output/.*-draft-.*\.md$"),
    re.compile(r"output/(linkedin|medium|substack)-.*\.md$"),
]

# Bus files that are either pipeline metadata OR ingestion (scraped third-party
# content). Either way, they are NOT founder-authored content and must not be
# gated on canonical stats.
BUS_METADATA_BASENAMES = {
    # Pipeline metadata
    "_meta.json",
    "preflight.json",
    "state-checksums.json",
    "energy.json",
    "step-8-gate.json",
    "step-11-gate.json",
    "daily-checklists.json",
    "ladder-patch.json",
    "icp-rejected.json",
    "copy-diffs.json",
    "stat-verify-blocks.json",
    "canonical-digest.json",
    "compliance.json",
    "copy-review.json",
    "loop-review.json",
    "behavioral-signals.json",
    "post-visuals.json",
    "leads.json",
    "icp-discovery.json",
    "linkedin-posts.json",
    "notion-push.json",
    "weekly-rollup.json",
    # Ingestion / third-party content (not authored by founder)
    "calendar.json",
    "gmail.json",
    "notion.json",
    "prospect-activity.json",
    "reddit-discovery.json",
    "reddit-fetch-raw.json",
    "reddit-fetch-spec.json",
    "meeting-prep.json",
}

# File-name prefixes that mark ingestion content.
INGESTION_PREFIXES = ("reddit-", "gmail-", "calendar-")

# JSON keys whose string values are content the user / audience will see.
# Substring match (case-insensitive) — generous on purpose so new content
# fields don't bypass the gate when an agent invents a name.
CONTENT_KEY_SUBSTRINGS = (
    "draft",
    "body",
    "text",
    "comment",
    "thread",
    "post",
    "reply",
    "hot_take",
    "hot-take",
    "message",
    "dm",
    "subject",
    "headline",
    "caption",
    "tweet",
    "blurb",
    "linkedin",
    "x_",
)

# JSON keys to NEVER lint even if they match CONTENT_KEY_SUBSTRINGS — these
# are template / config / pointer fields, not user-facing content.
CONTENT_KEY_DENY_EXACT = {
    "evergreen_used",
    "angle_source",
    "format",
    "auto_fail_check",
    "performance_note",
    "first_hour_comment_plan",
    "source_file",
    "item_id",
    "note",
    "rule",
    "recommendation",
    "source",
    "id",
}


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# Percentages: not part of a longer number (no leading digit or dot), digits,
# optional decimal, optional whitespace, %.
PERCENT_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")

# Dollars: $ then digits with optional decimal and K/M/B suffix (and +).
DOLLAR_RE = re.compile(r"\$\d+(?:\.\d+)?(?:[KMB]\+?)?(?![\w])")

# Multipliers: e.g. 3x, 4-5x
MULTIPLIER_RE = re.compile(r"\b\d+(?:-\d+)?x\b", re.IGNORECASE)

# Quantitative duration claims: only fire when the duration has a `+`
# (quantity claim like "40+ hours") OR a "-N" range (like "$25-75K"), OR is
# paired with a benchmark verb / measurement context within ~40 chars.
#
# Why: narrative durations ("got 20 minutes next week", "38 days since last
# touch") are not stat-shaped claims. The verifier is meant to gate
# industry-benchmark numerics, not conversational time references.
DURATION_RE = re.compile(
    r"\b(\d+(?:\.\d+)?(?:\+|\-\d+)?)\s+"
    r"(hours?|hrs?|days?|months?|years?|seconds?|weeks?)\b",
    re.IGNORECASE,
)

BENCHMARK_CONTEXT_RE = re.compile(
    r"\b(average|median|takes|took|spent|spends|spend|costs?|costing|fully\s+loaded|"
    r"attackers?\s+(?:exploit|need)|exploit\s+in|remediat\w+|tenure|advisor(?:y|ies)|"
    r"breach|response|sla|throughput|p99|p95|baseline|industry|study|survey|"
    r"report|reports|per\s+year|per\s+month|per\s+week|/yr|/year|/mo|/month|/wk)\b",
    re.IGNORECASE,
)

# Count claims: numbers paired with KTLYST-canonical countable nouns.
COUNT_RE = re.compile(
    r"\b(\d+(?:\+|\-\d+)?)\s+"
    r"(handoffs?|advisories|artifacts|folders?|teams?|input\s+types?|"
    r"engineers?|analysts?|advisories?|files?|alerts?|detections?|"
    r"rules?|sources?|incidents?)\b",
    re.IGNORECASE,
)

# Named sources whose attribution should be verified against the registry
# whenever they appear paired with a numeric claim.
NAMED_SOURCE_RE = re.compile(
    r"\b(CardinalOps|Mandiant|Verizon\s+DBIR|IBM(?:\s+Cost\s+of)?|Gartner|"
    r"Forrester|IDC|Ponemon|CrowdStrike(?:\s+Global)?|"
    r"Microsoft\s+Digital\s+Defense|IANS|Bain|SANS|Edgescan|Deepstrike|"
    r"Nagomi|Sapio|NDSS|Bessemer|YC(?:\s+W\d+)?)\b",
    re.IGNORECASE,
)

# Inline opt-out tags.
UNVALIDATED_RE = re.compile(
    r"\{\{(?:UNVALIDATED|NEEDS_PROOF|NEEDS_SOURCE)\}\}",
    re.IGNORECASE,
)
SKIP_MARKER = "stat-verify-skip"

# Strip code fences + inline code before claim extraction.
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

OPT_OUT_PROXIMITY = 80  # chars before/after a claim to scan for opt-out tag


# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------

def find_registry(start_path: Path) -> Path | None:
    """Locate canonical/stat-registry.json.

    Priority:
      1. STAT_REGISTRY_PATH env var (explicit override; if set and not a
         readable file, this also clamps the lookup — no fallback walk).
      2. Walk down from start_path's parents looking for the file.
    """
    env = os.environ.get("STAT_REGISTRY_PATH")
    if env is not None:
        p = Path(env)
        return p if p.is_file() else None

    here = start_path.resolve()
    if here.is_file():
        here = here.parent
    for parent in [here, *here.parents]:
        for candidate in parent.rglob("canonical/stat-registry.json"):
            sp = str(candidate)
            if any(x in sp for x in ("/.venv/", "/node_modules/", "/__pycache__/")):
                continue
            return candidate
    return None


def load_registry(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def build_lookup_indexes(registry: dict) -> tuple[set[str], list[tuple[str, str]]]:
    """
    Build two structures:
      - approved_numerics: a set of literal strings approved at any registry
        entry (e.g. {"21%", "90%", "13%", "$56M", "40 seconds"}).
      - phrasings: a list of (lowercased phrase, stat id) tuples for
        substring-based phrasing checks.
    """
    approved: set[str] = set()
    phrasings: list[tuple[str, str]] = []
    for stat in registry.get("stats", []):
        for n in stat.get("approved_numerics", []):
            approved.add(n.strip())
        for p in stat.get("canonical_phrasings", []):
            phrasings.append((p.lower().strip(), stat["id"]))
    return approved, phrasings


def normalize_numeric_token(token: str) -> set[str]:
    """Return the set of representations to look up for a single matched token."""
    t = token.strip()
    variants = {t}
    # "21%" <-> "21 %"
    if "%" in t:
        digits = t.replace("%", "").strip()
        variants.add(digits + "%")
        variants.add(digits + " %")
    # "$25-75K" <-> "$25K" "$75K" "$25" "$75"
    if t.startswith("$"):
        rest = t[1:]
        if "-" in rest:
            for piece in rest.split("-"):
                variants.add("$" + piece)
        variants.add(t.rstrip("K").rstrip("M").rstrip("B"))
    return variants


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def collect_content_strings_from_json(obj, deny_path: tuple = ()) -> list[str]:
    """Recursively collect strings under content keys."""
    out: list[str] = []

    def is_content_key(key: str) -> bool:
        if key in CONTENT_KEY_DENY_EXACT:
            return False
        kl = key.lower()
        return any(sub in kl for sub in CONTENT_KEY_SUBSTRINGS)

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if is_content_key(str(k)):
                    out.append(v)
            elif isinstance(v, (list, dict)):
                out.extend(
                    collect_content_strings_from_json(v, deny_path + (k,))
                    if not is_content_key(str(k))
                    else _collect_strings(v)
                )
    elif isinstance(obj, list):
        for item in obj:
            out.extend(collect_content_strings_from_json(item, deny_path))
    return out


def _collect_strings(obj) -> list[str]:
    """Collect all strings from a structure (used when we're inside a content key)."""
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_collect_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_collect_strings(item))
    return out


def strip_code(text: str) -> str:
    text = CODE_FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def extract_claims(text: str) -> list[tuple[str, int]]:
    """Return list of (token, start_index) for each numeric / source claim."""
    out: list[tuple[str, int]] = []

    for m in PERCENT_RE.finditer(text):
        out.append((m.group(0).strip(), m.start()))
    for m in DOLLAR_RE.finditer(text):
        out.append((m.group(0).strip(), m.start()))
    for m in MULTIPLIER_RE.finditer(text):
        out.append((m.group(0).strip(), m.start()))
    for m in DURATION_RE.finditer(text):
        token = m.group(0).strip()
        # Tolerate narrative durations: only flag when the number has a
        # quantity marker (+ or range) OR there's industry/benchmark context
        # within ~50 chars on either side.
        has_quantity_marker = "+" in token or "-" in m.group(1)
        if not has_quantity_marker:
            lo = max(0, m.start() - 50)
            hi = min(len(text), m.end() + 50)
            if not BENCHMARK_CONTEXT_RE.search(text[lo:hi]):
                continue
        out.append((token, m.start()))
    for m in COUNT_RE.finditer(text):
        out.append((m.group(0).strip(), m.start()))
    # Named sources only fire when paired with a numeric within ~80 chars.
    # "CrowdStrike artifact" (product name) is not a stat claim; "CrowdStrike
    # report says 74%" is.
    numeric_finder = re.compile(r"\d+(?:\.\d+)?(?:\s*%|\s*hours?|\s*days?|x\b)|\$\d+")
    for m in NAMED_SOURCE_RE.finditer(text):
        lo = max(0, m.start() - 80)
        hi = min(len(text), m.end() + 80)
        if numeric_finder.search(text[lo:hi]):
            out.append((m.group(0).strip(), m.start()))

    return out


def is_opted_out(text: str, claim_start: int) -> bool:
    """Check if a {{UNVALIDATED}}/{{NEEDS_PROOF}} tag is within OPT_OUT_PROXIMITY chars."""
    lo = max(0, claim_start - OPT_OUT_PROXIMITY)
    hi = min(len(text), claim_start + OPT_OUT_PROXIMITY)
    return bool(UNVALIDATED_RE.search(text[lo:hi]))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_claim(token: str, approved: set[str], phrasings: list[tuple[str, str]],
                 context: str) -> tuple[bool, str | None]:
    """
    Return (passed, matched_stat_id).

    A claim passes if:
      - Its normalized token is in the approved_numerics set, OR
      - The surrounding ~120-char context contains any canonical phrasing
        substring (lowercased).
    """
    for variant in normalize_numeric_token(token):
        if variant in approved:
            return True, None  # numeric-only match — no stat id needed

    ctx_lower = context.lower()
    for phrase, stat_id in phrasings:
        if phrase and phrase in ctx_lower:
            return True, stat_id

    return False, None


def lint_text(text: str, approved: set[str], phrasings: list[tuple[str, str]]) -> list[dict]:
    """Return list of violations (each is a dict with token, context, reason)."""
    if SKIP_MARKER in text:
        return []

    prose = strip_code(text)
    violations: list[dict] = []

    for token, start in extract_claims(prose):
        if is_opted_out(prose, start):
            continue
        lo = max(0, start - 60)
        hi = min(len(prose), start + len(token) + 60)
        context = prose[lo:hi]
        passed, _ = verify_claim(token, approved, phrasings, context)
        if not passed:
            violations.append({
                "token": token,
                "context": context.strip(),
                "reason": (
                    f"'{token}' not found in canonical/stat-registry.json "
                    f"approved_numerics or canonical_phrasings"
                ),
            })
    return violations


def lint_file(file_path: Path, registry: dict) -> list[dict]:
    """Lint a single file. Returns violations."""
    approved, phrasings = build_lookup_indexes(registry)

    try:
        raw = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return []

    if SKIP_MARKER in raw:
        return []

    if file_path.suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        content_strings = collect_content_strings_from_json(data)
    else:
        content_strings = [raw]

    violations: list[dict] = []
    for s in content_strings:
        violations.extend(lint_text(s, approved, phrasings))
    return violations


# ---------------------------------------------------------------------------
# Path scope
# ---------------------------------------------------------------------------

def is_in_scope(file_path: str) -> bool:
    fp = file_path.replace("\\", "/")
    base = os.path.basename(fp)
    if base in BUS_METADATA_BASENAMES:
        return False
    if any(base.startswith(p) for p in INGESTION_PREFIXES):
        return False
    # bus schemas are not content
    if "/agent-pipeline/schemas/" in fp:
        return False
    for pattern in IN_SCOPE_PATTERNS:
        if pattern.search(fp):
            return True
    return False


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(file_path: str, violations: list[dict]) -> str:
    lines = [f"stat-verify: {len(violations)} unverified claim(s) in {file_path}", ""]
    for v in violations:
        lines.append(f"  • {v['token']}")
        lines.append(f"    context: …{v['context']}…")
        lines.append(f"    {v['reason']}")
        lines.append("")
    lines.append("Fixes:")
    lines.append("  1. Match a canonical phrasing from q-ktlyst/canonical/stat-registry.json, OR")
    lines.append("  2. Tag the claim with {{UNVALIDATED}} inline (intentional unverified), OR")
    lines.append("  3. Add the claim to canonical first, then regenerate the registry.")
    lines.append("  4. File-level bypass: add  stat-verify-skip  anywhere in the file.")
    return "\n".join(lines)


def append_block_log(file_path: str, violations: list[dict], registry_dir: Path) -> None:
    """Append today's blocks to bus/{YYYY-MM-DD}/stat-verify-blocks.json."""
    today = _date.today().isoformat()
    # Best-effort guess at bus dir based on registry location.
    instance_root = registry_dir.parent  # canonical/ → instance root
    bus_dir = instance_root / ".q-system" / "agent-pipeline" / "bus" / today
    if not bus_dir.exists():
        return
    log_path = bus_dir / "stat-verify-blocks.json"
    entry = {
        "ts": _date.today().isoformat(),
        "file_path": file_path,
        "violations": violations,
    }
    existing: list = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []
    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2))


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def hook_mode() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not is_in_scope(file_path):
        sys.exit(0)

    fp = Path(file_path)
    if not fp.exists():
        sys.exit(0)

    registry_path = find_registry(fp)
    if registry_path is None:
        # No registry = fail-closed unless explicit bootstrap escape.
        # STAT_VERIFY_BOOTSTRAP=1 is the one-time escape during initial
        # registry creation. Without it, an in-scope content write with no
        # registry to check against is a configuration error, not a clean pass.
        if os.environ.get("STAT_VERIFY_BOOTSTRAP") == "1":
            print(
                "stat-verify: no canonical/stat-registry.json (bootstrap mode)",
                file=sys.stderr,
            )
            sys.exit(0)
        print(
            "stat-verify: no canonical/stat-registry.json found for "
            f"{file_path}. Create the registry or set STAT_VERIFY_BOOTSTRAP=1 "
            "for one-time bootstrap.",
            file=sys.stderr,
        )
        sys.exit(2)

    registry = load_registry(registry_path)
    violations = lint_file(fp, registry)
    if not violations:
        sys.exit(0)

    print(format_report(file_path, violations), file=sys.stderr)
    append_block_log(file_path, violations, registry_path.parent)
    sys.exit(2)


def cli_mode(file_path: str) -> None:
    fp = Path(file_path)
    if not fp.exists():
        print(f"stat-verify: {file_path} does not exist", file=sys.stderr)
        sys.exit(1)

    registry_path = find_registry(fp)
    if registry_path is None:
        print("stat-verify: no canonical/stat-registry.json found", file=sys.stderr)
        sys.exit(1)

    registry = load_registry(registry_path)
    violations = lint_file(fp, registry)
    if not violations:
        print(f"stat-verify: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


def self_test() -> None:
    """Run built-in fixtures. Exit 0 = all pass, 1 = failure."""
    fake_registry = {
        "stats": [
            {
                "id": "siem-attack-coverage",
                "approved_numerics": ["21%", "90%", "90%+", "79%"],
                "canonical_phrasings": [
                    "SIEMs cover 21% of ATT&CK",
                    "data for 90%",
                    "missing 79% of ATT&CK",
                ],
            },
            {
                "id": "translation-handoffs",
                "approved_numerics": ["42", "7", "6"],
                "canonical_phrasings": [
                    "42 handoffs",
                    "7 input types",
                    "6 teams",
                ],
            },
        ],
    }
    approved, phrasings = build_lookup_indexes(fake_registry)

    fixtures = [
        # (description, text, expected_violation_count)
        ("canonical phrasing passes",
         "SIEMs cover 21% of ATT&CK despite data for 90%.", 0),
        ("hallucinated 76% blocks",
         "SIEMs are missing 76% of ATT&CK coverage.", 1),
        ("UNVALIDATED inline opts out",
         "SIEMs are missing 76% of ATT&CK {{UNVALIDATED}}.", 0),
        ("skip marker opts out file",
         "stat-verify-skip\n\nSIEMs are missing 76% of ATT&CK.", 0),
        ("canonical handoff count passes",
         "42 handoffs across 6 teams.", 0),
        ("variant phrasing missing 79%",
         "missing 79% of ATT&CK coverage.", 0),
        ("code fence ignored",
         "```\nSIEMs are missing 76% of ATT&CK.\n```", 0),
        ("multiple violations in one string",
         "SIEMs miss 76% of ATT&CK and broke 99% of rules.", 2),
    ]

    failures = []
    for desc, text, expected in fixtures:
        # Apply skip marker check the same way lint_file does.
        if SKIP_MARKER in text:
            actual = 0
        else:
            actual = len(lint_text(text, approved, phrasings))
        status = "PASS" if actual == expected else "FAIL"
        print(f"  [{status}] {desc}: expected {expected}, got {actual}")
        if actual != expected:
            failures.append(desc)

    if failures:
        print(f"\nself-test: {len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print(f"\nself-test: all {len(fixtures)} fixtures passed")
    sys.exit(0)


def backtest_mode(target_dir: str) -> None:
    """Run verifier against every JSON file in target_dir tree. Report stats."""
    root = Path(target_dir)
    if not root.exists():
        print(f"stat-verify backtest: {target_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    registry_path = find_registry(root)
    if registry_path is None:
        print("stat-verify backtest: no canonical/stat-registry.json found", file=sys.stderr)
        sys.exit(1)
    registry = load_registry(registry_path)

    total_files = 0
    in_scope_files = 0
    files_with_violations = 0
    total_violations = 0
    file_reports: list[dict] = []

    for path in root.rglob("*.json"):
        total_files += 1
        if not is_in_scope(str(path)):
            continue
        in_scope_files += 1
        violations = lint_file(path, registry)
        if violations:
            files_with_violations += 1
            total_violations += len(violations)
            file_reports.append({
                "file": str(path),
                "violations": violations,
            })

    print(f"stat-verify backtest:")
    print(f"  scanned:        {total_files} JSON files")
    print(f"  in-scope:       {in_scope_files}")
    print(f"  with blocks:    {files_with_violations}")
    print(f"  total claims:   {total_violations}")
    if file_reports:
        print(f"\n--- detail ---\n")
        for r in file_reports:
            print(f"\n{r['file']}")
            for v in r["violations"]:
                print(f"  • {v['token']} :: …{v['context'][:80]}…")
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif sys.argv[1] == "--self-test":
        self_test()
    elif sys.argv[1] == "--backtest":
        if len(sys.argv) < 3:
            print("Usage: stat-verify.py --backtest <dir>", file=sys.stderr)
            sys.exit(1)
        backtest_mode(sys.argv[2])
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: stat-verify.py [<file_path> | --self-test | --backtest <dir>]", file=sys.stderr)
        sys.exit(1)
