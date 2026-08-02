from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from valuation_system.config import EXCEL_BUILDER
from valuation_system.models.valuation_results import ValuationResult


def export_excel(result: ValuationResult, output_path: str | Path) -> Path:
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    json_path = path.with_suffix(".model.json")
    json_path.write_text(json.dumps(result.to_dict(), indent=2, allow_nan=False))
    node = os.environ.get("VALUATION_NODE", "node")
    completed = subprocess.run(
        [node, str(EXCEL_BUILDER), str(json_path), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(f"Workbook export failed:\n{completed.stdout}\n{completed.stderr}")
    return path
