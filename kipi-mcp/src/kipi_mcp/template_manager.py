from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Optional


class TemplateManager:
    def __init__(
        self,
        templates_dir: Path,
        output_dir: Path,
        schedule_template: Optional[Path] = None,
        verify_schedule_fn=None,
    ):
        self.templates_dir = Path(templates_dir)
        self.output_dir = Path(output_dir)
        self.schedule_template = Path(schedule_template) if schedule_template else None
        self.verify_schedule_fn = verify_schedule_fn

    def create(self, template_name: str, output_name: str) -> dict:
        src = self.templates_dir / template_name
        dest = self.output_dir / output_name

        if not src.is_dir():
            raise ValueError(f"Template not found: {template_name}")
        if dest.exists():
            raise ValueError(f"Output already exists: {output_name}")

        shutil.copytree(src, dest)

        today = date.today().isoformat()
        files = []
        for p in dest.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(dest)))
                if p.suffix == ".md":
                    text = p.read_text()
                    text = text.replace("{{DATE}}", today)
                    text = text.replace("{{OUTPUT_NAME}}", output_name)
                    p.write_text(text)

        return {"created": str(dest), "files": sorted(files)}

    def list_templates(self) -> list[str]:
        if not self.templates_dir.is_dir():
            return []
        return sorted(d.name for d in self.templates_dir.iterdir() if d.is_dir())

    def build_schedule(self, json_file: str, output_file: str = "") -> dict:
        if self.schedule_template is None:
            raise ValueError("No schedule template configured")

        data = json.loads(Path(json_file).read_text())

        if self.verify_schedule_fn is not None:
            try:
                self.verify_schedule_fn(data)
            except Exception as e:
                return {"error": str(e), "blocked": True}

        html_template = self.schedule_template.read_text()
        result = html_template.replace(
            "__SCHEDULE_DATA__", json.dumps(data, ensure_ascii=True)
        )

        if output_file:
            Path(output_file).write_text(result)
            return {"built": output_file}

        return {"html": result}
