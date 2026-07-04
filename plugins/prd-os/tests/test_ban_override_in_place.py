"""Override-in-place contract (fable-override-in-place).

Every hard ban in the discipline skill states its legitimate override in the
SAME paragraph as the ban: a ban with no documented escape hatch trains the
model to route around the whole skill instead (the taste-skill production
lesson: absolutist prose without an escape hatch decays into ignored prose).
Hook-enforced bans additionally name their skip marker in place, one marker
per hook, no stacking (skill-hook-pairing.md).

A ban unit = a list item (bullet or numbered) or blank-line-separated block
containing the word "never" (the skill's hard-ban verb; softer guidance uses
other phrasing on purpose). Per-ITEM granularity matters: a whole contiguous
bullet list is one blank-line paragraph, so one item's marker would mask a
naked sibling ban (codex major, this issue). An override signal = a skip
marker, or an explicit condition ("unless", "Override:", "Exception:",
"escape hatch").

Explicitly excluded, non-normative by design:
- EXAMPLE.md — worked narrative, not rule text.
- references/fable-discipline-v1.md — the frozen pre-merge archive
  (discipline-skill-versioning); editing it would break the freeze contract
  (`diff -q` against the v1 receipt), so it keeps the old phrasing forever.
"""
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills/fable-discipline"
NORMATIVE = [
    SKILL_DIR / "SKILL.md",
    SKILL_DIR / "references/checklist.md",
    # prd-os's own skill: its nevers are SYSTEM INVARIANTS (Codex never edits,
    # state never committed, findings never dropped), each satisfied by naming
    # its executable enforcement in place rather than a behavioral escape hatch
    SKILL_DIR.parent / "prd-os/SKILL.md",
]
EXCLUDED_AS_NON_NORMATIVE = [
    SKILL_DIR / "EXAMPLE.md",
    Path(__file__).resolve().parents[1]
    / "skills/prd-os/references/fable-discipline-v1.md",
]

MARKERS = ("fable-discipline-lint-skip", "spillover-skip")
OVERRIDE_RE = re.compile(r"\bunless\b|override:|exception:|escape hatch", re.I)
# A ban backed by code is an invariant, not a behavior request: naming the
# executable blocker in the same unit satisfies override-in-place (enforcement
# is the hatch's owner; you change the code, not talk past the ban)
ENFORCEMENT_RE = re.compile(
    r"\.gitignore|gates run|auto-creates an open spillover|/codex:review|"
    r"hook|lint|validator", re.I,
)
BAN_RE = re.compile(r"\bnever\b", re.I)
_ITEM_START = re.compile(r"^\s*(?:-|\d+\.)\s+")


def _paragraphs(text: str) -> list[str]:
    """Split into ban units: blank-line blocks, then per list item inside
    each block. A new '-' or 'N.' line starts a new unit; continuation
    lines stay with their item."""
    units = []
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        current: list[str] = []
        for line in block.splitlines():
            if _ITEM_START.match(line) and current:
                units.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            units.append("\n".join(current).strip())
    return [u for u in units if u]


def _ban_paragraphs():
    for path in NORMATIVE:
        for para in _paragraphs(path.read_text()):
            if para.lstrip().startswith("#"):
                # a section title is a name, not a rule unit; its body units
                # are walked on their own
                continue
            if BAN_RE.search(para):
                yield path.name, para


def test_every_ban_paragraph_names_its_override_in_place():
    naked = [
        (name, para[:120])
        for name, para in _ban_paragraphs()
        if not (OVERRIDE_RE.search(para) or ENFORCEMENT_RE.search(para)
                or any(m in para for m in MARKERS))
    ]
    assert not naked, (
        "ban paragraphs with no in-place override condition or skip marker:\n"
        + "\n\n".join(f"[{n}] {p}" for n, p in naked)
    )


def test_hook_enforced_bans_name_their_marker_in_place():
    text = (SKILL_DIR / "SKILL.md").read_text()
    paras = _paragraphs(text)
    iso = [p for p in paras if "Test isolation" in p]
    assert iso and "fable-discipline-lint-skip" in iso[0], (
        "test-isolation ban paragraph does not name its skip marker"
    )
    spill = [p for p in paras if "spillover ledger" in p and BAN_RE.search(p)]
    assert spill and all("spillover-skip" in p for p in spill), (
        "spillover-capture ban paragraph does not name its skip marker"
    )


def test_one_marker_per_hook_no_stacking():
    """Each marker appears for its own hook only; no paragraph asks for two
    markers on one ban (stacked markers = ambiguous bypass surface)."""
    for name, para in _ban_paragraphs():
        both = all(m in para for m in MARKERS)
        assert not both, f"[{name}] paragraph stacks both skip markers: {para[:120]}"
