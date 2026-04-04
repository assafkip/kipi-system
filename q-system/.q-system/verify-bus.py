#!/usr/bin/env python3
"""
Bus file verification harness. Run between pipeline phases to ensure
expected files exist and have valid structure.

Usage:
  python3 verify-bus.py <date> <phase>

Phases: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

Exit codes:
  0 = all expected files present and valid
  1 = missing or invalid files (prints which ones)
"""

import json
import os
import re
import sys
from datetime import datetime

# Resolve {{QROOT}} relative to this script's location (../ from .q-system/)
QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCHEMAS_DIR = os.path.join(QROOT, ".q-system", "agent-pipeline", "schemas")
CADENCE_CONFIG_PATH = os.path.join(
    QROOT, ".q-system", "agent-pipeline", "agents", "_cadence-config.json"
)

CURRENT_BUS_VERSION = 1

# ---------------------------------------------------------------------------
# Lightweight JSON Schema validator (stdlib only, no pip deps)
# Supports: required, type, const, enum, pattern, minimum, maximum,
#           nested objects with their own required/properties, arrays
# ---------------------------------------------------------------------------

def _check_type(value, expected):
    """Check value matches a JSON Schema type (or list of types)."""
    if isinstance(expected, list):
        return any(_check_type(value, t) for t in expected)
    mapping = {
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
        "array": list,
        "object": dict,
        "null": type(None),
    }
    py_type = mapping.get(expected)
    if py_type is None:
        return True  # unknown type, skip
    if expected == "integer" and isinstance(value, bool):
        return False  # bool is subclass of int in Python
    return isinstance(value, py_type)


def _validate_obj(data, schema, path=""):
    """Recursively validate data against a JSON Schema fragment.

    Returns (True, "ok") or (False, "reason").
    """
    # --- bus_version const check ---
    if "const" in schema:
        if data != schema["const"]:
            return False, f"{path}: expected const {schema['const']}, got {data}"

    # --- type check ---
    if "type" in schema:
        if not _check_type(data, schema["type"]):
            return False, f"{path}: expected type {schema['type']}, got {type(data).__name__}"

    # --- enum check ---
    if "enum" in schema:
        if data not in schema["enum"]:
            return False, f"{path}: value {data!r} not in enum {schema['enum']}"

    # --- pattern check (strings only) ---
    if "pattern" in schema and isinstance(data, str):
        if not re.search(schema["pattern"], data):
            return False, f"{path}: value {data!r} does not match pattern {schema['pattern']}"

    # --- numeric range ---
    if "minimum" in schema and isinstance(data, (int, float)):
        if data < schema["minimum"]:
            return False, f"{path}: {data} < minimum {schema['minimum']}"
    if "maximum" in schema and isinstance(data, (int, float)):
        if data > schema["maximum"]:
            return False, f"{path}: {data} > maximum {schema['maximum']}"

    # --- object: required + properties ---
    if isinstance(data, dict) and "properties" in schema:
        for req in schema.get("required", []):
            if req not in data:
                return False, f"{path}: missing required field '{req}'"
        for key, prop_schema in schema["properties"].items():
            if key in data:
                ok, reason = _validate_obj(data[key], prop_schema, path=f"{path}.{key}")
                if not ok:
                    return False, reason

    # --- array: items ---
    if isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data):
            ok, reason = _validate_obj(item, schema["items"], path=f"{path}[{i}]")
            if not ok:
                return False, reason

    return True, "ok"


def validate_against_schema(data, bus_filename):
    """Validate bus file data against its JSON Schema if one exists.

    Returns (True, "ok") if valid or no schema found,
            (False, "reason") if schema validation fails.
    """
    schema_name = bus_filename.replace(".json", ".schema.json")
    schema_path = os.path.join(SCHEMAS_DIR, schema_name)
    if not os.path.isfile(schema_path):
        return True, "no schema"
    try:
        with open(schema_path) as fh:
            schema = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"schema load error: {e}"

    return _validate_obj(data, schema, path=bus_filename)


