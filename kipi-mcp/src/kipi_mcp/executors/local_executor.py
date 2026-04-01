import json
import logging
from pathlib import Path
from kipi_mcp.executors import ExecutorResult

logger = logging.getLogger(__name__)


def execute(config: dict, allowed_base: Path | None = None) -> ExecutorResult:
    """Read records from a local file.

    Args:
        config: Source config with file_path and format.
        allowed_base: If set, file_path must be within this directory.
    """
    file_path = Path(config.get("file_path", "")).resolve()
    fmt = config.get("format", "json")

    # Path traversal protection
    if allowed_base is not None:
        allowed = allowed_base.resolve()
        try:
            file_path.relative_to(allowed)
        except ValueError:
            return ExecutorResult(
                error=f"Path traversal blocked: {file_path} is outside {allowed}"
            )

    try:
        if not file_path.exists():
            return ExecutorResult(error=f"File not found: {file_path}")

        text = file_path.read_text().strip()
        if not text:
            return ExecutorResult()

        if fmt == "jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
            records = data if isinstance(data, list) else [data]

        return ExecutorResult(records=records)

    except Exception as exc:
        logger.error("Local executor error: %s", exc, exc_info=True)
        return ExecutorResult(error=str(exc))
