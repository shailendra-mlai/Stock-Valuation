"""Run the standardized three-period S&P 500 APV screen and export its summary workbook."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from valuation_system.data.sp500_batch import CONSTITUENTS_URL, run_sp500_batch
from valuation_system.reporting.sp500_excel import export_sp500_excel


def main() -> int:
    parser = argparse.ArgumentParser(description="Value eligible S&P 500 companies using a standardized three-period APV screen")
    parser.add_argument("--output", default="./output")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--constituents-source", default=CONSTITUENTS_URL)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    json_path = output / f"SP500_APV_Analysis_{stamp}.json"
    workbook_path = output / f"SP500_APV_Summary_{stamp}.xlsx"
    run_sp500_batch(json_path, args.constituents_source, output / "sp500_cache", args.workers)
    export_sp500_excel(json_path, workbook_path, output / "sp500_previews")
    print(f"Workbook: {workbook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
