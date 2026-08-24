import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from kipi_mcp.morning_init import (
    _split_sections,
    preflight,
    session_bootstrap,
    canonical_digest,
    morning_init,
    gate_check,
    deliverables_check,
    retry_notion_queue,
    _check_db_integrity,
    auto_backup,
)


@pytest.fixture
def paths(tmp_path):
    from kipi_mcp.paths import KipiPaths
    from conftest import write_registry
    write_registry(tmp_path / "base", tmp_path / "repo", instance="test")
    p = KipiPaths(base_dir=tmp_path / "base", repo_dir=tmp_path / "repo", instance="test")
    p.ensure_dirs()
    return p


def _create_file(path: Path, content: str = "test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ── Preflight ──


class TestPreflight:
    def test_all_files_exist(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        _create_file(paths.memory_dir / "last-handoff.md")
        result = preflight(paths)
        assert result["ready"] is True
        assert all(v is True for v in result["files"].values())

    def test_missing_required_file(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        # objections.md missing
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is False
        assert result["files"]["objections"] is False
        assert result["files"]["talk_tracks"] is True

    def test_optional_missing_still_ready(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        # handoff missing (optional)
        result = preflight(paths)
        assert result["ready"] is True
        assert result["files"]["handoff"] is False

    def test_returns_date(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert "date" in result

    def test_empty_file_rejected(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "tiny")  # 4 bytes < 50
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is False
        assert result["files"]["talk_tracks"] == "empty"
        assert len(result["content_warnings"]) >= 1
        assert "talk_tracks" in result["content_warnings"][0]

    def test_valid_content_passes(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is True
        assert result["content_warnings"] == []
        assert all(v is True for k, v in result["files"].items() if k != "handoff")


# ── Bootstrap ──


class TestBootstrap:
    def test_no_previous_session(self, paths):
        result = session_bootstrap(paths)
        assert result["action_cards"] == []
        assert result["loop_stats"]["open"] == 0

    def test_recovers_action_cards(self, paths):
        log = {
            "action_cards": [
                {"id": "c1", "confirmed": False, "text": "Follow up with Alice"},
                {"id": "c2", "confirmed": True, "text": "Done"},
            ]
        }
        date = datetime.now().strftime("%Y-%m-%d")
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = session_bootstrap(paths)
        assert len(result["action_cards"]) == 1
        assert result["action_cards"][0]["id"] == "c1"

    def test_loop_stats(self, paths):
        loops = [
            {"id": "L1", "status": "open", "escalation_level": 0},
            {"id": "L2", "status": "open", "escalation_level": 2},
            {"id": "L3", "status": "closed", "escalation_level": 1},
        ]
        (paths.output_dir / "open-loops.json").write_text(json.dumps(loops))
        result = session_bootstrap(paths)
        assert result["loop_stats"]["open"] == 2
        assert result["loop_stats"]["level_0"] == 1
        assert result["loop_stats"]["level_2"] == 1

    def test_stall_detection(self, paths):
        old_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
        content = f"## Alice\n- Company: Acme\n- Last contact: {old_date}\n"
        _create_file(paths.my_project_dir / "relationships.md", content)
        result = session_bootstrap(paths)
        assert len(result["stalls"]) == 1
        assert result["stalls"][0]["contact"] == "Alice"
        assert result["stalls"][0]["days_stale"] >= 20

    def test_canonical_checksums(self, paths):
        content = "# Test talk track\nMetaphor goes here."
        _create_file(paths.canonical_dir / "talk-tracks.md", content)
        _create_file(paths.canonical_dir / "objections.md", "# Obj 1\nResponse.")
        result = session_bootstrap(paths)
        expected = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert result["checksums"]["talk_tracks"] == expected

    def test_bootstrap_includes_recently_closed_loops(self, paths):
        from kipi_mcp.loop_tracker import LoopTracker
        lt = LoopTracker(db_path=paths.metrics_db)
        lt.init_db()
        opened = lt.open("email_sent", "TestTarget", "intro")
        lt.close(opened["loop_id"], "replied", "system")
        result = session_bootstrap(paths)
        assert "recently_closed_loops" in result
        assert len(result["recently_closed_loops"]) >= 1
        assert result["recently_closed_loops"][0]["target"] == "TestTarget"
        assert "recently_closed" in result["loop_stats"]


# ── Canonical Digest ──


class TestCanonicalDigest:
    def test_extracts_talk_tracks(self, paths):
        content = (
            "# Primary Metaphor\nYour brain externalized.\n\n"
            "# Key Definition\nA second brain that remembers everything.\n\n"
            "# Wedge Formula\n3 out of 5 founders forget. This fixes it.\n\n"
            "# Banned Phrases\n- leverage\n- synergy\n- game-changer\n\n"
            "# Detection Rule\nIf they say 'I keep forgetting', pivot to demo.\n"
        )
        _create_file(paths.canonical_dir / "talk-tracks.md", content)
        result = canonical_digest(paths)
        tt = result["talk_tracks"]
        assert "externalized" in tt["metaphor"]
        assert "second brain" in tt["definition"]
        assert len(tt["banned_phrases"]) == 3
        assert "leverage" in tt["banned_phrases"]

    def test_extracts_objections(self, paths):
        content = "# Too expensive\nWe save 20 hours/week. That's worth more than the cost. Most teams see ROI in 2 weeks.\n\n# Already have a tool\nGreat. Does it remember what each person said last month? Our system compounds knowledge."
        _create_file(paths.canonical_dir / "objections.md", content)
        result = canonical_digest(paths)
        assert len(result["objections"]) == 2
        assert result["objections"][0]["name"] == "Too expensive"
        assert "20 hours" in result["objections"][0]["response"]

    def test_extracts_current_state(self, paths):
        content = "# What Works Today\n- Morning briefing\n- Loop tracking\n\n# Validated\n- AUDHD friction ordering\n\n# Unvalidated\n- Auto-posting\n"
        _create_file(paths.my_project_dir / "current-state.md", content)
        result = canonical_digest(paths)
        cs = result["current_state"]
        assert "Morning briefing" in cs["works_today"]
        assert "AUDHD friction ordering" in cs["validated"]
        assert "Auto-posting" in cs["unvalidated"]

    def test_extracts_decisions(self, paths):
        content = "# [RULE] Never auto-post\nFounder must approve all posts before publishing.\n\n# [RULE] Haiku for data pulls\nUse haiku model for all data-fetching agents.\n"
        _create_file(paths.canonical_dir / "decisions.md", content)
        result = canonical_digest(paths)
        assert len(result["decisions"]) >= 2

    def test_missing_file_graceful(self, paths):
        # Only create talk-tracks, skip the rest
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Metaphor\nTest.")
        result = canonical_digest(paths)
        assert len(result["warnings"]) >= 1
        assert result["talk_tracks"]["metaphor"] != ""

    def test_validation_gate(self, paths):
        # Create all files with valid content
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Primary Metaphor\nBrain ext.\n# Key Definition\nSecond brain.\n")
        _create_file(paths.canonical_dir / "objections.md", "# Obj1\nResponse here.\n")
        _create_file(paths.my_project_dir / "current-state.md", "# What Works Today\n- Item1\n")
        _create_file(paths.canonical_dir / "discovery.md", "# Top Questions\n- Q1\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] Test\nDo this.\n")
        result = canonical_digest(paths)
        assert result["valid"] is True

    def test_h3_children_parse_into_their_h2_section(self, paths):
        """sp-8804dee7. The live discovery.md sections with ## and nests its
        28 real questions under ### vertical children; splitting at ANY heading
        shipped the parent empty and lost every child to unmatched headings."""
        content = (
            "# Discovery Log\n\n"
            "## Unanswered Questions\n\n"
            "### ESG Vertical\n"
            "- What ESG platforms do firms use?\n"
            "- What is the buying decision-maker?\n\n"
            "### IP Law Vertical\n"
            "- Which patent platforms do boutiques use?\n\n"
            "## Validation Gaps\n"
            "- ESG ROI numbers unvalidated\n"
        )
        _create_file(paths.canonical_dir / "discovery.md", content)
        result = canonical_digest(paths)
        assert len(result["discovery"]["questions"]) == 3

    def test_gap_sections_accumulate_never_overwrite(self, paths):
        """sp-7e42845e mechanism 2. '## Validation Gaps' was overwritten by
        '## Website Positioning Gap', shipping March website notes labelled as
        validation gaps."""
        content = (
            "# Discovery Log\n\n"
            "## Validation Gaps\n"
            "- ESG ROI numbers unvalidated\n\n"
            "## Website Positioning Gap\n"
            "- askconsulting.io positioned as fraud investigation\n"
        )
        _create_file(paths.canonical_dir / "discovery.md", content)
        result = canonical_digest(paths)
        gaps = result["discovery"]["gaps"]
        assert any("ESG ROI" in g for g in gaps), gaps
        assert any("askconsulting.io" in g for g in gaps), gaps

    def test_superseded_source_is_recorded_not_parsed(self, paths):
        """ASK-510 retired three sources to pointer docs. Their bodies describe
        the retirement; parsing them shipped retired content as live content."""
        content = (
            "---\nstatus: superseded\nsuperseded_by: ASK-510 2026-08-08\n---\n\n"
            "# Talk Tracks\n\n> **SUPERSEDED 2026-08-08 (ASK-510).**\n\n"
            "## Why this was retired rather than rewritten\n"
            "- It sold the retired beachhead.\n"
        )
        _create_file(paths.canonical_dir / "talk-tracks.md", content)
        _create_file(paths.canonical_dir / "objections.md",
                     "# Obj\nResp.\n")   # not retired, must still parse
        result = canonical_digest(paths)
        assert result["retired_sources"]["talk_tracks"] == {"decision": "ASK-510"}
        assert result["talk_tracks"] == {}
        assert len(result["objections"]) == 1
        assert not any("retired" in w or "talk-tracks" in w
                       for w in result["warnings"]), result["warnings"]

    def test_valid_false_names_its_failed_checks(self, paths):
        """sp-7e42845e mechanism 3: valid=False arrived with warnings=[] and no
        reason attached anywhere."""
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] R\nD.\n")
        result = canonical_digest(paths)
        assert result["valid"] is False
        assert "discovery: no questions parsed" in result["validation_failed"]

    def test_retired_sources_drop_out_of_validity(self, paths):
        """The schema decision: metaphor/definition/wedge/works_today belong to
        sources deliberately retired under ASK-510. With those sources retired,
        valid=True is reachable honestly from what still lives."""
        for name in ("talk-tracks.md", "objections.md"):
            _create_file(paths.canonical_dir / name,
                         f"# {name}\n> SUPERSEDED 2026-08-08 (ASK-510).\n")
        _create_file(paths.my_project_dir / "current-state.md",
                     "---\nstatus: superseded\nsuperseded_by: ASK-510\n---\n")
        _create_file(
            paths.canonical_dir / "discovery.md",
            "## Unanswered Questions\n### V\n- Q1\n\n## Validation Gaps\n- G1\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] R\nD.\n")
        result = canonical_digest(paths)
        assert set(result["retired_sources"]) == {
            "talk_tracks", "objections", "current_state"}
        assert result["valid"] is True, result["validation_failed"]


# ── Canonical Digest: wrong content (ASK-977) ──


# Shapes taken from the live consulting tree as MEASURED and recorded in ASK-977
# on 2026-08-23 (H2 sections with H3 children; '## Validation Gaps' immediately
# followed by '## Website Positioning Gap'), not from an author's imagination.
# This worktree cannot read that tree, so the provenance is the issue's
# measurement, and these fixtures reproduce its SHAPE, never its content.

DISCOVERY_H3_CHILDREN = """\
# Discovery

## Unanswered Questions

### Pricing
- What does a pilot actually cost?
- Who signs the PO?

### Scope
- Which data sources are in scope?

## Validation Gaps

### Never tested
- Nobody has paid for the weekly report yet

## Website Positioning Gap

- askconsulting.io reads as fraud investigation
"""


class TestDigestReturnsRightContent:
    """ASK-977: canonical_digest returned WRONG content, not merely empty."""

    def test_h3_children_stay_in_their_h2_parent(self, paths):
        """Mechanism 1: H3 was a peer of H2, so the parent parsed to 0 items."""
        _create_file(paths.canonical_dir / "discovery.md", DISCOVERY_H3_CHILDREN)
        questions = canonical_digest(paths)["discovery"]["questions"]
        assert "What does a pilot actually cost?" in questions
        assert "Which data sources are in scope?" in questions

    def test_matching_sections_accumulate_instead_of_overwriting(self, paths):
        """Mechanism 2: last-match-wins shipped website notes AS validation gaps."""
        _create_file(paths.canonical_dir / "discovery.md", DISCOVERY_H3_CHILDREN)
        gaps = canonical_digest(paths)["discovery"]["gaps"]
        assert "Nobody has paid for the weekly report yet" in gaps
        assert "askconsulting.io reads as fraud investigation" in gaps

    def test_accumulated_items_keep_the_cap_and_dedupe(self, paths):
        """The cap survives accumulation, and a parent+child pair is not doubled."""
        gap_sections = "\n\n".join(
            f"## Gap {n}\n\n### detail\n- gap item {n}" for n in range(14)
        )
        _create_file(paths.canonical_dir / "discovery.md", gap_sections)
        gaps = canonical_digest(paths)["discovery"]["gaps"]
        assert len(gaps) == 10
        assert len(set(gaps)) == 10

    def test_flat_h1_documents_still_split_per_heading(self, paths):
        """Nesting must not merge a document whose headings are all one depth."""
        _create_file(
            paths.canonical_dir / "objections.md",
            "# Too expensive\nWe save time.\n\n# Already have a tool\nDoes it remember?\n",
        )
        objections = canonical_digest(paths)["objections"]
        names = [o["name"] for o in objections]
        assert names == ["Too expensive", "Already have a tool"]
        assert objections[0]["response"] == "We save time."


SUPERSEDED_TALK_TRACKS = """\
---
status: superseded
superseded_by: ASK-510
---

# Primary Metaphor
Your brain externalized.
"""

SUPERSEDED_CURRENT_STATE = """\
> **SUPERSEDED** by ASK-510. Kept for history only.

# What Works Today
- Something that has not been true since March
"""


def _seed_live_sources(paths):
    _create_file(paths.canonical_dir / "objections.md", "# Obj1\nResponse here.\n")
    _create_file(paths.canonical_dir / "discovery.md", "# Top Questions\n- Q1\n")
    _create_file(paths.canonical_dir / "decisions.md", "# [RULE] Test\nDo this.\n")


class TestRetiredSources:
    """A retired source must be distinguishable from an absent one."""

    def test_superseded_frontmatter_is_recorded_not_parsed(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", SUPERSEDED_TALK_TRACKS)
        result = canonical_digest(paths)
        assert result["retired_sources"]["talk_tracks"] == {"decision": "ASK-510"}
        assert result["talk_tracks"].get("metaphor", "") == ""

    def test_superseded_banner_is_recorded_not_parsed(self, paths):
        _create_file(paths.my_project_dir / "current-state.md", SUPERSEDED_CURRENT_STATE)
        result = canonical_digest(paths)
        assert result["retired_sources"]["current_state"] == {"decision": "ASK-510"}
        assert result["current_state"].get("works_today", []) == []

    def test_retirement_adds_no_warning(self, paths):
        """warnings stay a missing-file signal; retirement is not a missing file."""
        _create_file(paths.canonical_dir / "talk-tracks.md", SUPERSEDED_TALK_TRACKS)
        _create_file(paths.my_project_dir / "current-state.md", SUPERSEDED_CURRENT_STATE)
        _seed_live_sources(paths)
        assert canonical_digest(paths)["warnings"] == []

    def test_a_live_source_is_not_marked_retired(self, paths):
        """Negative self-test: without a banner the same file parses as before."""
        _create_file(
            paths.canonical_dir / "talk-tracks.md",
            "# Primary Metaphor\nYour brain externalized.\n",
        )
        result = canonical_digest(paths)
        assert result["retired_sources"] == {}
        assert "externalized" in result["talk_tracks"]["metaphor"]


class TestValidityAccounting:
    def test_retired_source_checks_drop_out_and_valid_is_reachable(self, paths):
        """ASK-510 retired talk-tracks + current-state; 3 of 7 checks were then
        structurally unreachable, so valid could never go true honestly."""
        _create_file(paths.canonical_dir / "talk-tracks.md", SUPERSEDED_TALK_TRACKS)
        _create_file(paths.my_project_dir / "current-state.md", SUPERSEDED_CURRENT_STATE)
        _seed_live_sources(paths)
        result = canonical_digest(paths)
        assert result["validation_failed"] == []
        assert result["valid"] is True

    def test_invalid_digest_names_every_reason(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Primary Metaphor\nX.\n")
        result = canonical_digest(paths)
        assert result["valid"] is False
        assert result["validation_failed"], "valid=False named no reason"
        joined = " ".join(result["validation_failed"])
        assert "objections" in joined
        assert "definition" in joined

    def test_live_repo_talk_tracks_headings_yield_a_definition(self):
        """ASK-976: the digest must be valid against THIS repo's real canonical tree.

        Deliberately NOT a fixture. The defect was that every fixture in this
        file spelled the heading `Definition`, while the file the digest
        actually reads spells the same content `### One-liner` / `### Category`
        under `## Core Positioning`. An invented fixture agreed with the parser
        and could not see the gap; only the producer's own file can.

        RED before the fix (2026-08-24):
            valid=False, validation_failed=['talk_tracks: no definition']
        """
        repo = Path(__file__).resolve().parents[4]
        canonical, my_project = repo / "q-system" / "canonical", repo / "q-system" / "my-project"
        if not (canonical / "talk-tracks.md").exists():
            pytest.skip(f"no live canonical tree at {canonical}")

        live = SimpleNamespace(canonical_dir=canonical, my_project_dir=my_project)
        result = canonical_digest(live)

        assert result["talk_tracks"]["definition"], (
            "live talk-tracks.md parsed to an empty definition; its headings are "
            f"{[h for h, _ in _split_sections((canonical / 'talk-tracks.md').read_text())]}"
        )
        assert result["validation_failed"] == []
        assert result["valid"] is True

    def test_a_definition_heading_is_named_never_positional(self, paths):
        """Negative self-test: the aliases are heading names, not a fallback.

        Mutation guard for ASK-976 -- if the fix had been "use the first section
        when no definition heading exists", this file would pass and the check
        would be decoration.
        """
        _create_file(
            paths.canonical_dir / "talk-tracks.md",
            "# Primary Metaphor\nX.\n\n# Rollout Notes\nSome prose that defines nothing.\n",
        )
        result = canonical_digest(paths)
        assert result["talk_tracks"]["definition"] == ""
        assert "talk_tracks: no definition" in result["validation_failed"]

    def test_two_definition_headings_accumulate_never_overwrite(self, paths):
        """`One-liner` + `Category` both feed `definition`; the later must not erase."""
        _create_file(
            paths.canonical_dir / "talk-tracks.md",
            "# Primary Metaphor\nX.\n\n"
            "## Core Positioning\n\n### One-liner\nThe one-liner text.\n\n"
            "### Category\nThe category text.\n",
        )
        definition = canonical_digest(paths)["talk_tracks"]["definition"]
        assert "one-liner text" in definition
        assert "category text" in definition

    def test_a_failing_check_on_a_live_source_still_invalidates(self, paths):
        """Negative self-test: retirement drops checks, it does not pass them."""
        _create_file(paths.canonical_dir / "talk-tracks.md", SUPERSEDED_TALK_TRACKS)
        _create_file(paths.my_project_dir / "current-state.md", SUPERSEDED_CURRENT_STATE)
        _create_file(paths.canonical_dir / "discovery.md", "# Top Questions\n- Q1\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] Test\nDo this.\n")
        # objections.md absent -> a LIVE check fails and one warning is raised
        result = canonical_digest(paths)
        assert result["valid"] is False
        assert any("objections" in r for r in result["validation_failed"])


# ── Morning Init ──


class TestMorningInit:
    def test_cleanup_runs_on_init(self, paths):
        from kipi_mcp.harvest_store import HarvestStore
        store = HarvestStore(db_path=paths.output_dir / "test.db")
        store.init_db()
        # Create an old run
        import sqlite3
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "INSERT INTO harvest_runs (run_id, started_at, mode, status) VALUES (?, ?, ?, ?)",
            ("old-run", "2026-01-01T00:00:00", "incremental", "complete"),
        )
        conn.commit()
        conn.close()
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=3, harvest_store=store)
        assert result["cleanup"]["deleted_runs"] >= 1

    def test_old_files_cleaned(self, paths):
        import os, time
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        # Create an old morning log (backdate mtime)
        old_log = paths.output_dir / "morning-log-2025-01-01.json"
        old_log.write_text("{}")
        old_time = time.time() - (15 * 86400)  # 15 days ago
        os.utime(old_log, (old_time, old_time))
        morning_init(paths, energy_level=3)
        assert not old_log.exists()

    def test_returns_complete_bundle(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Metaphor\nTest." + "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "# Obj\nResp." + "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        _create_file(paths.my_project_dir / "current-state.md", "# What Works Today\n- X\n")
        _create_file(paths.canonical_dir / "discovery.md", "# Questions\n- Q\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] R\nD.\n")
        result = morning_init(paths, energy_level=3)
        assert "preflight" in result
        assert "bootstrap" in result
        assert "canonical_digest" in result
        assert "energy" in result
        assert "date" in result

    def test_energy_compression(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=2)
        assert result["energy"]["max_hitlist"] == 5
        assert result["energy"]["skip_deep_focus"] is True

        result = morning_init(paths, energy_level=5)
        assert result["energy"]["max_hitlist"] == 999
        assert result["energy"]["skip_deep_focus"] is False

    def test_morning_init_detects_handoff(self, paths):
        from kipi_mcp.harvest_store import HarvestStore
        store = HarvestStore(db_path=paths.output_dir / "test.db")
        store.init_db()
        today = datetime.now().strftime("%Y-%m-%d")
        store.save_handoff(
            date=today, run_id=f"{today}-001",
            phases_completed="phase_0,phase_1",
            notes="Stopped mid-harvest",
        )
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=3, harvest_store=store)
        assert result["resume_from"] is not None
        assert result["resume_from"]["phases_completed"] == "phase_0,phase_1"
        assert result["resume_from"]["notes"] == "Stopped mid-harvest"


# ── Gate Check ──


class TestGateCheck:
    def test_no_log_file(self, paths):
        result = gate_check(paths, phase=6, date="2026-04-01")
        assert result["passed"] is False
        assert "not found" in result["error"]

    def test_all_prior_phases_done(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                "phase_2_analysis": {"status": "done"},
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is True
        assert result["missing"] == []

    def test_missing_phase(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                # phase_2_analysis missing
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is False
        assert "phase_2_analysis" in result["missing"]

    def test_skipped_counts_as_done(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                "phase_2_analysis": {"status": "skipped"},
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is True


# ── Deliverables Check ──


class TestDeliverablesCheck:
    @pytest.fixture
    def store(self, tmp_path):
        from kipi_mcp.harvest_store import HarvestStore
        s = HarvestStore(db_path=tmp_path / "test.db")
        s.init_db()
        return s

    def _store_agent_record(self, store, source_name):
        run = store.create_run("incremental")
        store.store_record(
            run_id=run["run_id"],
            source_name=source_name,
            record_key=f"test-{source_name}",
            summary_json='{"test": true}',
        )

    def test_all_present(self, paths, store):
        for agent in [
            "agent:pipeline-followup", "agent:engagement-hitlist",
            "agent:outbound-detection", "agent:loop-review",
            "agent:signals-content", "agent:value-routing",
        ]:
            self._store_agent_record(store, agent)
        result = deliverables_check(paths, harvest_store=store)
        assert result["passed"] is True
        assert len(result["missing"]) == 0

    def test_missing_hitlist(self, paths, store):
        for agent in [
            "agent:pipeline-followup",
            "agent:outbound-detection", "agent:loop-review",
            "agent:signals-content", "agent:value-routing",
        ]:
            self._store_agent_record(store, agent)
        # hitlist missing
        result = deliverables_check(paths, harvest_store=store)
        assert result["passed"] is False
        assert any("hitlist" in m for m in result["missing"])

    def test_no_store(self, paths):
        result = deliverables_check(paths, harvest_store=None)
        assert result["passed"] is False
        assert len(result["missing"]) > 0


# ── DB Integrity ──


class TestDbIntegrity:
    def test_db_integrity_check_ok(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()
        result = _check_db_integrity(db_path)
        assert result["status"] == "ok"
        assert result["detail"] == "ok"

    def test_db_integrity_check_no_db(self, tmp_path):
        result = _check_db_integrity(tmp_path / "nonexistent.db")
        assert result["status"] == "no_db"


# ── Auto Backup ──


class TestAutoBackup:
    @pytest.fixture
    def backup_mgr(self, paths):
        from kipi_mcp.backup import BackupManager
        # Seed PLUGIN-DATA, not canonical/. canonical_dir is repo-derived since the
        # path-contract repoint and BackupManager sweeps global_dir + config_dir
        # only, so a file seeded there produced an archive of 0 files and this
        # case asserted >= 1 against an empty backup.
        _create_file(paths.config_dir / "founder-profile.md", "# Profile")
        return BackupManager(paths)

    def test_auto_backup_creates_archive(self, backup_mgr):
        result = auto_backup(backup_mgr)
        assert "backup" in result
        assert result["backup"]["files_count"] >= 1
        assert Path(result["backup"]["path"]).exists()

    def test_auto_backup_rotation_keeps_5(self, backup_mgr, paths):
        out = paths.output_dir
        for i in range(7):
            backup_mgr.backup(output_path=out / f"kipi-backup-2026010{i}-000000.tar.gz")
        assert len(backup_mgr.list_backups()) == 7
        result = auto_backup(backup_mgr, max_backups=5)
        assert result["rotation"]["kept"] == 5
        assert len(result["rotation"]["deleted"]) >= 2
        # 7 + 1 new = 8, rotate keeps 5
        assert len(backup_mgr.list_backups()) == 5
