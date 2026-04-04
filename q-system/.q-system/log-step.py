#!/usr/bin/env python3
"""Morning routine step logger.

Writes step completion to the morning log JSON file on disk.

Usage:
  python3 q-system/.q-system/log-step.py <date> <step_id> <status> <result> [error]

Examples:
  python3 q-system/.q-system/log-step.py 2026-03-14 0f_connection_check done "7/7 passed"
  python3 q-system/.q-system/log-step.py 2026-03-14 1_notion_actions failed "" "property Status not found"
  python3 q-system/.q-system/log-step.py 2026-03-14 5_site_metrics skipped "" "Monday only"
  python3 q-system/.q-system/log-step.py 2026-03-14 5.9_lead_sourcing partial "LinkedIn+Reddit only"

Special commands:
  python3 q-system/.q-system/log-step.py <date> init
  python3 q-system/.q-system/log-step.py <date> add-card <id> <type> <target> <draft_text> [url]
  python3 q-system/.q-system/log-step.py <date> deliver-cards
  python3 q-system/.q-system/log-step.py <date> gate-check <gate_step> <all_prior_done> [missing_steps]
  python3 q-system/.q-system/log-step.py <date> checksum-start <key> <value>
  python3 q-system/.q-system/log-step.py <date> checksum-end <key> <value>
  python3 q-system/.q-system/log-step.py <date> verify <claim> <source> <verified> <result>
"""

import json
import os
import sys
from datetime import datetime

# Resolve QROOT from script location (../ from .q-system/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.join(SCRIPT_DIR, "..")


def get_log_file(date):
    return os.path.join(QROOT, "output", f"morning-log-{date}.json")


def load_log(path):
    with open(path) as f:
        return json.load(f)


def save_log(path, log):
    with open(path, "w") as f:
        json.dump(log, f, indent=2)


def cmd_init(date):
    log_file = get_log_file(date)
    log = {
        "date": date,
        "session_start": datetime.now().isoformat(),
        "steps": {},
        "action_cards": [],
        "state_checksums": {"session_start": {}, "session_end": {}, "drift_detected": []},
        "verification_queue": [],
        "gates_checked": {},
        "audit": None,
    }
    save_log(log_file, log)
    print(f"Created: {log_file}")


def cmd_add_card(date, card_id, card_type, target, text, url=""):
    log_file = get_log_file(date)
    log = load_log(log_file)
    card = {
        "id": card_id,
        "type": card_type,
        "target": target,
        "draft_text": text[:200],
        "url": url if url else None,
        "card_delivered": False,
        "founder_confirmed": False,
        "logged_to": [],
    }
    log["action_cards"].append(card)
    save_log(log_file, log)
    print(f"Added card: {card_id} ({card_type}) -> {target}")


def cmd_deliver_cards(date):
    log_file = get_log_file(date)
    log = load_log(log_file)
    count = 0
    for card in log["action_cards"]:
        if not card.get("card_delivered"):
            card["card_delivered"] = True
            count += 1
    save_log(log_file, log)
    print(f"Marked {count} cards as delivered")


def cmd_gate_check(date, gate_step, all_prior, missing_str=""):
    log_file = get_log_file(date)
    log = load_log(log_file)
    missing_list = [s.strip() for s in missing_str.split(",") if s.strip()] if missing_str else []
    log["gates_checked"][gate_step] = {
        "checked": True,
        "all_prior_done": all_prior == "true",
        "missing": missing_list,
    }
    save_log(log_file, log)
    status = "PASS" if all_prior == "true" else "FAIL"
    msg = f"Gate {gate_step}: [{status}]"
    if missing_list:
        msg += f" Missing: {missing_list}"
    print(msg)


def cmd_checksum_start(date, key, value):
    log_file = get_log_file(date)
    log = load_log(log_file)
    log["state_checksums"]["session_start"][key] = value
    save_log(log_file, log)
    print(f"Checksum start: {key} = {value}")


def cmd_checksum_end(date, key, value):
    log_file = get_log_file(date)
    log = load_log(log_file)
    log["state_checksums"]["session_end"][key] = value
    start_val = log["state_checksums"]["session_start"].get(key)
    if start_val is not None and start_val != value:
        drift_msg = f"{key}: {start_val} -> {value}"
        if drift_msg not in log["state_checksums"]["drift_detected"]:
            log["state_checksums"]["drift_detected"].append(drift_msg)
    save_log(log_file, log)
    print(f"Checksum end: {key} = {value}")


def cmd_verify(date, claim, source, verified_str, result=""):
    log_file = get_log_file(date)
    log = load_log(log_file)
    entry = {
        "claim": claim,
        "source_file": source,
        "verified": verified_str == "true",
        "verification_method": "",
        "result": result if result else None,
    }
    found = False
    for i, v in enumerate(log["verification_queue"]):
        if v["claim"] == claim:
            log["verification_queue"][i] = entry
            found = True
            break
    if not found:
        log["verification_queue"].append(entry)
    save_log(log_file, log)
    status = "VERIFIED" if verified_str == "true" else "UNVERIFIED"
    print(f"Verification: [{status}] {claim}")


def cmd_log_step(date, step_id, status, result="", error=""):
    log_file = get_log_file(date)
    log = load_log(log_file)
    log["steps"][step_id] = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "result": result if result else None,
        "error": error if error else None,
    }
    save_log(log_file, log)
    icon = {"done": "OK", "failed": "FAIL", "skipped": "SKIP", "partial": "WARN"}.get(status, "??")
    msg = f"[{icon}] {step_id}: {status}"
    if result:
        msg += f" - {result}"
    if error:
        msg += f" ({error})"
    print(msg)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 q-system/.q-system/log-step.py <date> <step_id> <status> <result> [error]", file=sys.stderr)
        sys.exit(1)

    date = sys.argv[1]
    cmd = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "init":
        cmd_init(date)
    elif cmd == "add-card":
        cmd_add_card(date, sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7] if len(sys.argv) > 7 else "")
    elif cmd == "deliver-cards":
        cmd_deliver_cards(date)
    elif cmd == "gate-check":
        cmd_gate_check(date, sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "")
    elif cmd == "checksum-start":
        cmd_checksum_start(date, sys.argv[3], sys.argv[4])
    elif cmd == "checksum-end":
        cmd_checksum_end(date, sys.argv[3], sys.argv[4])
    elif cmd == "verify":
        cmd_verify(date, sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] if len(sys.argv) > 6 else "")
    else:
        # Default: log a step
        step_id = sys.argv[2] if len(sys.argv) > 2 else None
        status = sys.argv[3] if len(sys.argv) > 3 else None
        if not step_id or not status:
            print("Usage: python3 q-system/.q-system/log-step.py <date> <step_id> <status> <result> [error]", file=sys.stderr)
            sys.exit(1)
        result = sys.argv[4] if len(sys.argv) > 4 else ""
        error = sys.argv[5] if len(sys.argv) > 5 else ""
        cmd_log_step(date, step_id, status, result, error)


if __name__ == "__main__":
    main()
