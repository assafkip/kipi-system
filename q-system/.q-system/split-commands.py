#!/usr/bin/env python3
"""
Split commands.md into individual step files.

Reads the monolithic commands.md and extracts each step into its own file
in the steps/ directory. The step-loader.sh then reads from these individual
files instead of parsing the 2000+ line monolith each time.

Also generates a steps/INDEX.md that maps step IDs to files.

Run this whenever commands.md is updated:
  python3 q-system/.q-system/split-commands.py
"""

import re
import os
from pathlib import Path

COMMANDS_FILE = "q-system/.q-system/commands.md"
STEPS_DIR = "q-system/.q-system/steps"
INDEX_FILE = os.path.join(STEPS_DIR, "INDEX.md")


def extract_steps(content):
    """Extract step sections from commands.md."""
    lines = content.split("\n")
    steps = {}
    current_step = None
    current_lines = []

    # Patterns that indicate a new step
    step_patterns = [
        (r'\*\*Step\s+(\d+(?:\.\d+)?[a-z]?)\s*[-—:]', None),  # **Step 5.85 -
        (r'\*\*(\d+(?:\.\d+)?[a-z]?)\s*[-—]\s', None),  # **0b.5 -
        (r'Step\s+(\d+(?:\.\d+)?[a-z]?)\s*[-—:]', None),  # Step 11 -
    ]

    # Section headers (non-step content)
    section_pattern = re.compile(r'^#{1,3}\s')
    separator_pattern = re.compile(r'^---\s*$')

    for i, line in enumerate(lines):
        # Check if this line starts a new step
        matched_step = None
        for pattern, _ in step_patterns:
            m = re.search(pattern, line)
            if m:
                matched_step = m.group(1)
                break

        if matched_step:
            # Save previous step
            if current_step and current_lines:
                steps[current_step] = "\n".join(current_lines)

            current_step = matched_step
            current_lines = [line]
        elif current_step:
            # Check if we've hit a new major section or step
            if (line.startswith("**Step ") or line.startswith("**PHASE ")) and current_step and len(current_lines) > 3:
                # Could be a sub-section within the step, check if it's actually a new step
                is_new = False
                for pattern, _ in step_patterns:
                    if re.search(pattern, line):
                        is_new = True
                        break
                if is_new:
                    steps[current_step] = "\n".join(current_lines)
                    m = re.search(r'(\d+(?:\.\d+)?[a-z]?)', line)
                    if m:
                        current_step = m.group(1)
                    current_lines = [line]
                else:
                    current_lines.append(line)
            else:
                current_lines.append(line)

    # Save last step
    if current_step and current_lines:
        steps[current_step] = "\n".join(current_lines)

    return steps


def normalize_step_id(step_id):
    """Convert step ID to a safe filename."""
    return step_id.replace(".", "-")


def main():
    # Read commands.md
    with open(COMMANDS_FILE) as f:
        content = f.read()

    # Also extract the preamble (everything before the first step)
    lines = content.split("\n")
    preamble_lines = []
    for line in lines:
        if re.search(r'\*\*Step\s+\d|^- \*\*0[a-z]', line):
            break
        preamble_lines.append(line)

    # Write preamble
    preamble_path = os.path.join(STEPS_DIR, "00-preamble.md")
    with open(preamble_path, "w") as f:
        f.write("\n".join(preamble_lines))

    # Extract and write steps
    steps = extract_steps(content)
    index_lines = ["# Step Index\n", "| Step ID | File | Lines |", "|---------|------|-------|"]

    for step_id in sorted(steps.keys(), key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)]):
        safe_id = normalize_step_id(step_id)
        filename = f"step-{safe_id}.md"
        filepath = os.path.join(STEPS_DIR, filename)

        step_content = steps[step_id]
        line_count = len(step_content.split("\n"))

        with open(filepath, "w") as f:
            f.write(step_content)

        index_lines.append(f"| {step_id} | {filename} | {line_count} |")
        print(f"  {step_id} -> {filename} ({line_count} lines)")

    # Write index
    with open(INDEX_FILE, "w") as f:
        f.write("\n".join(index_lines) + "\n")

    print(f"\nSplit {len(steps)} steps into {STEPS_DIR}/")
    print(f"Index: {INDEX_FILE}")

    # Token savings estimate
    total_lines = sum(len(s.split("\n")) for s in steps.values())
    avg_lines = total_lines // len(steps) if steps else 0
    print(f"\nOriginal: {len(content.split(chr(10)))} lines (~{len(content)//4} tokens)")
    print(f"Average step: {avg_lines} lines (~{avg_lines * 80 // 4} tokens)")
    print(f"Loading 1 step instead of full file saves ~{(len(content)//4) - (avg_lines * 80 // 4)} tokens per step")


if __name__ == "__main__":
    main()
