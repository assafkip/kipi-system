from __future__ import annotations
from pathlib import Path


class GuideLoader:
    """Serves marketing/growth methodology guides on demand."""

    def __init__(self, guides_dir: Path):
        self.guides_dir = guides_dir

    def list_topics(self) -> list[str]:
        """Return all available guide topic names."""
        if not self.guides_dir.exists():
            return []
        return sorted(
            d.name for d in self.guides_dir.iterdir()
            if d.is_dir() and (d / "methodology.md").exists()
        )

    def load(self, topic: str, section: str = "full") -> str:
        """Load a guide by topic and optional section.

        Args:
            topic: Guide name (e.g. "copywriting", "revops")
            section: "full" (methodology + all refs), "methodology" (core only),
                     or a specific reference file name (e.g. "scoring-models")
        """
        topic_dir = self.guides_dir / topic
        if not topic_dir.exists():
            available = self.list_topics()
            raise FileNotFoundError(
                f"Guide '{topic}' not found. Available: {', '.join(available)}"
            )

        methodology = topic_dir / "methodology.md"
        if not methodology.exists():
            raise FileNotFoundError(f"No methodology.md in guide '{topic}'")

        if section == "methodology":
            return methodology.read_text()

        if section == "full":
            parts = [methodology.read_text()]
            refs_dir = topic_dir / "references"
            if refs_dir.exists():
                for ref_file in sorted(refs_dir.glob("*.md")):
                    parts.append(f"\n---\n# Reference: {ref_file.stem}\n\n{ref_file.read_text()}")
            return "\n".join(parts)

        # Specific reference section
        refs_dir = topic_dir / "references"
        candidates = [
            refs_dir / f"{section}.md",
            refs_dir / f"{section}",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.read_text()

        available_refs = []
        if refs_dir.exists():
            available_refs = [f.stem for f in refs_dir.glob("*.md")]
        raise FileNotFoundError(
            f"Section '{section}' not found in guide '{topic}'. "
            f"Available sections: methodology, {', '.join(available_refs)}"
        )
