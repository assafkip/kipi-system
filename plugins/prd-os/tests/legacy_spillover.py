"""Seed a PRE-2026-09-12 minor spillover row, the shape `spillover add` wrote.

Founder, 2026-09-12: "New minor findings: fix or reject, never queue." Since
then `spillover add` refuses minor and low (test_spillover_files_linear.py pins
the refusal). The rows it wrote before that still exist in every live ledger
(kipi-system 1,318 open, consulting 529, chief 3, measured 2026-09-12), and the
gate, triage, resolve and reclassify behaviour for them is still load-bearing.
Suites that model those rows seed them here, field for field as the old `add`
wrote them, instead of through a CLI that now correctly refuses them.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LEGACY_SEVERITIES = ("minor", "low")


def _flag(args: tuple, name: str):
    return args[args.index(name) + 1] if name in args else None


def is_legacy_minor_add(args: tuple) -> bool:
    return (len(args) >= 2 and args[0] == "spillover" and args[1] == "add"
            and (_flag(args, "--severity") or "minor").strip().lower() in LEGACY_SEVERITIES)


def seed_legacy_add(repo: Path, args: tuple) -> subprocess.CompletedProcess:
    """Write the row the pre-2026-09-12 `spillover add <args>` wrote; mimic its stdout."""
    source, desc = _flag(args, "--source"), _flag(args, "--desc")
    sid = _flag(args, "--id") or f"sp-{hashlib.sha256((source + desc).encode()).hexdigest()[:8]}"
    rec = {"id": sid, "source": source, "description": desc,
           "severity": (_flag(args, "--severity") or "minor").strip().lower(),
           "status": "open",
           "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "owner": _flag(args, "--owner") or "sana"}
    ledger = Path(repo) / ".prd-os" / "spillover.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return subprocess.CompletedProcess(list(args), 0,
                                       stdout=json.dumps({"id": sid, "status": "open"}) + "\n",
                                       stderr="")