# ---------------------------------------------------------------------------
# Cadence config loader (day-of-week rules)
# ---------------------------------------------------------------------------

def load_day_rules():
    """Load day_rules from _cadence-config.json.

    Expected format:
      { "day_rules": { "tuesday": { "4": ["tl-content.json"] }, ... } }

    Returns dict mapping lowercase day name -> { phase_int: [filenames] }
    or None if file missing / unparseable (triggers hardcoded fallback).
    """
    if not os.path.isfile(CADENCE_CONFIG_PATH):
        return None
    try:
        with open(CADENCE_CONFIG_PATH) as fh:
            cfg = json.load(fh)
        raw = cfg.get("day_rules")
        if not isinstance(raw, dict):
            return None
        # Normalize phase keys to int
        result = {}
        for day, phases in raw.items():
            result[day.lower()] = {
                int(k): v for k, v in phases.items() if isinstance(v, list)
            }
        return result
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def apply_day_rules(day_of_week, phase, required, optional, day_rules):
    """Promote optional files to required based on day-of-week rules.

    Mutates required and optional lists in place.
    If day_rules is None, falls back to hardcoded defaults.
    """
    if day_rules is not None:
        promotions = day_rules.get(day_of_week, {}).get(phase, [])
        for f in promotions:
            if f in optional:
                optional.remove(f)
            if f not in required:
                required.append(f)
        return

    # Hardcoded fallback: tl-content.json required on Tue/Thu in Phase 4
    if phase == 4 and day_of_week in ("tuesday", "thursday"):
        if "tl-content.json" in optional:
            optional.remove("tl-content.json")
        if "tl-content.json" not in required:
            required.append("tl-content.json")


# ---------------------------------------------------------------------------
# Main verification
# ---------------------------------------------------------------------------

