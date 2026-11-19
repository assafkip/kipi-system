#!/usr/bin/env python3
"""PreToolUse hook shim: the send-time voice check (ASK-4969 part 3).

This file only LOCATES the entry point and hands over. The check is
plugins/kipi-core/scripts/voice_send_check.py, which calls voice_full_gate.check (#851).
why a shim and not a copy: the settings merge gives a plugins/ path an instance-owned identity,
so the template can only wire a q-system/ script. The shim is that script; no logic lives here.

Where kipi-core is found, first hit wins, one function:
  1. <instance>/plugins/kipi-core/scripts   (the synced copy; the skeleton itself has one)
  2. ~/.claude/plugins/marketplaces/kipi/plugins/kipi-core/scripts   (the marketplace clone)
Neither present: exit 2. A send gate that cannot find its engine must not pass.
"""
import os
import runpy
import sys
from pathlib import Path


def find_scripts_dir() -> "Path | None":
    here = Path(__file__).resolve()
    candidates = [here.parents[3] / "plugins" / "kipi-core" / "scripts",
                  Path.home() / ".claude" / "plugins" / "marketplaces" / "kipi"
                  / "plugins" / "kipi-core" / "scripts"]
    for c in candidates:
        if (c / "voice_send_check.py").is_file():
            return c
    return None


def main() -> int:
    scripts = find_scripts_dir()
    if scripts is None:
        print("voice-send-check: voice_send_check.py not found under plugins/kipi-core or the "
              "marketplace clone: the send gate cannot run", file=sys.stderr)
        return 2
    sys.path.insert(0, str(scripts))
    sys.argv = [str(scripts / "voice_send_check.py"), "--hook"]
    try:
        runpy.run_path(str(scripts / "voice_send_check.py"), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
