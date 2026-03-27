import re
from pathlib import Path


class StepLoader:
    """Loads step definitions for the morning routine. Replaces step-loader.sh."""

    _COMMAND_PATTERNS: dict[str, str] = {
        "5.85": "Step 5.85",
        "5.86": "Step 5.86",
        "5.9": "Step 5.9 -",
        "5.9b": r"Step 5\.9b|Daily Engagement Hitlist",
        "4": "Step 4:",
        "4.1": "Step 4.1",
        "3": r"Step 3 —|Step 3:",
        "3.8": "Step 3.8",
        "0b.5": "0b.5 - Loop",
        "8": r"Step 8 —|GATE CHECK.*step 8",
        "9": "Step 9 —",
        "11": r"Step 11|MANDATORY FINAL STEP",
    }

    _SECTION_END = re.compile(r"^\*\*Step \d|^---$|^##")

    def __init__(self, steps_dir: Path, commands_file: Path) -> None:
        self.steps_dir = steps_dir
        self.commands_file = commands_file

    def load(self, step_id: str) -> str:
        result = self._load_from_file(step_id)
        if result is not None:
            return result
        result = self._load_from_commands(step_id)
        if result is not None:
            return result
        return f"Step {step_id} not found in step files or commands.md"

    def _load_from_file(self, step_id: str) -> str | None:
        safe_id = step_id.replace(".", "-")
        path = self.steps_dir / f"step-{safe_id}.md"
        if path.is_file():
            return path.read_text()
        return None

    def _load_from_commands(self, step_id: str) -> str | None:
        if not self.commands_file.is_file():
            return None
        text = self.commands_file.read_text()
        lines = text.splitlines()

        pattern_str = self._COMMAND_PATTERNS.get(step_id, f"Step {step_id}")
        pattern = re.compile(pattern_str, re.IGNORECASE)

        start = None
        for i, line in enumerate(lines):
            if pattern.search(line):
                start = i
                break

        if start is None:
            return None

        collected = [lines[start]]
        for j in range(start + 1, min(start + 80, len(lines))):
            if self._SECTION_END.search(lines[j]):
                break
            collected.append(lines[j])

        return "\n".join(collected)

    def list_available(self) -> list[str]:
        ids = []
        if not self.steps_dir.is_dir():
            return ids
        for path in sorted(self.steps_dir.glob("step-*.md")):
            name = path.stem  # e.g. "step-5-85"
            raw = name[len("step-"):]  # e.g. "5-85"
            # Convert first hyphen back to dot for the step ID,
            # but only the first one to handle IDs like "0b.5" → "0b-5"
            step_id = raw.replace("-", ".", 1)
            ids.append(step_id)
        return ids
