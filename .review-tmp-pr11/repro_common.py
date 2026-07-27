"""Load the PR-head fleet-health-daily.py as a module. Read-only, no repo writes."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "scripts" / "fleet-health-daily.py"

spec = importlib.util.spec_from_file_location("fh", SRC)
fh = importlib.util.module_from_spec(spec)
sys.modules["fh"] = fh
spec.loader.exec_module(fh)
