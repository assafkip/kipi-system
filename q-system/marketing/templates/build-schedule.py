#!/usr/bin/env python3
"""Build daily schedule HTML from JSON data + template.

Usage: python3 build-schedule.py <json-file> [output-file]
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(SCRIPT_DIR, "daily-schedule-template.html")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <json-file> [output-file]", file=sys.stderr)
        sys.exit(1)

    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isfile(json_file):
        print(f"Error: JSON file not found: {json_file}", file=sys.stderr)
        sys.exit(1)

    # VERIFICATION GATE: Check schedule JSON before building HTML
    # Based on "Lost in the Middle" research - don't trust LLM self-reporting.
    verify_script = os.path.join(SCRIPT_DIR, "..", "..", ".q-system", "verify-schedule.py")
    verify_script = os.path.normpath(verify_script)
    if os.path.isfile(verify_script):
        print("Verifying schedule data...")
        result = subprocess.run([sys.executable, verify_script, json_file])
        if result.returncode != 0:
            print("")
            print("HTML BUILD BLOCKED. Fix the errors above and rebuild.")
            print("The LLM cannot bypass this check.")
            sys.exit(1)

    if not os.path.isfile(TEMPLATE):
        print(f"Error: Template not found: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    with open(TEMPLATE) as f:
        template = f.read()

    with open(json_file) as f:
        data = json.load(f)

    js_json = json.dumps(data, ensure_ascii=True)
    result = template.replace("__SCHEDULE_DATA__", js_json)

    if output_file:
        with open(output_file, "w") as f:
            f.write(result)
        print(f"Built: {output_file}")
    else:
        print(result)


if __name__ == "__main__":
    main()
