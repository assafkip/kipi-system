#!/usr/bin/env python3
"""Kipi System Separation - Validation Harness.

Usage: python3 validate-separation.py <phase> [--verbose]
Runs all checks up to and including the specified phase.
Exit code 0 = all checks pass. Non-zero = failure.
"""

import collections
import json
import importlib.util
import os
import re
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(SCRIPT_DIR, "instance-registry.json")

# ANSI colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

pass_count = 0
fail_count = 0
warn_count = 0
errors = []


def check(description, result):
    global pass_count, fail_count
    if result:
        print(f"  {GREEN}PASS{NC} {description}")
        pass_count += 1
    else:
        print(f"  {RED}FAIL{NC} {description}")
        fail_count += 1
        errors.append(f"  - {description}")


def warn(description):
    global warn_count
    print(f"  {YELLOW}WARN{NC} {description}")
    warn_count += 1


def phase_header(num, title):
    print()
    print(f"{BLUE}=== Phase {num}: {title} ==={NC}")


def file_exists(path):
    return os.path.isfile(path)


# Model-allocation policy. Single source of truth: .claude/rules/model-allocation.md
# (this table and that rule must change together). Why this exists: audit 2026-07-01
# found the tier policy only as prose while frontmatters had drifted (haiku pinned
# 4-5, opus/sonnet stuck on 4-6 with 4-8/5 current) and nothing flagged it.
MODEL_TIERS = {
    "haiku": {"claude-haiku-4-5", "claude-haiku-4-5-20251001"},
    "sonnet": {"claude-sonnet-5"},
    "opus": {"claude-opus-4-8"},
}
AGENT_TIER = {
    "preflight": "haiku",
    "data-ingest": "haiku",
    "content-reviewer": "sonnet",
    "engagement-hitlist": "opus",
    "synthesizer": "opus",
}


def model_allocation_violations(claude_agents_dir):
    """Validate model: frontmatter in .claude/agents/*.md against the tier policy.

    Returns a list of violation strings (empty = compliant). Dir-parameterized so
    tests can run it against a corrupted temp copy instead of the live tree.
    """
    violations = []
    if not os.path.isdir(claude_agents_dir):
        return ["agents dir missing: " + claude_agents_dir]
    allowed_ids = set().union(*MODEL_TIERS.values())
    for f in sorted(os.listdir(claude_agents_dir)):
        if not f.endswith(".md"):
            continue
        name, model = None, None
        in_fm = False
        with open(os.path.join(claude_agents_dir, f)) as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if line == "---":
                    if in_fm:
                        break
                    in_fm = True
                    continue
                if in_fm:
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("model:"):
                        model = line.split(":", 1)[1].strip().strip('"')
        if model is None:
            violations.append(f"{f}: no model: in frontmatter")
            continue
        if model not in allowed_ids:
            violations.append(f"{f}: model '{model}' not in allowlist (deprecated or unknown)")
            continue
        expected_tier = AGENT_TIER.get(name or f[:-3])
        if expected_tier and model not in MODEL_TIERS[expected_tier]:
            violations.append(f"{f}: model '{model}' is not tier '{expected_tier}' (task-tier mismatch)")
    return violations


def dir_exists(path):
    return os.path.isdir(path)


def count_files(directory, pattern="*.md", exclude_prefixes=("_", "step-")):
    """Count files matching pattern, excluding files starting with given prefixes."""
    count = 0
    if not os.path.isdir(directory):
        return 0
    for f in os.listdir(directory):
        if not f.endswith(".md"):
            continue
        if any(f.startswith(p) for p in exclude_prefixes):
            continue
        count += 1
    return count


