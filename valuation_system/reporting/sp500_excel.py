from __future__ import annotations

import os
import subprocess
from pathlib import Path


BUILDER = Path(__file__).with_name("build_sp500_workbook.mjs")


def export_sp500_excel(input_json: str | Path, output_xlsx: str | Path, preview_dir: str | Path | None = None) -> Path:
    source = Path(input_json).resolve()
    target = Path(output_xlsx).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    preview = Path(preview_dir).resolve() if preview_dir else target.parent / "sp500_previews"
    preview.mkdir(parents=True, exist_ok=True)
    node = os.environ.get("VALUATION_NODE", "node")
    completed = subprocess.run(
        [node, str(BUILDER), str(source), str(target), str(preview)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"S&P 500 workbook export failed:\n{completed.stdout}\n{completed.stderr}")
    print(completed.stdout)
    return target
