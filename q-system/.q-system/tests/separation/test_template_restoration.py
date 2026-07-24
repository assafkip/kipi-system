import hashlib
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DISCOVERY = REPO_ROOT / "q-system/canonical/discovery.md"
PRICING = REPO_ROOT / "q-system/canonical/pricing-framework.md"
EXPORT_SOURCE_COMMIT = "6ae07f98af7a4745265292920ee3bad875c4edff"
EXPORT_CLOSE_COMMIT = "90f4ee3d57e1cb8191a51b88208697a5a54f76b4"
DISCOVERY_TEMPLATE_COMMIT = "dbf5e5878ae517d7ab36fb6cc096f756236e95e3"
PRICING_TEMPLATE_COMMIT = "d5e231ff03d057f7cbb1a552b8b84ca6481e5a46"
EXPORTED_HASHES = {
    "q-system/canonical/discovery.md": (
        "208a5cc8d886a8376afb159b3b768650b2d42b0fa28ec0cd7e1d85374ea5e470"
    ),
    "q-system/canonical/pricing-framework.md": (
        "c763957f17f29c2a54098dddd9d92f6db6635f7996d5eeaf003047f7d6caa3f1"
    ),
}
DISCOVERY_TEMPLATE = """# Discovery

> Questions asked by prospects, investors, and partners. Answers refined over time.

## Format <!-- pin -->

```
### Q: "[Question as asked]"
- **Asked by:** [persona type]
- **Context:** (why they asked)
- **Best answer:** (current best response)
- **Gaps:** (what we still can't answer well)
- **Source:** [Person] - [Date]
```

## Questions & Answers

(populated through debriefs and calibration)
"""
PRICING_TEMPLATE = """# Pricing Framework

> Pricing model, packaging tiers, and budget conversation guidance. Updated through debriefs and calibration.

## Format <!-- pin -->

```
### Tier: [Tier Name]
- **Target:** [buyer persona / company size]
- **Price point:** [range or specific]
- **Packaging:** [what's included]
- **Proof points:** [why this price works]
- **Objection handling:** [common pushback at this tier]
- **Source:** [Person] - [Date]
```

## Pricing Tiers <!-- pin -->

(populated through debriefs and calibration)

## Budget Signals from Conversations

(captured from debrief pricing/packaging analysis)

## Competitive Pricing Intel

(what prospects compare us to, price-wise)
"""


def git_object_exists(commit_sha):
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0


def git_is_ancestor(ancestor, descendant):
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0


def git_file(commit_sha, path):
    return subprocess.run(
        ["git", "show", f"{commit_sha}:{path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def test_export_receipt_precedes_source_restoration():
    assert git_object_exists(EXPORT_SOURCE_COMMIT)
    assert git_object_exists(EXPORT_CLOSE_COMMIT)
    assert git_is_ancestor(EXPORT_SOURCE_COMMIT, EXPORT_CLOSE_COMMIT)
    assert git_is_ancestor(EXPORT_CLOSE_COMMIT, "HEAD")

    for path, expected_hash in EXPORTED_HASHES.items():
        exported = git_file(EXPORT_SOURCE_COMMIT, path)
        assert hashlib.sha256(exported).hexdigest() == expected_hash


def test_discovery_is_the_existing_generic_template():
    grounded = git_file(
        DISCOVERY_TEMPLATE_COMMIT,
        "q-system/canonical/discovery.md",
    ).decode()
    assert grounded == DISCOVERY_TEMPLATE
    assert DISCOVERY.read_text(encoding="utf-8") == DISCOVERY_TEMPLATE


def test_pricing_is_the_existing_generic_template():
    grounded = git_file(
        PRICING_TEMPLATE_COMMIT,
        "q-system/canonical/pricing-framework.md",
    ).decode()
    assert grounded == PRICING_TEMPLATE
    assert PRICING.read_text(encoding="utf-8") == PRICING_TEMPLATE


def test_exported_instance_facts_are_absent_from_generic_templates():
    templates = DISCOVERY.read_text(encoding="utf-8") + PRICING.read_text(
        encoding="utf-8"
    )
    exported_fact_markers = (
        "Ally",
        "Ethan",
        "Active Fence",
        "Tova",
        "Chris",
        "$6,500",
        "$1,500",
        "$150/hour",
        "handala",
        "Iranian NVE",
    )

    assert all(marker not in templates for marker in exported_fact_markers)