def grep_count(pattern, path, recursive=False):
    """Count files matching a grep pattern. Returns number of matching files."""
    try:
        cmd = ["grep", "-ril" if recursive else "-il", pattern, path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return len([l for l in result.stdout.strip().split("\n") if l])
        return 0
    except (subprocess.TimeoutExpired, Exception):
        return 0


def grep_count_multi(patterns, path):
    """Count files matching any of several patterns recursively."""
    pat = "|".join(patterns)
    return grep_count(pat, path, recursive=True)


def file_contains(filepath, pattern):
    """Check if a file contains a pattern."""
    try:
        with open(filepath) as f:
            return bool(re.search(pattern, f.read()))
    except (FileNotFoundError, Exception):
        return False


def python_parses(filepath):
    """Check if a Python file parses without syntax errors."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{filepath}').read())"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def load_registry():
    try:
        with open(REGISTRY) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"instances": []}


MARKDOWN_BOLD_LABEL_PATTERNS = (
    re.compile(
        r"^\s*(?:[-*]\s+)?\*\*(?P<label>[^*]+?):\*\*\s*(?P<value>.*?)\s*$"
    ),
    re.compile(
        r"^\s*(?:[-*]\s+)?\*\*(?P<label>[^*]+?)\*\*:\s*(?P<value>.*?)\s*$"
    ),
)
# The loosest pattern by far: any `label: value` line. It is the one that reads
# a Python type annotation (`source: dict[str, Any],`), a docstring parameter
# (`company: Company or project name...`) and a CSV prose cell as canonical
# records. See BARE_LABEL_EXEMPT_SUFFIXES.
BARE_LABEL_PATTERN = re.compile(
    r"^\s*(?:[-*]\s+)?(?P<label>[A-Za-z][A-Za-z0-9 _-]*):"
    r"\s*(?P<value>.*?)\s*$"
)
MARKDOWN_TABLE_PATTERN = re.compile(
    r"^\s*\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<value>[^|]*?)\s*\|"
)
SEMANTIC_FIELD_PATTERNS = (
    MARKDOWN_BOLD_LABEL_PATTERNS
    + (BARE_LABEL_PATTERN, MARKDOWN_TABLE_PATTERN)
)

# A DECLARATION is not an ASSERTION. In these languages `label: value` is
# syntax -- a type annotation, a parameter, an object key -- so the bare-label
# pattern reads the language itself as leaked facts. Measured 2026-07-27 over
# the propagated source set: 15 of the 34 gating findings, and not one was a
# fact. `source: str`, `source: dict[str, Any],`, `client: httpx.AsyncClient,`,
# `source: Optional[Path] = None`, `source: resolvedPath,` are the whole
# population.
#
# Only the BARE pattern is exempted. `**Client:** Acme` and `| Client | Acme |`
# inside a docstring or a template string are still read, because those are
# markdown a human wrote, not syntax the parser requires. Cost, stated rather
# than hidden: a roster written as an unquoted `client: Acme` line in a .py file
# is now invisible. In Python a dict literal keys it as `"client": "Acme"`,
# which this pattern never matched anyway (it requires a bare word before the
# colon), so the reachable loss is a comment.
#
# .yaml/.yml are deliberately NOT here: YAML is a real roster format, and
# `prospect: Acme Corp` in a data file is exactly the leak this gate exists for.
# YAML declarations are handled by SCHEMA_PRIMITIVE_VALUES instead, which is
# tight enough that a company name cannot pass through it.
CODE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx",
})
# A .csv is tabular data: one record per LINE, comma-delimited. A `label: value`
# inside a cell is prose, not a canonical record. All 4 CSV findings were the
# string "Visual DNA: Relentless motion... " in a design-reference table, read
# as `pricing` because a `$` appeared later in the same long cell.
DATA_SUFFIXES = frozenset({".csv", ".tsv"})
BARE_LABEL_EXEMPT_SUFFIXES = CODE_SUFFIXES | DATA_SUFFIXES

# YAML type declarations. Deliberately an exact-match allowlist of primitive
# type NAMES rather than a grammar: `prospect: string` is a schema, while
# `prospect: Acme` must still be a finding, and only an allowlist keeps that
# line sharp. Adding a company name here would be a visible, reviewable act.
SCHEMA_PRIMITIVE_VALUES = frozenset({
    "any", "array", "bool", "boolean", "date", "datetime", "dict", "float",
    "int", "integer", "list", "null", "number", "object", "str", "string",
})
YAML_SUFFIXES = frozenset({".yaml", ".yml"})

# A CITED DOCUMENT is not an identity. `Source: https://docs.anthropic.com/...`
# and `source: [rca-...md](../cole-gtm/...)` both name a document you can go
# open, which is the opposite of an instance fact -- the research-mode skill
# REQUIRES that line. A locator (URL, markdown link with a URL or a relative
# path, arXiv id, DOI) is the deterministic tell; a bare `Source: Acme Corp` has
# none and stays a finding.
CITATION_LOCATOR_RE = re.compile(
    r"https?://"
    r"|\]\(\s*(?:https?://|\.{0,2}/)"
    r"|\barxiv:\s*\d{4}\.\d{4,5}"
    r"|\bdoi:\s*10\.\d{4,9}/",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(
    # {{HANDLEBARS}}, this repo's primary placeholder form.
    r"\{\{\s*[A-Za-z][A-Za-z0-9_.-]*\s*\}\}"
    # ...and [Bracketed Title Case], the form the canonical TEMPLATES use:
    # `- **Source:** [Person] - [Date]` is the blank a debrief fills in, not a
    # source identity. Deliberately narrow -- capitalized words and spaces only
    # -- so a markdown link label (`[Anthropic - Reduce Hallucinations](...)`,
    # `[teract.ai](...)`, `[last30days]`) is untouched: those carry `-`, `.` or
    # lowercase and must keep flowing to the citation check.
    # Cost, stated rather than hidden: a real fact written as `Client: [Acme
    # Corp]` is now invisible. In this repo brackets mean "fill this in", and
    # the template-restoration tests depend on that reading.
    # The `(?!\()` is load-bearing: without it this eats the LABEL of a markdown
    # link, so `- **Client:** [Oriole Systems](https://oriole.example)` reduced
    # to a bare parenthetical and vanished entirely. The reach probe caught it.
    r"|\[[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\](?!\()"
)
# A value that is ENTIRELY a parenthetical is a template prompt to the author,
# not an assertion: `- **Gaps:** (what we still can't answer well)`. Requiring
# the parens to wrap the whole value is what keeps this narrow -- `Price: $6,500
# (annual)` is untouched because the currency sits outside them.
TEMPLATE_PROMPT_RE = re.compile(r"^\([^()]*\)$")
CURRENCY_RE = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d{1,2})?"
    r"|\b(?:USD|EUR|GBP)\s+\d[\d,]*(?:\.\d{1,2})?"
    r"|\b\d[\d,]*(?:\.\d{1,2})?\s+(?:USD|EUR|GBP)\b)",
    re.IGNORECASE,
)
DATE_PATTERNS = (
    (
        re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
        ("%Y-%m-%d",),
    ),
    (
        re.compile(r"\b\d{1,2}/\d{1,2}/20\d{2}\b"),
        ("%m/%d/%Y", "%d/%m/%Y"),
    ),
    (
        re.compile(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
            r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
            r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2},?\s+20\d{2}\b",
            re.IGNORECASE,
        ),
        ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"),
    ),
)
# `name` is deliberately ABSENT. Measured 2026-07-25: it produced 118 of 253
# blocking findings on this repo and not one was a client -- it is the key every
# YAML schema, agent frontmatter, Python type annotation and table header uses.
# A label that generic is not evidence of identity; the specific ones below are.
# Cost, stated rather than hidden: `- Name: Northwind` now falls through to
# `unclassified_populated_record`, a warning. Pinned in the reach probe.
IDENTITY_FIELDS = {
    "client",
    "client name",
    "company",
    "organization",
    "prospect",
    "prospect name",
}
PRICING_FIELDS = {"amount", "package price", "price", "pricing"}
SOURCE_FIELDS = {"potential source", "source"}
# `date` is deliberately ABSENT, for the same reason: 90 of 253 findings, all
# document metadata in frontmatter. A bare date is when a file was written, not
# when someone was spoken to. `call`, `meeting` and `discussion` carry that.
INTERACTION_FIELDS = {
    "call",
    "discussion",
    "interaction",
    "meeting",
}
GAP_FIELDS = {"case gap", "gaps", "proof gap", "proof gaps"}


def _synthetic_fixture(text, source_path):
    first_nonempty = next(
        (line.strip().lower() for line in text.splitlines() if line.strip()),
        "",
    )
    path_parts = (
        str(source_path).replace("\\", "/").split("/")
        if source_path is not None
        else []
    )
    return (
        first_nonempty == "fixture: synthetic"
        and path_parts[:5]
        == ["q-system", ".q-system", "tests", "separation", "fixtures"]
    )


# A markdown table SEPARATOR is not a record: without this, `|---|---|` parses
# as label `---`, value `---`. Both pipes are required. An earlier version made
# them optional, which matched a bare `---` -- a horizontal rule, a YAML
# document separator, a Setext underline -- and exempted whatever sat above it.
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$")

# There is deliberately no table-HEADER exemption. One was added on 2026-07-25
# to stop `| Name | Hex | RGB |` palette headers being read as client
# identities, and it was a hole bought for nothing: measured over the real
# propagated source set it suppressed 33 findings with it and 33 without, i.e.
# ZERO that removing `name` had not already suppressed, while making `Client`,
# `Price` and `Source` invisible in any header cell. A planted client roster
# returned a clean verdict from the armed gate while the same fact in bullet
# form aborted. A header cell is exactly where a real roster puts its label.


def _record_patterns_for(source_path):
    """The record grammars that apply to one file.

    A file's LANGUAGE decides which `label: value` lines are assertions. See
    BARE_LABEL_EXEMPT_SUFFIXES for why the bare pattern is dropped in code and
    tabular data.
    """
    if source_path is None:
        return SEMANTIC_FIELD_PATTERNS
    suffix = os.path.splitext(str(source_path))[1].lower()
    if suffix in BARE_LABEL_EXEMPT_SUFFIXES:
        return MARKDOWN_BOLD_LABEL_PATTERNS + (MARKDOWN_TABLE_PATTERN,)
    return SEMANTIC_FIELD_PATTERNS


def _semantic_record_lines(text, source_path=None):
    lines = text.splitlines()
    patterns = _record_patterns_for(source_path)
    for index, line in enumerate(lines):
        if TABLE_SEPARATOR_RE.match(line):
            continue
        match = next(
            (
                pattern.match(line)
                for pattern in patterns
                if pattern.match(line)
            ),
            None,
        )
        if match is None:
            continue
        value = match.group("value").strip()
        if (
            not value
            and index + 1 < len(lines)
            and lines[index + 1][:1].isspace()
        ):
            value = lines[index + 1].strip()
        yield index + 1, match.group("label"), value


# Bound chosen from a measured gap, not by taste. Strip the figures and count
# the words left:
#
#   asserted prices        `$5,000`                                        -> 0
#                          `Oriole Systems signed for $45,000 today.`      -> 5
#                          `Maren quoted $5,000 on July 24, 2026`          -> 4
#   operating-cost prose   `Do not exceed $2 total Apify spend per morning
#                           run across IG + TikTok combined.`              -> 13
#                          `Apify ~$0.50 per run (X/Twitter only). The
#                           canonical Reddit tooling ...`                  -> 14
#
# 5 and 13 leave a wide valley; 6 sits in it. If a future case lands between
# 6 and 12 the bound is the wrong instrument and should be replaced, not nudged.
PRICE_RESIDUE_WORD_LIMIT = 6


def _states_a_price(value):
    """True when the value IS a figure, not prose that mentions one.

    `**Package:** $5,000` and `$6,500 + $1,500/mo` assert a price. `Total Apify
    spend across Instagram + TikTok must not exceed $2 per run. Check ...` and
    `Gamma has a free tier ... Paid plans start around $10/month if you ...`
    mention an operating cost inside a sentence.

    The first version of this shipped as "currency without a pricing label is
    never a price", which read `**Package:** $5,000` as advisory and was caught
    by the fact-grammar boundary fixture -- a real loss of detector strength for
    exactly the leak this gate exists to catch. Dominance is the distinguisher:
    strip the figures and see whether a sentence is left.
    """
    residue = CURRENCY_RE.sub(" ", value)
    words = re.findall(r"[A-Za-z]{2,}", residue)
    return len(words) <= PRICE_RESIDUE_WORD_LIMIT


def _has_valid_date(value):
    for pattern, formats in DATE_PATTERNS:
        for match in pattern.finditer(value):
            if any(
                _date_parses(match.group(0), date_format)
                for date_format in formats
            ):
                return True
    return False


def _date_parses(value, date_format):
    try:
        datetime.strptime(value, date_format)
    except ValueError:
        return False
    return True


def semantic_leakage_findings(text, source_path=None):
    """Classify asserted Markdown records without relying on client names."""
    if not isinstance(text, str):
        raise TypeError("semantic leakage input must be text")
    if _synthetic_fixture(text, source_path):
        return []

    suffix = os.path.splitext(str(source_path))[1].lower() if source_path else ""

    findings = []
    for line_number, raw_label, value in _semantic_record_lines(
        text, source_path
    ):
        label = " ".join(raw_label.lower().split())
        asserted_value = PLACEHOLDER_RE.sub("", value).strip(" \t-:;,")
        if not asserted_value:
            continue
        if TEMPLATE_PROMPT_RE.match(asserted_value):
            continue
        if (
            suffix in YAML_SUFFIXES
            and asserted_value.lower() in SCHEMA_PRIMITIVE_VALUES
        ):
            continue

        fact_classes = []
        if label in IDENTITY_FIELDS:
            fact_classes.append("client_identity")
        if label == "relationship":
            fact_classes.append("relationship")
        if label in PRICING_FIELDS:
            fact_classes.append("pricing")
        elif CURRENCY_RE.search(asserted_value):
            fact_classes.append(
                "pricing"
                if _states_a_price(asserted_value)
                else "pricing_mention"
            )
        if label in SOURCE_FIELDS:
            if CITATION_LOCATOR_RE.search(asserted_value):
                fact_classes.append("cited_source")
            else:
                fact_classes.append(
                    "sourced_interaction"
                    if _has_valid_date(asserted_value)
                    else "source_identity"
                )
        if label in INTERACTION_FIELDS and _has_valid_date(asserted_value):
            fact_classes.append("dated_interaction")
        if label in GAP_FIELDS:
            fact_classes.append("case_proof_gap")
        if not fact_classes:
            # A populated canonical-style record with no known class is not
            # evidence of safety. Unknown schema must stop for ownership review.
            fact_classes.append("unclassified_populated_record")

        for fact_class in fact_classes:
            findings.append(
                {
                    "fact_class": fact_class,
                    "line": line_number,
                }
            )
    return findings


def _load_containment_targets():
    script_path = os.path.join(
        SCRIPT_DIR,
        "q-system",
        ".q-system",
        "scripts",
        "containment-targets.py",
    )
    spec = importlib.util.spec_from_file_location(
        "kipi_containment_targets",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load containment target enumerator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Prefixes that `kipi update` NEVER copies into an instance. Mirrors
# INSTANCE_OWNED_SUBTREES in kipi-update.sh (my-project, canonical, memory,
# output, .q-system/data, .q-system/agent-pipeline/bus), each rooted at
# q-system/. A fact in one of these cannot fan out to another instance, so
# Gate 1.3b -- which exists to catch fan-out -- has nothing to say about it.
#
# This is the same rationale the Full skeleton sweep already applies below
# (see the comment above `exclude_files`). Two gates in ONE file disagreeing
# about what propagates was the defect: the sweep excluded canonical/ on
# purpose while 1.3b scanned it, so 13 of 1.3b's 47 classified findings were
# facts that physically cannot reach another instance.
#
# Drift protection is a test, not a comment: test-gate-13b-scope.py asserts
# this tuple still matches kipi-update.sh's INSTANCE_OWNED_SUBTREES.
#
# q-system/research/ is here because it was MADE instance-owned in ASK-191, not
# because it always was: it shipped four kipi-system-specific notes to every
# instance until `research` was added to INSTANCE_OWNED_SUBTREES. The ASK-191
# issue text asserted research/ was already non-propagated; it was not, and
# excluding it here WITHOUT the kipi-update.sh change would have hidden a real
# fan-out rather than stopped it. The drift test is what keeps that honest.
#
# Repo-root paths outside q-system/ are NOT listed: only q-system/, plugins/
# and .claude/ propagate, but enumerating the root's non-propagated dirs here
# would be a second, drift-prone answer to a question kipi-update.sh owns.
NON_PROPAGATED_PREFIXES = (
    "q-system/my-project",
    "q-system/canonical",
    "q-system/memory",
    "q-system/output",
    "q-system/research",
    "q-system/.q-system/data",
    "q-system/.q-system/agent-pipeline/bus",
)

# `unclassified_populated_record` is the classifier's "I do not recognize this
# schema" bucket, not a finding. Measured 2026-07-27: 12,341 of 12,388 findings
# on this repo, including 418 lines of one MCP server source file and 236 lines
# of a command reference. It gates nothing because a detector that flags 418
# lines of generic engine source is not detecting a leak; it is reporting that
# markdown-ish `label: value` lines exist.
#
# It stays VISIBLE (counted, and listed under --verbose) rather than being
# deleted, because the day it drops to near-zero is the day the classifier
# learned the schema, and that is worth being able to see.
#
# A baseline/ratchet at 12,388 was proposed and rejected by the founder
# 2026-07-27: it would stamp the false alarms as accepted debt and bury the 47
# real findings inside them permanently.
#
# `pricing_mention` and `cited_source` join it for the reasons documented at
# their classification sites: a currency with no pricing label is an operating
# cost, and a Source: line carrying a public locator is the citation the
# research-mode skill requires. Both stay counted so a spike is still visible.
ADVISORY_FACT_CLASSES = frozenset({
    "pricing_mention",
    "cited_source",
    "unclassified_populated_record",
})


def _propagates(relative_path):
    """False for a path `kipi update` never copies into an instance."""
    normalized = relative_path.replace("\\", "/")
    return not any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in NON_PROPAGATED_PREFIXES
    )


def partition_semantic_violations(violations):
    """Split findings into (gating, advisory).

    Gating findings are classified facts on a path that actually propagates.
    Everything else is reported and does not fail the gate.
    """
    gating = []
    advisory = []
    for violation in violations:
        if violation["fact_class"] in ADVISORY_FACT_CLASSES:
            advisory.append(violation)
        elif not _propagates(violation["path"]):
            advisory.append(violation)
        else:
            gating.append(violation)
    return gating, advisory


def semantic_separation_violations(repo_root=SCRIPT_DIR):
    """Run semantic leakage checks over repository-derived generic targets."""
    root = os.path.abspath(os.fspath(repo_root))
    target_module = _load_containment_targets()
    manifest = target_module.enumerate_containment_targets(root)
    violations = []
    for relative_path in manifest["targets"]:
        text = target_module.read_indexed_target(
            root,
            relative_path,
            manifest["target_objects"][relative_path],
        )
        findings = semantic_leakage_findings(
            text,
            source_path=relative_path,
        )
        for finding in findings:
            violations.append(
                {
                    "fact_class": finding["fact_class"],
                    "line": finding["line"],
                    "path": relative_path,
                }
            )
    target_module.assert_index_unchanged(
        root,
        manifest["index_sha256"],
    )
    return violations


# ---------- PHASES ----------

def phase_0():
    phase_header(0, "Pre-execution checks")

    check("instance-registry.json exists", file_exists(REGISTRY))
    check("q-system/ directory exists in skeleton", dir_exists(os.path.join(SCRIPT_DIR, "q-system")))

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Instance path checks (CI environment)")
    else:
        registry = load_registry()
        for instance in registry.get("instances", []):
            path = instance.get("path", "")
            name = os.path.basename(path)
            check(f"Instance path exists: {name}", dir_exists(path))


def phase_1():
    phase_header(1, "Skeleton integrity")

    agents_dir = os.path.join(SCRIPT_DIR, "q-system", ".q-system", "agent-pipeline", "agents")
    scripts_dir = os.path.join(SCRIPT_DIR, "q-system", ".q-system")

    # --- GATE 1.1: Agent files ---
    print()
    print("  --- Gate 1.1: Agent files ---")

    agent_count = count_files(agents_dir)
    check(f"Agent count >= 30 (found: {agent_count})", agent_count >= 30)

    # Frontmatter on all numbered agents
    missing_frontmatter = 0
    if os.path.isdir(agents_dir):
        for f in sorted(os.listdir(agents_dir)):
            if not f[0].isdigit() or not f.endswith(".md"):
                continue
            filepath = os.path.join(agents_dir, f)
            with open(filepath) as fh:
                first_line = fh.readline().strip()
            if first_line != "---":
                missing_frontmatter += 1
                if verbose:
                    warn(f"Missing frontmatter: {f}")
    check(f"All numbered agents have YAML frontmatter ({missing_frontmatter} missing)", missing_frontmatter == 0)

    # Reads sections
    missing_rw = 0
    if os.path.isdir(agents_dir):
        for f in sorted(os.listdir(agents_dir)):
            if not f[0].isdigit() or not f.endswith(".md"):
                continue
            filepath = os.path.join(agents_dir, f)
            if not file_contains(filepath, r"## Reads?"):
                missing_rw += 1
                if verbose:
                    warn(f"Missing Reads section: {f}")
    check(f"All numbered agents have Reads section ({missing_rw} missing)", missing_rw == 0)

    # No KTLYST-specific terms
    ktlyst_hits = grep_count_multi(
        [r"KTLYST", r"ktlyst", r"q-ktlyst", r"re-breach", r"re\.breach", r"threat.intel.*team", r"CNS.*nervous"],
        agents_dir,
    )
    check(f"No KTLYST-specific terms in agent files ({ktlyst_hits} files)", ktlyst_hits == 0)

    # No hardcoded paths
    hardcoded = grep_count_multi([r"/Users/assafkip", r"q-ktlyst/"], agents_dir)
    check(f"No hardcoded paths in agent files ({hardcoded} files)", hardcoded == 0)

    # Key config files
    check("step-orchestrator.md exists", file_exists(os.path.join(agents_dir, "step-orchestrator.md")))
    check(
        "_cadence-config exists (.yaml or .md)",
        file_exists(os.path.join(agents_dir, "_cadence-config.yaml")) or file_exists(os.path.join(agents_dir, "_cadence-config.md")),
    )
    check("_auto-fail-checklist.md exists", file_exists(os.path.join(agents_dir, "_auto-fail-checklist.md")))

    # --- Gate 1.1b: Claude agent model allocation ---
    print()
    print("  --- Gate 1.1b: Model allocation (.claude/agents) ---")
    ma_violations = model_allocation_violations(os.path.join(SCRIPT_DIR, ".claude", "agents"))
    for v in ma_violations:
        warn(v)
    check(f"Agent model IDs match the allocation policy ({len(ma_violations)} violations)", not ma_violations)

    # --- GATE 1.2: Scripts ---
    print()
    print("  --- Gate 1.2: Scripts ---")

    # --- Gate 1.2a: Capability gate (silent-absence class) ---
    # One implementation, two callers: CI invokes capability-gate.py directly
    # (validate.yml); kipi check enforces it here. CAPABILITY_GATE_SKIP=1 is
    # set ONLY by the CI validate-separation step so the suite is not executed
    # twice per CI run (finding-15, prd-silent-absence-capability-gate).
    # The skip is honored only from a caller that PROVES it runs the gate
    # elsewhere (CI runs it as its own step; kipi check just ran the instance
    # suite). A bare ambient CAPABILITY_GATE_SKIP=1 in a founder shell would
    # otherwise permanently and silently disable the gate (codex adversarial,
    # sag-callsite) — the exact bypass surface this PRD closes.
    _skip_proof = (os.environ.get("GITHUB_ACTIONS") == "true"
                   or os.environ.get("KIPI_GATE_SKIP_CALLER") == "kipi-check-instance")
    if os.environ.get("CAPABILITY_GATE_SKIP") == "1" and _skip_proof:
        print("  --- Gate 1.2a: capability gate SKIPPED (CAPABILITY_GATE_SKIP=1; caller runs it directly) ---")
    else:
        gate_script = os.path.join(SCRIPT_DIR, "q-system", ".q-system", "scripts", "capability-gate.py")
        gate_run = subprocess.run([sys.executable, gate_script, "--repo-root", SCRIPT_DIR],
                                  capture_output=True, text=True)
        check("capability gate: declared-vs-actual diff + full test run exits 0",
              gate_run.returncode == 0)
        if gate_run.returncode != 0:
            print("\n".join(("    " + l) for l in
                            (gate_run.stdout + gate_run.stderr).splitlines()[-15:]))

    # --- Gate 1.2b: Memory hygiene sweep (ADVISORY, can never fail this gate) ---
    # memory-lint.py reads the auto-memory corpus, which lives OUTSIDE the repo
    # (~/.claude/projects/<slug>/memory/). Deliberately warn-only, in both
    # directions: a stale or unindexed memory is never a reason to refuse a repo
    # validation, and the corpus predates the as_of/status convention entirely --
    # 73 of 73 files carry neither field, so a failing gate here would be red on
    # its whole population from the first run and get switched off.
    # CLAUDE_PROJECT_DIR is pinned so the sweep resolves the same corpus whatever
    # directory kipi check was invoked from (two derivations of one path is how a
    # sweep and a hook end up reading different corpora and both reporting clean).
    print()
    print("  --- Gate 1.2b: Memory hygiene (advisory) ---")
    memory_lint = os.path.join(scripts_dir, "scripts", "memory-lint.py")
    if not file_exists(memory_lint):
        warn("Gate 1.2b: memory-lint.py missing")
    else:
        lint_env = dict(os.environ, CLAUDE_PROJECT_DIR=SCRIPT_DIR)
        lint_run = subprocess.run([sys.executable, memory_lint],
                                  capture_output=True, text=True, env=lint_env)
        summary = next((l for l in lint_run.stdout.splitlines()
                        if l.startswith("structural:")), None)
        if summary is None:
            warn(f"Gate 1.2b: memory-lint produced no summary (exit {lint_run.returncode})")
        elif summary.split()[1] != "0":
            warn(f"Gate 1.2b: memory hygiene -- {summary}. Run: "
                 f"python3 q-system/.q-system/scripts/memory-lint.py")
        else:
            check(f"memory hygiene sweep clean ({summary})", True)

    for script in ["audit-morning.py", "verify-schedule.py", "token-guard.py"]:
        check(f"{script} exists", file_exists(os.path.join(scripts_dir, script)))

    # Check for ported scripts (may be in scripts/ subdir)
    scan_draft = file_exists(os.path.join(scripts_dir, "scripts", "scan-draft.py")) or file_exists(os.path.join(scripts_dir, "scan-draft.py"))
    check("scan-draft.py exists (anti-AI scanner)", scan_draft)

    check("verify-bus.py exists", file_exists(os.path.join(scripts_dir, "verify-bus.py")) or file_exists(os.path.join(scripts_dir, "scripts", "verify-bus.py")))
    check("verify-orchestrator.py exists", file_exists(os.path.join(scripts_dir, "verify-orchestrator.py")) or file_exists(os.path.join(scripts_dir, "scripts", "verify-orchestrator.py")))

    build_sched = os.path.join(SCRIPT_DIR, "q-system", "marketing", "templates", "build-schedule.py")
    check("build-schedule.py exists and is non-empty", file_exists(build_sched) and os.path.getsize(build_sched) > 0)

    # No KTLYST in scripts. Exclude the lessons-validator denylist machinery
    # (the leak-detector and its test): a denylist must name the tokens it
    # blocks, so it legitimately contains them. Same self-reference exemption
    # this validator grants itself in the full sweep below.
    script_exclude = ("lessons-validator", "lessons_scrub", "lessons-scrub")
    script_hits = 0
    for root, dirs, files in os.walk(scripts_dir):
        for f in files:
            if any(ex in f for ex in script_exclude):
                continue
            if f.endswith(".py") or f.endswith(".sh"):
                filepath = os.path.join(root, f)
                if file_contains(filepath, r"KTLYST|ktlyst|q-ktlyst"):
                    script_hits += 1
    check(f"No KTLYST references in scripts ({script_hits} files)", script_hits == 0)

    # --- GATE 1.3: Canonical templates ---
    print()
    print("  --- Gate 1.3: Canonical templates ---")

    canonical = os.path.join(SCRIPT_DIR, "q-system", "canonical")
    for tmpl in ["discovery.md", "objections.md", "talk-tracks.md", "decisions.md",
                 "engagement-playbook.md", "lead-lifecycle-rules.md", "market-intelligence.md",
                 "pricing-framework.md", "verticals.md"]:
        check(f"canonical/{tmpl} exists", file_exists(os.path.join(canonical, tmpl)))

    my_project = os.path.join(SCRIPT_DIR, "q-system", "my-project")
    check("my-project/founder-profile.md exists", file_exists(os.path.join(my_project, "founder-profile.md")))

    profile_path = os.path.join(my_project, "founder-profile.md")
    check("founder-profile.md contains {{SETUP_NEEDED}}", file_contains(profile_path, r"SETUP_NEEDED"))

    canonical_ktlyst = grep_count_multi([r"KTLYST", r"ktlyst", r"Assaf", r"CISO.*pain", r"re-breach"], canonical)
    check(f"No KTLYST content in canonical templates ({canonical_ktlyst} files)", canonical_ktlyst == 0)

    # --- GATE 1.3b: Repository-derived semantic containment ---
    print()
    print("  --- Gate 1.3b: Semantic containment ---")
    try:
        semantic_violations = semantic_separation_violations(SCRIPT_DIR)
    except Exception as exc:
        semantic_violations = None
        warn(f"Semantic containment scope blocked: {exc}")
    if semantic_violations is None:
        check(
            "Repository-derived generic targets contain no semantic instance "
            "facts (scope unavailable)",
            False,
        )
    else:
        gating, advisory = partition_semantic_violations(semantic_violations)
        if verbose:
            for violation in gating:
                warn("{path}:{line}: {fact_class}".format(**violation))
        # Advisory findings are counted always and listed only under --verbose:
        # there are ~12k of them and dumping the list drowns the gating ones.
        advisory_classes = collections.Counter(
            v["fact_class"] for v in advisory
        )
        print(
            "        advisory (non-gating): "
            + (
                ", ".join(
                    f"{cls}={count}"
                    for cls, count in sorted(advisory_classes.items())
                )
                or "none"
            )
        )
        check(
            "Repository-derived generic targets contain no semantic instance "
            f"facts ({len(gating)} gating, {len(advisory)} advisory)",
            gating == [],
        )

    # --- GATE 1.4: Voice skill framework ---
    print()
    print("  --- Gate 1.4: Voice skill ---")

    voice = os.path.join(SCRIPT_DIR, "plugins", "kipi-core", "skills", "founder-voice")
    check("founder-voice SKILL.md exists", file_exists(os.path.join(voice, "SKILL.md")))
    check("voice-dna.md template exists", file_exists(os.path.join(voice, "references", "voice-dna.md")))
    check("writing-samples.md template exists", file_exists(os.path.join(voice, "references", "writing-samples.md")))

    voice_ktlyst = grep_count_multi(
        [r"Assaf", r"KTLYST", r"threat.intel.*Google", r"threat.intel.*Meta"],
        voice,
    )
    check(f"No Assaf-specific content in voice framework ({voice_ktlyst} files)", voice_ktlyst == 0)

    research = os.path.join(SCRIPT_DIR, "plugins", "kipi-core", "skills", "research-mode")
    check("research-mode SKILL.md exists", file_exists(os.path.join(research, "SKILL.md")))
    check("research-mode command exists", file_exists(os.path.join(research, "commands", "q-research.md")))

    # --- GATE 1.5: CLAUDE.md ---
    print()
    print("  --- Gate 1.5: CLAUDE.md ---")

    check("Root CLAUDE.md exists", file_exists(os.path.join(SCRIPT_DIR, "CLAUDE.md")))
    check("q-system/CLAUDE.md exists", file_exists(os.path.join(SCRIPT_DIR, "q-system", "CLAUDE.md")))

    q_claude = os.path.join(SCRIPT_DIR, "q-system", "CLAUDE.md")
    try:
        with open(q_claude) as f:
            content = f.read()
        claude_ktlyst = len(re.findall(r"KTLYST|ktlyst|Assaf|re-breach|CISO.*pain", content, re.IGNORECASE))
    except FileNotFoundError:
        claude_ktlyst = 0
    check(f"No KTLYST references in q-system/CLAUDE.md ({claude_ktlyst} hits)", claude_ktlyst == 0)

    # --- GATE 1.6: build-schedule.py ---
    print()
    print("  --- Gate 1.6: build-schedule.py ---")

    if file_exists(build_sched):
        check("build-schedule.py has verification gate", file_contains(build_sched, r"verify.schedule"))

    # --- GATE 1.7: plugin version drift ---
    #
    # The plugin CACHE is what actually loads, and it is keyed by the version in
    # plugins/<name>/.claude-plugin/plugin.json. Editing any file under a plugin
    # WITHOUT bumping that version is a silent no-op fleet-wide: the marketplace
    # gets the change, every session keeps running the cached old copy, and the
    # edit is text in a file rather than wired behaviour.
    #
    # Hit twice on 2026-07-26 -- a kipi-dsse scope_hook fix and prd-os -- which is
    # the general form of the 2026-06-20 load-path scar. This is the deterministic
    # checker for it (no-prompt-only rule).
    print()
    print("  --- Gate 1.7: Plugin version drift ---")

    # DELEGATES to q-system/.q-system/scripts/plugin-version-bump-check.py rather
    # than reimplementing it. That script already existed (commit c494b85,
    # sp-9886486d) and is wired into lefthook.yml as a pre-commit hook; this gate
    # originally shipped a second, independent implementation of the same rule --
    # the exact "one question answered twice" defect the updater consolidation
    # was about. One implementation, two call sites.
    #
    # The two call sites are not redundant. lefthook runs it `--staged` at commit
    # time and `git commit --no-verify` skips it entirely, which is how this
    # repo accumulated the drift in the first place. Running it here against the
    # published ref catches what --no-verify let through.
    checker = os.path.join(
        SCRIPT_DIR, "q-system", ".q-system", "scripts", "plugin-version-bump-check.py"
    )
    if not file_exists(checker):
        warn("Gate 1.7: plugin-version-bump-check.py missing")
    elif subprocess.run(["git", "-C", SCRIPT_DIR, "rev-parse", "--verify", "-q",
                         "origin/main"], capture_output=True).returncode != 0:
        warn("Gate 1.7 skipped: no origin/main to compare against")
    else:
        result = subprocess.run(
            ["python3", checker, "--against", "origin/main"],
            capture_output=True, text=True, cwd=SCRIPT_DIR,
        )
        check("No plugin changed since origin/main without a version bump",
              result.returncode == 0)
        for line in (result.stderr or "").strip().splitlines()[:6]:
            print(f"        {line}")

    # --- Full skeleton sweep ---
    print()
    print("  --- Full skeleton sweep ---")

    q_system_dir = os.path.join(SCRIPT_DIR, "q-system")
    full_sweep = 0
    # canonical/ files that reference the fleet by name on purpose. canonical/ is
    # NOT propagated by kipi update -- kipi-update.sh rsync excludes /canonical/,
    # /my-project/, /memory/, /output/ -- so these refs are instance-local and
    # never ship to another instance (same rationale as lessons-validator/
    # instance-registry): ai-index-2026-comparison (fleet analysis), fleet-map
    # (fleet inventory), decisions (decision log).
    exclude_files = {"PHASE-0-AUDIT", "EXECUTION-PLAN", "validate-separation", "instance-registry", "lessons-validator", "lessons_scrub", "lessons-scrub", "ai-index-2026-comparison", "fleet-map", "decisions",
                     "tripwire-terms"}  # the push tripwire's roster holds the terms it blocks, by design (kipi-push-upstream.sh, PRD B)
    exclude_dirs = {"output", ".obsidian", "memory"}
    for root, dirs, files in os.walk(q_system_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if any(ex in f for ex in exclude_files):
                continue
            filepath = os.path.join(root, f)
            if file_contains(filepath, r"KTLYST|ktlyst|q-ktlyst|/Users/assafkip"):
                full_sweep += 1
    check(f"Full skeleton sweep: zero KTLYST/hardcoded refs ({full_sweep} files)", full_sweep == 0)

    # Skill -> hook orphan audit (skill-hook-pairing rule). Runs the plugin-bundled,
    # manifest-gated standalone audit against the skeleton: a lint/gate script authored but
    # never wired into a hook config -> FAIL. Advisory (WARN) until a skeleton manifest exists.
    audit = os.path.join(SCRIPT_DIR, "plugins", "kipi-core", "scripts", "skill-hook-audit.py")
    if not file_exists(audit):
        warn("Skill-hook audit: plugins/kipi-core/scripts/skill-hook-audit.py missing")
    else:
        result = subprocess.run([sys.executable, audit, SCRIPT_DIR], capture_output=True, text=True)
        audit_out = (result.stdout + result.stderr).strip()
        if "not onboarded" in audit_out:
            warn("Skill-hook audit: skeleton has no manifest yet (advisory)")
        else:
            check("Skill-hook audit: no orphaned skill-hooks", result.returncode == 0)
            if result.returncode != 0 and audit_out:
                errors.append(audit_out)

    # ENFORCED-claim audit (ASK-965). The sibling question to the one above: that
    # audit asks whether a SKILL's hook is wired, this asks whether a RULE's
    # (ENFORCED marker names an executable that exists, is wired in the config it
    # names, is not neutered there, and has a test pinning the claim.
    #
    # Wired in three places on purpose, and they catch different things:
    #   PostToolUse  feedback on the write that just landed
    #   lefthook     the commit, which is what makes the invariant persistent
    #   here         the whole tree, which is what a fleet-wide `check` is for --
    #                it also sees rule files that arrived by rsync from the
    #                skeleton, which neither of the other two ever mediates.
    claim_lint = os.path.join(SCRIPT_DIR, "q-system", ".q-system", "scripts",
                              "enforced-claim-lint.py")
    # A MISSING GATE IS A FAILURE, NOT A WARNING (codex-adversarial review of
    # 536ab18f, major). This integration exists to catch rule files delivered
    # through paths no hook mediates; warning when the gate itself is absent lets
    # `kipi check` exit 0 in exactly the situation it was added for.
    if not file_exists(claim_lint):
        check("Enforced-claim audit: enforced-claim-lint.py present", False)
        errors.append("q-system/.q-system/scripts/enforced-claim-lint.py is missing, "
                      "so no ENFORCED claim in .claude/rules was checked at all.")
    else:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=SCRIPT_DIR)
        result = subprocess.run([sys.executable, claim_lint, "--all"],
                                capture_output=True, text=True, env=env)
        claim_out = (result.stdout + result.stderr).strip()
        check("Enforced-claim audit: every (ENFORCED marker is substantiated or baselined",
              result.returncode == 0)
        if result.returncode != 0 and claim_out:
            errors.append(claim_out)
        elif claim_out:
            # The remaining baselined debt, surfaced on green runs too. Debt that
            # stops being mentioned stops being debt and becomes furniture.
            print(f"  {claim_out.splitlines()[-1]}")


def phase_2():
    phase_header(2, "KTLYST_strategy subtree")

    ktlyst = "/Users/assafkip/Desktop/KTLYST_strategy"

    if os.getenv('CI') == 'true' or not dir_exists(ktlyst):
        print(f"  {YELLOW}SKIP{NC} KTLYST_strategy checks (not available)")
        return

    check("KTLYST has q-system/ directory (subtree)", dir_exists(os.path.join(ktlyst, "q-system")))
    check("KTLYST has q-ktlyst/ directory (instance content)", dir_exists(os.path.join(ktlyst, "q-ktlyst")))

    # Try multiple path layouts: archive overlay (flat), subtree (nested), legacy
    k_agents_paths = [
        os.path.join(ktlyst, "q-system", ".q-system", "agent-pipeline", "agents"),
        os.path.join(ktlyst, "q-system", "q-system", ".q-system", "agent-pipeline", "agents"),
        os.path.join(ktlyst, "q-system", "q-system", "agent-pipeline", "agents"),
    ]
    k_agents_dir = next((p for p in k_agents_paths if dir_exists(p)), None)
    if k_agents_dir and dir_exists(k_agents_dir):
        k_count = count_files(k_agents_dir)
        check(f"KTLYST q-system/ subtree has agents ({k_count})", k_count >= 30)
    else:
        check("KTLYST q-system/ subtree agent directory exists", False)

    check(
        "KTLYST instance content in q-ktlyst/ (canonical or my-project)",
        dir_exists(os.path.join(ktlyst, "q-ktlyst", "canonical")) or dir_exists(os.path.join(ktlyst, "q-ktlyst", "my-project")),
    )

    check("KTLYST root CLAUDE.md exists", file_exists(os.path.join(ktlyst, "CLAUDE.md")))

    claude_path = os.path.join(ktlyst, "CLAUDE.md")
    if file_exists(claude_path):
        check("KTLYST CLAUDE.md imports skeleton", file_contains(claude_path, r"@q-system|q-system/CLAUDE\.md"))
        check("KTLYST CLAUDE.md imports instance rules", file_contains(claude_path, r"@q-ktlyst|q-ktlyst/CLAUDE\.md"))

    # No plugin dependency
    plugin_refs = 0
    for cf in [
        os.path.join(ktlyst, "CLAUDE.md"),
        os.path.join(ktlyst, ".claude", "settings.json"),
        os.path.join(ktlyst, ".claude", "settings.local.json"),
        os.path.join(ktlyst, ".mcp.json"),
        os.path.join(ktlyst, "q-ktlyst", ".q-system", "commands.md"),
        os.path.join(ktlyst, "q-ktlyst", ".q-system", "preflight.md"),
    ]:
        if file_exists(cf):
            try:
                with open(cf) as f:
                    plugin_refs += f.read().count("kipi-pipeline-plugin")
            except Exception:
                pass

    if plugin_refs == 0:
        check(f"No kipi-pipeline-plugin references in KTLYST ({plugin_refs})", True)
    else:
        warn(f"kipi-pipeline-plugin references in KTLYST ({plugin_refs}) - clean in Phase 3")

    # Scripts parse (try flat and nested paths)
    k_scripts_paths = [
        os.path.join(ktlyst, "q-system", ".q-system"),
        os.path.join(ktlyst, "q-system", "q-system", ".q-system"),
    ]
    k_scripts = next((p for p in k_scripts_paths if dir_exists(p)), k_scripts_paths[0])
    audit_path = os.path.join(k_scripts, "audit-morning.py")
    if file_exists(audit_path):
        check("Subtree audit-morning.py parses without errors", python_parses(audit_path))

    scan_path = os.path.join(k_scripts, "scripts", "scan-draft.py")
    if file_exists(scan_path):
        check("Subtree scan-draft.py parses without errors", python_parses(scan_path))


def phase_3():
    phase_header(3, "Plugin elimination")

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Plugin elimination checks (CI environment)")
        return

    check("kipi-pipeline-plugin directory removed", not dir_exists("/Users/assafkip/Desktop/kipi-pipeline-plugin"))
    check("q-founder-os directory removed", not dir_exists("/Users/assafkip/Desktop/q-founder-os"))

    # Global config references
    global_plugin = 0
    home = os.path.expanduser("~")
    for cf in [
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.local.json"),
        os.path.join(home, ".claude", "plugins", "known_marketplaces.json"),
    ]:
        if file_exists(cf):
            try:
                with open(cf) as f:
                    global_plugin += f.read().count("kipi-pipeline-plugin")
            except Exception:
                pass
    check(f"No plugin references in Claude Code config ({global_plugin})", global_plugin == 0)

    check("Plugin cache directory removed", not dir_exists(os.path.join(home, ".claude", "plugins", "cache", "kipi-local")))


def phase_4():
    phase_header(4, "All instances")

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Instance checks (CI environment)")
        return

    registry = load_registry()
    for instance in registry.get("instances", []):
        name = instance.get("name", "unknown")
        path = instance.get("path", "")
        # `or`, not .get default: an explicit null in the registry bypasses the default
        prefix = instance.get("subtree_prefix") or "q-system"
        itype = instance.get("type", "subtree")

        # Skip archived/merged instances
        if instance.get("status"):
            print()
            print(f"  --- {name} ({itype}) ---")
            print(f"  {YELLOW}SKIP{NC} {name}: {instance['status']}")
            continue

        # Standalone repos have no skeleton subtree; nothing to validate here
        # (a null subtree_prefix used to crash this phase on os.path.join)
        if itype == "standalone" or not instance.get("subtree_prefix"):
            print()
            print(f"  --- {name} ({itype}) ---")
            print(f"  {YELLOW}SKIP{NC} {name}: standalone (not skeleton-managed)")
            continue

        print()
        print(f"  --- {name} ({itype}) ---")

        if not instance.get("skip_agent_check"):
            check(f"{name}: {prefix}/ directory exists", dir_exists(os.path.join(path, prefix)))
        else:
            prefix_exists = dir_exists(os.path.join(path, prefix))
            if not prefix_exists:
                print(f"  {YELLOW}SKIP{NC} {name}: {prefix}/ not present ({instance.get('note', 'optional')})")
            else:
                check(f"{name}: {prefix}/ directory exists", True)

        if itype == "direct-clone":
            agent_path = os.path.join(path, prefix, ".q-system", "agent-pipeline", "agents")
        else:
            agent_path = os.path.join(path, prefix, "q-system", ".q-system", "agent-pipeline", "agents")
            if not dir_exists(agent_path):
                agent_path = os.path.join(path, prefix, "q-system", "agent-pipeline", "agents")
            if not dir_exists(agent_path):
                agent_path = os.path.join(path, prefix, ".q-system", "agent-pipeline", "agents")

        if instance.get("skip_agent_check"):
            check(f"{name}: has agents (skipped - {instance.get('note', 'no pipeline')})", True)
        elif dir_exists(agent_path):
            i_count = count_files(agent_path)
            threshold = 15 if itype == "direct-clone" else 30
            label = f"{i_count}, direct-clone - relaxed threshold" if itype == "direct-clone" else str(i_count)
            check(f"{name}: has agents ({label})", i_count >= threshold)
        else:
            check(f"{name}: agent directory exists at expected path", False)

        check(f"{name}: root CLAUDE.md exists", file_exists(os.path.join(path, "CLAUDE.md")))

        claude_path = os.path.join(path, "CLAUDE.md")
        if file_exists(claude_path):
            check(f"{name}: CLAUDE.md imports skeleton", file_contains(claude_path, r"@q-system"))


def phase_5():
    phase_header(5, "Propagation and documentation")

    for script in ["kipi-update.sh", "kipi-new-instance.sh", "kipi-push-upstream.sh"]:
        path = os.path.join(SCRIPT_DIR, script)
        check(f"{script} exists and is executable", file_exists(path) and os.access(path, os.X_OK))

    for doc in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        check(f"Documentation: {doc} exists", file_exists(os.path.join(SCRIPT_DIR, doc)))

    # No KTLYST in docs
    doc_ktlyst = 0
    for doc in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        if file_contains(os.path.join(SCRIPT_DIR, doc), r"KTLYST|ktlyst"):
            doc_ktlyst += 1
    check(f"No KTLYST references in documentation ({doc_ktlyst})", doc_ktlyst == 0)


def main():
    global verbose

    phase = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    verbose = "--verbose" in sys.argv

    phases = [phase_0, phase_1, phase_2, phase_3, phase_4, phase_5]
    for i, func in enumerate(phases):
        if phase >= i:
            func()

    # Summary
    print()
    print(f"{BLUE}=============================={NC}")
    print(f"{BLUE}  VALIDATION SUMMARY (Phase {phase}){NC}")
    print(f"{BLUE}=============================={NC}")
    print(f"  {GREEN}PASS: {pass_count}{NC}")
    print(f"  {RED}FAIL: {fail_count}{NC}")
    print(f"  {YELLOW}WARN: {warn_count}{NC}")

    if fail_count > 0:
        print()
        print(f"{RED}FAILURES:{NC}")
        for e in errors:
            print(e)
        print()
        print(f"{RED}GATE FAILED. Do not proceed to Phase {phase + 1}.{NC}")
        sys.exit(1)
    else:
        print()
        print(f"{GREEN}ALL CHECKS PASSED. Phase {phase} gate is GREEN.{NC}")
        sys.exit(0)


if __name__ == "__main__":
    main()
