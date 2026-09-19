#!/usr/bin/env python3
"""design-engine-door.py -- PreToolUse and PostToolUse on the Skill tool (dc-18, dc-19, ASK-1796).

/design-chain is the one design command (founder, 2026-09-18). The other design skills stay
installed as ENGINES the chain calls at a stage. This hook refuses a listed engine when the
session has no active design-chain round, and names /design-chain. An unlisted skill passes.

Active round: the gate's session ledger (STATE_DIR/<session>.json) key "round", set by
design-chain-gate.py when a file is written in a round dir under a design-chain.json; active while
that dir exists and holds no receipts.json (unsealed).

Registry: design-engines.json beside this file. Unreadable registry: unlisted names pass, the
coded CORE list still refuses, so a broken file cannot open the door for the main engines.

Exit contract: 0 pass, 2 block (stderr to Claude). Kept import-light: the no-match path must stay
under 50 ms (asserted in test_design_engine_door.py).
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "design-engines.json"
STATE_DIR = Path(os.environ.get("DESIGN_CHAIN_STATE", os.path.expanduser("~/.config/kipi/design-chain")))
CORE = frozenset({"frontend-design", "ui-ux-pro-max", "design", "brand", "design-room",
                  "hyperframes", "hyperframes-animation", "deck-ai"})


def listed() -> set:
    try:
        data = json.loads(REGISTRY.read_text())
        names = {e["skill"] for e in data["engines"] if isinstance(e, dict) and isinstance(e.get("skill"), str)}
    except (OSError, ValueError, KeyError, TypeError):
        return set(CORE)
    return names | CORE


def active_round(session_id: str) -> Path | None:
    p = STATE_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session_id or 'nosession')}.json"
    try:
        rd = json.loads(p.read_text()).get("round")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(rd, str) or not rd:
        return None
    rd = Path(rd)
    # open until sealed, and only while it is still a round (a deleted brief closed nothing, adv-4)
    return rd if (rd / "brief.md").is_file() and not (rd / "receipts.json").exists() else None


def canonical(raw: str) -> str:
    """The engine a Skill call names: the last non-empty ':' part, case, spaces, slashes and '_' vs '-'
    folded ("Frontend-Design", "frontend-design:", "/frontend_design" all missed the list, adv-5)."""
    parts = [p for p in raw.strip().split(":") if p.strip()]
    return (parts[-1] if parts else "").strip().strip("/").casefold().replace("_", "-")


def record(payload: dict) -> None:
    """PostToolUse (dc-19): an engine that ran inside the open round appends {skill, raw, session, at}
    to that round's engines.jsonl, so a technique crediting an engine can be checked against a run.
    The copied-animation incident credited hyperframes-animation with motion copied from a reference."""
    raw = str((payload.get("tool_input") or {}).get("skill") or "").strip()
    name = canonical(raw)
    if not name or name not in listed():
        return
    sid = payload.get("session_id", "")
    rd = active_round(sid)
    if rd is None:
        return
    import time
    try:
        with open(rd / "engines.jsonl", "a") as f:
            f.write(json.dumps({"skill": name, "raw": raw, "session": sid,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    except OSError:
        return            # the round went away mid-call: no record, and seal refuses the credit


def decide(payload: dict) -> tuple[int, str]:
    if payload.get("tool_name") != "Skill":
        return 0, ""
    if payload.get("hook_event_name") == "PostToolUse":
        record(payload)
        return 0, ""
    raw = str((payload.get("tool_input") or {}).get("skill") or "").strip()
    name = canonical(raw)                  # "kipi-design:brand" is the brand engine
    if not name or name not in listed():
        return 0, ""
    if active_round(payload.get("session_id", "")) is not None:
        return 0, ""
    return 2, (f"'{raw}' is a design engine, and this session has no open design-chain round. Start with "
               f"/design-chain; it calls {name} at its stage and records it.")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    rc, msg = decide(payload if isinstance(payload, dict) else {})
    if msg:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
