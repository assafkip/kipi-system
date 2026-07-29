#!/usr/bin/env python3
"""Self-test for system_manifest.py.

Pairs with RCA rca-conclusions-before-evidence-2026-07-28, contributing factor:
"No manifest exists declaring which workflows constitute a data path, so 'have I read
all of this subsystem' is not a computable question today." These cases are that
question, made computable.

Hermetic: every case builds its own temp instance root.
Run: python3 test_system_manifest.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import system_manifest as SM  # noqa: E402

GOOD = {
    "version": 1,
    "subsystems": [
        {
            "id": "groupme-to-sheet",
            "name": "GroupMe order intake to Google Sheet",
            "aliases": ["the ingest chain", "sheet sync pipeline"],
            "members": [
                {"ref": "Prodigy Gold - Postgres Ingest", "kind": "n8n-workflow"},
                {"ref": "Prodigy Gold - Parse LLM", "kind": "n8n-workflow"},
                {"ref": "Prodigy Gold - QA Validator", "kind": "n8n-workflow"},
            ],
        }
    ],
}


def _root(manifest=None) -> Path:
    tmp = Path(tempfile.mkdtemp())
    canon = tmp / "q-thing" / "canonical"
    canon.mkdir(parents=True)
    if manifest is not None:
        (canon / "system-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
    return tmp


def case_absent_manifest_is_not_an_error() -> bool:
    """No manifest means the gate no-ops. The skeleton itself ships without one."""
    repo = _root()
    return SM.load(repo) == {} and SM.check(repo) == [] and SM.mentions(repo, "x") == []


def case_check_passes_a_good_manifest() -> bool:
    return SM.check(_root(GOOD)) == []


def case_check_rejects_zero_members() -> bool:
    """A subsystem with no members makes coverage vacuously true. That is the bug."""
    bad = json.loads(json.dumps(GOOD))
    bad["subsystems"][0]["members"] = []
    return len(SM.check(_root(bad))) > 0


def case_check_rejects_duplicate_member_ref() -> bool:
    bad = json.loads(json.dumps(GOOD))
    bad["subsystems"][0]["members"].append(
        {"ref": "Prodigy Gold - Parse LLM", "kind": "n8n-workflow"})
    return len(SM.check(_root(bad))) > 0


def case_check_rejects_duplicate_subsystem_id() -> bool:
    bad = json.loads(json.dumps(GOOD))
    bad["subsystems"].append(json.loads(json.dumps(GOOD["subsystems"][0])))
    return len(SM.check(_root(bad))) > 0


def case_check_rejects_alias_collision() -> bool:
    """Two subsystems answering to one alias makes `mentions` ambiguous."""
    bad = json.loads(json.dumps(GOOD))
    other = json.loads(json.dumps(GOOD["subsystems"][0]))
    other["id"] = "rep-form-to-fastgem"
    other["aliases"] = ["the ingest chain"]
    bad["subsystems"].append(other)
    return len(SM.check(_root(bad))) > 0


def case_mentions_hits_on_id() -> bool:
    repo = _root(GOOD)
    return SM.mentions(repo, "The groupme-to-sheet path is fine.") == ["groupme-to-sheet"]


def case_mentions_hits_on_alias() -> bool:
    """The RCA's failure was prose, not ids. Aliases are how a subsystem gets named."""
    repo = _root(GOOD)
    return SM.mentions(repo, "The ingest chain drops rows.") == ["groupme-to-sheet"]


def case_mentions_is_case_insensitive() -> bool:
    repo = _root(GOOD)
    return SM.mentions(repo, "Sheet Sync Pipeline looks healthy.") == ["groupme-to-sheet"]


def case_mentions_ignores_unrelated_text() -> bool:
    repo = _root(GOOD)
    return SM.mentions(repo, "The weather is fine and the build is green.") == []


def case_missing_members_reports_the_unread() -> bool:
    """THE reproducer. Two of three workflows read, a claim about the chain issued."""
    repo = _root(GOOD)
    evidence = "I opened Prodigy Gold - Postgres Ingest and Prodigy Gold - Parse LLM."
    return SM.missing_members(repo, "groupme-to-sheet", evidence) == [
        "Prodigy Gold - QA Validator"]


def case_missing_members_empty_when_all_read() -> bool:
    repo = _root(GOOD)
    evidence = ("Prodigy Gold - Postgres Ingest / Prodigy Gold - Parse LLM / "
                "Prodigy Gold - QA Validator all opened.")
    return SM.missing_members(repo, "groupme-to-sheet", evidence) == []


def case_missing_members_match_is_case_insensitive() -> bool:
    repo = _root(GOOD)
    evidence = "prodigy gold - postgres ingest, PRODIGY GOLD - PARSE LLM, Prodigy Gold - QA Validator"
    return SM.missing_members(repo, "groupme-to-sheet", evidence) == []


def case_missing_members_all_when_nothing_read() -> bool:
    repo = _root(GOOD)
    return len(SM.missing_members(repo, "groupme-to-sheet", "")) == 3


CASES = [
    ("absent manifest is not an error", case_absent_manifest_is_not_an_error),
    ("check passes a good manifest", case_check_passes_a_good_manifest),
    ("check rejects zero members", case_check_rejects_zero_members),
    ("check rejects a duplicate member ref", case_check_rejects_duplicate_member_ref),
    ("check rejects a duplicate subsystem id", case_check_rejects_duplicate_subsystem_id),
    ("check rejects an alias collision", case_check_rejects_alias_collision),
    ("mentions hits on id", case_mentions_hits_on_id),
    ("mentions hits on alias", case_mentions_hits_on_alias),
    ("mentions is case insensitive", case_mentions_is_case_insensitive),
    ("mentions ignores unrelated text", case_mentions_ignores_unrelated_text),
    ("missing_members reports the unread member", case_missing_members_reports_the_unread),
    ("missing_members empty when all read", case_missing_members_empty_when_all_read),
    ("missing_members match is case insensitive", case_missing_members_match_is_case_insensitive),
    ("missing_members returns all when nothing read", case_missing_members_all_when_nothing_read),
]


def main() -> int:
    failures = 0
    for name, fn in CASES:
        try:
            ok = bool(fn())
        except Exception as exc:
            ok = False
            name = f"{name} [raised {type(exc).__name__}: {exc}]"
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        failures += 0 if ok else 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