def verify(date, phase):
    bus_dir = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus", date)

    if not os.path.isdir(bus_dir):
        print(f"FAIL: Bus directory does not exist: {bus_dir}")
        return False

    # Define expected files per phase (cumulative)
    phase_files = {
        0: {
            "required": ["preflight.json", "energy.json"],
            "checks": {
                "preflight.json": lambda d: d.get("ready") == True,
                "energy.json": lambda d: d.get("level") in range(1, 6),
            }
        },
        1: {
            "required": ["calendar.json", "gmail.json", "notion.json"],
            "optional": ["vc-pipeline.json", "content-metrics.json", "copy-diffs.json"],
            "checks": {
                "calendar.json": lambda d: "today" in d or "this_week" in d,
                "gmail.json": lambda d: "emails" in d,
                "notion.json": lambda d: "contacts" in d and "actions" in d,
                "canonical-digest.json": lambda d: "talk_tracks" in d and "objections" in d and "decisions" in d,
            }
        },
        2: {
            "required": ["meeting-prep.json", "warm-intros.json"],
            "checks": {}
        },
        3: {
            "required": ["linkedin-posts.json", "linkedin-dms.json", "dp-pipeline.json", "prospect-pipeline.json"],
            "optional": ["behavioral-signals.json", "prospect-activity.json"],
            "checks": {
                "linkedin-posts.json": lambda d: "posts" in d,
                "linkedin-dms.json": lambda d: "dms" in d,
                "behavioral-signals.json": lambda d: "signals" in d,
                "prospect-pipeline.json": lambda d: "counts" in d and "all_prospects" in d,
            }
        },
        4: {
            "required": ["signals.json"],
            "optional": ["value-routing.json", "post-visuals.json", "promo.json", "tl-content.json"],
            "checks": {
                "signals.json": lambda d: "selected_signal" in d or "linkedin_draft" in d,
            }
        },
        5: {
            "required": ["temperature.json", "leads.json", "hitlist.json"],
            "optional": ["pipeline-followup.json", "loop-review.json"],
            "checks": {
                "hitlist.json": lambda d: "actions" in d and len(d["actions"]) > 0,
                "temperature.json": lambda d: "scores" in d or "prospects" in d,
            }
        },
        6: {
            "required": ["compliance.json", "positioning.json"],
            "optional": ["sycophancy-audit.json", "client-deliverables.json", "marketing-health.json"],
            "checks": {
                "compliance.json": lambda d: "overall_pass" in d or "items_checked" in d,
                "sycophancy-audit.json": lambda d: d.get("overall") in ("pass", "watch", "alert") and d.get("residual_risk_acknowledged") == True,
            }
        },
        7: {
            "required": [],
            "optional": ["outreach-queue.json"],
            "checks": {
                "outreach-queue.json": lambda d: "queue" in d,
            }
        },
        8: {
            "required": [],
            "optional": [],
            "checks": {}
        },
        9: {
            "required": [],
            "optional": ["notion-push.json", "daily-checklists.json"],
            "checks": {}
        },
    }

    if phase not in phase_files:
        print(f"Unknown phase: {phase}")
        return True

    spec = phase_files[phase]
    required = list(spec.get("required", []))
    optional = list(spec.get("optional", []))

    # Day-of-week promotion via cadence config (or hardcoded fallback)
    day_of_week = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
    day_rules = load_day_rules()
    apply_day_rules(day_of_week, phase, required, optional, day_rules)

    checks = spec.get("checks", {})

    all_pass = True
    results = []

    for f in required:
        path = os.path.join(bus_dir, f)
        if not os.path.isfile(path):
            results.append(f"  FAIL [required] {f}: MISSING")
            all_pass = False
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            if "error" in data:
                results.append(f"  WARN [required] {f}: has error key ({data['error']})")
            elif "platform_errors" in data and data["platform_errors"]:
                platforms = ", ".join(data["platform_errors"].keys())
                results.append(f"  WARN [required] {f}: platform_errors for {platforms}")
            elif f in checks and not checks[f](data):
                results.append(f"  FAIL [required] {f}: structure check failed")
                all_pass = False
            else:
                results.append(f"  OK   [required] {f}")
            # Schema validation (WARN only during migration)
            schema_ok, schema_reason = validate_against_schema(data, f)
            if not schema_ok:
                results.append(f"  WARN [schema]   {f}: {schema_reason}")
            elif schema_reason != "no schema":
                results.append(f"  OK   [schema]   {f}")
        except json.JSONDecodeError as e:
            results.append(f"  FAIL [required] {f}: invalid JSON ({e})")
            all_pass = False

    for f in optional:
        path = os.path.join(bus_dir, f)
        if not os.path.isfile(path):
            results.append(f"  SKIP [optional] {f}: not present")
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            if "error" in data:
                results.append(f"  WARN [optional] {f}: has error key")
            elif f in checks and not checks[f](data):
                results.append(f"  WARN [optional] {f}: structure check failed")
            else:
                results.append(f"  OK   [optional] {f}")
            # Schema validation (WARN only during migration)
            schema_ok, schema_reason = validate_against_schema(data, f)
            if not schema_ok:
                results.append(f"  WARN [schema]   {f}: {schema_reason}")
            elif schema_reason != "no schema":
                results.append(f"  OK   [schema]   {f}")
        except json.JSONDecodeError:
            results.append(f"  WARN [optional] {f}: invalid JSON")

    print(f"Phase {phase} bus verification ({date}):")
    for r in results:
        print(r)
    cadence_src = "cadence-config" if day_rules is not None else "hardcoded"
    print(f"Day rules: {day_of_week} (source: {cadence_src})")
    print(f"Result: {'PASS' if all_pass else 'FAIL'}")
    return all_pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <date> <phase>")
        sys.exit(1)
    date = sys.argv[1]
    phase = int(sys.argv[2])
    success = verify(date, phase)
    sys.exit(0 if success else 1)
