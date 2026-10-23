#!/usr/bin/env python3
"""Reproducer-first tests for the design-partner-only wiring of memory auto-capture
(issue autocapture-instance-guard, PRD prd-memory-autocapture-2026-07-04, finding-3).

Proves the referee cannot enable itself beyond the design partner:
- the public allowlist config names nobody; the partner is in a private file  -> test_allowlist_is_partner_only
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
import tempfile
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
    # The public config enables NOBODY. The design partner is a client, so its
    # instance lives in the private allowlist outside this public repo (ASK-2058).
    cfg = json.loads(CONFIG.read_text())
    _check("allowlist_is_partner_only",
           cfg.get("enabled_instances") == [], f"cfg={cfg}")


def test_gate_off_off_partner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / "autocapture-instances.txt"
        private.write_text("partner_instance\n")
        _check("gate_off_off_partner",
               mac.is_enabled(config_path=CONFIG, instance_id="kipi-system",
                              private_path=private) is False)


def test_gate_on_for_partner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / "autocapture-instances.txt"
        private.write_text("# the design partner\npartner_instance\n")
        _check("gate_on_for_partner",
               mac.is_enabled(config_path=CONFIG, instance_id="partner_instance",
                              private_path=private) is True)
        missing = Path(tmp) / "absent.txt"
        _check("gate_off_without_private_list",
               mac.is_enabled(config_path=CONFIG, instance_id="partner_instance",
                              private_path=missing) is False)


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
