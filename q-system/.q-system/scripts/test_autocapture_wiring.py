#!/usr/bin/env python3
"""Reproducer-first tests for the design-partner-only wiring of memory auto-capture
(issue autocapture-instance-guard, PRD prd-memory-autocapture-2026-07-04, finding-3).

Proves the referee cannot enable itself beyond the design partner:
- the allowlist config names only 4_points_consulting  -> test_allowlist_is_partner_only
- capture is OFF on a non-allowlisted instance, ON for the partner
  -> test_gate_off_off_partner / test_gate_on_for_partner
- the Stop-hook entry is wired in BOTH settings.json and settings-template.json
  (sync), so shipping fleet-wide leaves it inert, not missing  -> test_wired_in_both
- the entry is advisory (guarded, `|| true`), never a blocking exit-2
  -> test_entry_is_advisory
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import memory_autocapture as mac  # noqa: E402

QROOT = (HERE / ".." / "..").resolve()          # q-system/
REPO = QROOT.parent                              # repo root
CONFIG = HERE / "autocapture_config.json"
SETTINGS = REPO / ".claude" / "settings.json"
TEMPLATE = REPO / "settings-template.json"
SCRIPT_TOKEN = "memory_autocapture.py"

_failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    print(f"PASS {name}" if cond else f"FAIL {name} {detail}")
    if not cond:
        _failures.append(name)


def _stop_commands(settings_path: Path) -> list[str]:
    data = json.loads(settings_path.read_text())
    cmds: list[str] = []
    for group in data.get("hooks", {}).get("Stop", []):
        for hook in group.get("hooks", []):
            cmd = hook.get("command")
            if cmd:
                cmds.append(cmd)
    return cmds


def test_allowlist_is_partner_only() -> None:
    cfg = json.loads(CONFIG.read_text())
    _check("allowlist_is_partner_only",
           cfg.get("enabled_instances") == ["4_points_consulting"], f"cfg={cfg}")


def test_gate_off_off_partner() -> None:
    _check("gate_off_off_partner",
           mac.is_enabled(config_path=CONFIG, instance_id="kipi-system") is False)


def test_gate_on_for_partner() -> None:
    _check("gate_on_for_partner",
           mac.is_enabled(config_path=CONFIG, instance_id="4_points_consulting") is True)


def test_wired_in_both() -> None:
    in_settings = any(SCRIPT_TOKEN in c for c in _stop_commands(SETTINGS))
    in_template = any(SCRIPT_TOKEN in c for c in _stop_commands(TEMPLATE))
    _check("wired_in_both", in_settings and in_template,
           f"settings={in_settings} template={in_template}")


def test_entry_is_advisory() -> None:
    ok = True
    for path in (SETTINGS, TEMPLATE):
        for cmd in _stop_commands(path):
            if SCRIPT_TOKEN in cmd and "|| true" not in cmd:
                ok = False
    _check("entry_is_advisory", ok, "capture Stop entry must end with '|| true'")


def main() -> int:
    test_allowlist_is_partner_only()
    test_gate_off_off_partner()
    test_gate_on_for_partner()
    test_wired_in_both()
    test_entry_is_advisory()
    if _failures:
        print(f"\n{len(_failures)} FAILURES: {_failures}")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
