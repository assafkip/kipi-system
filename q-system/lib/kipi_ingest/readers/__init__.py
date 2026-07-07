"""Format readers. Each returns `(list[Block], ReadResult)`.

Stdlib-only readers (markdown, csv) import at module load. Heavy-format readers
(xlsx, pdf, docx) import their parse library lazily inside the function and raise
a clear error if it is absent, so importing this package never requires openpyxl
or a PDF engine.
"""
from __future__ import annotations

from .markdown import read_md
from .csv_reader import read_csv
from .xlsx_reader import read_xlsx  # openpyxl imported lazily inside read_xlsx

__all__ = ["read_md", "read_csv", "read_xlsx"]
