#!/usr/bin/env python3
"""
End-to-end tests for stat-verify.py. Covers hook-mode payloads, JSON content
walks, opt-out tags, scope, and registry lookup. Runnable standalone:

    python3 q-system/.q-system/scripts/tests/test-stat-verify.py

Exits 0 if all tests pass, 1 otherwise. Self-contained — uses tmpdirs, no
pytest dependency, no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "stat-verify.py"


def run_hook(payload: dict, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cli(file_path: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(SCRIPT), file_path],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def make_instance(tmpdir: Path, stat_overrides: list | None = None) -> Path:
    """Create a fake instance-shaped tree with canonical/stat-registry.json."""
    canonical = tmpdir / "canonical"
    canonical.mkdir(parents=True)
    bus = tmpdir / ".q-system" / "agent-pipeline" / "bus" / "2026-05-21"
    bus.mkdir(parents=True)
    registry = {
        "version": 1,
        "stats": stat_overrides or [
            {
                "id": "siem-attack",
                "approved_numerics": ["21%", "90%", "90%+", "79%"],
                "canonical_phrasings": [
                    "SIEMs cover 21% of ATT&CK",
                    "data for 90%",
                    "missing 79% of ATT&CK",
                ],
            },
            {
                "id": "handoffs",
                "approved_numerics": ["42", "7", "6"],
                "canonical_phrasings": ["42 handoffs", "7 input types", "6 teams"],
            },
            {
                "id": "test-spec",
                "approved_numerics": ["60+", "11", "40 seconds"],
                "canonical_phrasings": ["60+ artifacts", "11 team folders", "40 seconds"],
            },
        ],
    }
    (canonical / "stat-registry.json").write_text(json.dumps(registry))
    return bus


def test_in_scope_bus_content_with_bad_stat_blocks(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({
        "x_thread": ["SIEMs are missing 76% of ATT&CK coverage."],
    }))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, out, err = run_hook(payload)
    assert rc == 2, f"expected exit 2, got {rc}; stderr={err}"
    assert "76%" in err, f"expected '76%' in stderr; got: {err!r}"


def test_in_scope_bus_content_with_canonical_stat_passes(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({
        "x_thread": [
            "SIEMs cover 21% of ATT&CK techniques despite having data for 90%.",
            "42 handoffs across 6 teams.",
        ],
    }))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"expected exit 0, got {rc}; stderr={err}"


def test_unvalidated_tag_allows_unknown_stat(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({
        "linkedin_draft": "Something something 999% improvement {{UNVALIDATED}}.",
    }))
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"expected exit 0, got {rc}; stderr={err}"


def test_skip_marker_bypasses_entire_file(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({
        "_note": "stat-verify-skip",
        "x_thread": ["76% of nonsense", "another 88% claim"],
    }))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"expected exit 0, got {rc}; stderr={err}"


def test_metadata_bus_file_out_of_scope(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "_meta.json"
    target.write_text(json.dumps({"x_thread": ["76% bogus"]}))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"expected exit 0 (metadata out of scope), got {rc}; stderr={err}"


def test_non_content_fields_ignored(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    # 76% lives only in a non-content key — should be ignored.
    target.write_text(json.dumps({
        "format": "76% of something",
        "auto_fail_check": "pass",
    }))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"non-content fields should not trip the verifier; got {rc}; stderr={err}"


def test_out_of_scope_path_silent(tmpdir: Path) -> None:
    make_instance(tmpdir)
    target = tmpdir / "random.json"
    target.write_text(json.dumps({"linkedin_draft": "76% nope"}))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"out-of-scope path should be silent; got {rc}; stderr={err}"


def test_non_edit_tool_silent(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["76% bogus"]}))
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 0, f"non-Edit/Write tool should be silent; got {rc}; stderr={err}"


def test_cli_clean_file_exits_zero(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["42 handoffs across 6 teams."]}))
    rc, out, err = run_cli(str(target))
    assert rc == 0, f"CLI clean file should exit 0; got {rc}; out={out}; err={err}"
    assert "clean" in out


def test_cli_dirty_file_exits_two(tmpdir: Path) -> None:
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["fake 99% claim"]}))
    rc, out, err = run_cli(str(target))
    assert rc == 2, f"CLI dirty file should exit 2; got {rc}; out={out}; err={err}"


def test_missing_registry_fails_closed(tmpdir: Path) -> None:
    """No registry in tree = fail-closed (exit 2) on in-scope content."""
    bus = tmpdir / ".q-system" / "agent-pipeline" / "bus" / "2026-05-21"
    bus.mkdir(parents=True)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["42 handoffs"]}))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    # Clamp registry lookup to a known-missing path so the walk doesn't
    # find an unrelated repo's registry on dev machines.
    rc, _, err = run_hook(
        payload,
        extra_env={
            "STAT_VERIFY_BOOTSTRAP": "",
            "STAT_REGISTRY_PATH": str(tmpdir / "nope-registry.json"),
        },
    )
    assert rc == 2, f"expected fail-closed exit 2 on missing registry; got {rc}; stderr={err}"
    assert "registry" in err.lower(), f"expected registry hint in stderr; got: {err!r}"


def test_bootstrap_escape_allows_missing_registry(tmpdir: Path) -> None:
    """STAT_VERIFY_BOOTSTRAP=1 allows in-scope content to pass with no registry."""
    bus = tmpdir / ".q-system" / "agent-pipeline" / "bus" / "2026-05-21"
    bus.mkdir(parents=True)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["42 handoffs"]}))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(
        payload,
        extra_env={
            "STAT_VERIFY_BOOTSTRAP": "1",
            "STAT_REGISTRY_PATH": str(tmpdir / "nope-registry.json"),
        },
    )
    assert rc == 0, f"bootstrap mode should pass; got {rc}; stderr={err}"


def test_cli_missing_registry_exits_two_not_one(tmpdir: Path) -> None:
    """CLI mode aligns with hook mode: exit 2 on missing registry, not 1."""
    target = tmpdir / "lone.json"
    target.write_text(json.dumps({"x_thread": ["42 handoffs"]}))
    proc = subprocess.run(
        ["python3", str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        env={**os.environ, "STAT_REGISTRY_PATH": str(tmpdir / "nope-registry.json")},
    )
    assert proc.returncode == 2, (
        f"CLI must exit 2 on missing registry; got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_find_registry_does_not_walk_into_sibling_subtree(tmpdir: Path) -> None:
    """find_registry's parent walk must not satisfy lookup from a sibling
    subtree containing a stat-registry.json. Direct-check semantics only.
    """
    inst_a = tmpdir / "instance-A" / ".q-system" / "agent-pipeline" / "bus" / "2026-05-21"
    inst_a.mkdir(parents=True)
    target = inst_a / "tl-content.json"
    target.write_text(json.dumps({"x_thread": ["42 handoffs"]}))

    inst_b = tmpdir / "instance-B" / "canonical"
    inst_b.mkdir(parents=True)
    (inst_b / "stat-registry.json").write_text(json.dumps({"version": 1, "stats": []}))

    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    proc = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "STAT_REGISTRY_PATH"},
    )
    assert proc.returncode == 2, (
        f"walk must not satisfy from sibling subtree; got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    assert "registry" in proc.stderr.lower()


def test_phrasing_does_not_launder_unapproved_numeric(tmpdir: Path) -> None:
    """A canonical phrasing in context must contain the token to validate it.
    'SIEMs cover 21% of ATT&CK ... missing 76%' must block 76%."""
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text(json.dumps({
        "x_thread": [
            "SIEMs cover 21% of ATT&CK and are missing 76% of ATT&CK.",
        ],
    }))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 2, f"context laundering must not pass 76%; got {rc}; err={err!r}"
    assert "76%" in err, f"expected 76% in error; got {err!r}"


def test_unreadable_file_fails_closed(tmpdir: Path) -> None:
    """A file the linter cannot read must fail closed, not be silently
    treated as clean."""
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_bytes(b"\xff\xfe\x00\x00\xff")
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 2, f"unreadable file must fail closed; got {rc}; err={err!r}"
    assert "unreadable" in err.lower() or "cannot read" in err.lower()


def test_malformed_json_fails_closed(tmpdir: Path) -> None:
    """Malformed in-scope JSON must fail closed, not silently pass."""
    bus = make_instance(tmpdir)
    target = bus / "tl-content.json"
    target.write_text("{ this is not json")
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    rc, _, err = run_hook(payload)
    assert rc == 2, f"malformed JSON must fail closed; got {rc}; err={err!r}"
    assert "malformed" in err.lower() or "json" in err.lower()


def test_dollar_range_extracted_as_one_token(tmpdir: Path) -> None:
    """`$25-75K` must extract as a single token so the upper bound is
    verified, not silently dropped."""
    bus = make_instance(tmpdir, stat_overrides=[
        {
            "id": "test-acv",
            "approved_numerics": ["$25-75K"],
            "canonical_phrasings": ["$25-75K pilot"],
        },
    ])
    target = bus / "tl-content.json"
    target.write_text(json.dumps({"linkedin_draft": "Pilot ACV is $25-75K."}))
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
    rc, _, err = run_hook(payload)
    assert rc == 0, f"$25-75K should pass with approved range; got {rc}; err={err!r}"

    target.write_text(json.dumps({"linkedin_draft": "Pilot ACV is $25-99K."}))
    rc, _, err = run_hook(payload)
    assert rc == 2, f"$25-99K must block (upper bound not approved); got {rc}; err={err!r}"


def test_self_test_passes(tmpdir: Path) -> None:
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"self-test failed: {proc.stdout}\n{proc.stderr}"


TESTS = [
    test_in_scope_bus_content_with_bad_stat_blocks,
    test_missing_registry_fails_closed,
    test_bootstrap_escape_allows_missing_registry,
    test_in_scope_bus_content_with_canonical_stat_passes,
    test_unvalidated_tag_allows_unknown_stat,
    test_skip_marker_bypasses_entire_file,
    test_metadata_bus_file_out_of_scope,
    test_non_content_fields_ignored,
    test_out_of_scope_path_silent,
    test_non_edit_tool_silent,
    test_cli_clean_file_exits_zero,
    test_cli_dirty_file_exits_two,
    test_cli_missing_registry_exits_two_not_one,
    test_find_registry_does_not_walk_into_sibling_subtree,
    test_phrasing_does_not_launder_unapproved_numeric,
    test_unreadable_file_fails_closed,
    test_malformed_json_fails_closed,
    test_dollar_range_extracted_as_one_token,
    test_self_test_passes,
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    for fn in TESTS:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try:
                fn(tmp)
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                print(f"  [FAIL] {fn.__name__}: {e}")
                failures.append((fn.__name__, str(e)))
            except Exception as e:
                print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
                failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
    print()
    if failures:
        print(f"{len(failures)} of {len(TESTS)} FAILED", file=sys.stderr)
        return 1
    print(f"all {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
