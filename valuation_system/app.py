from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from valuation_system.analysis.engine import run_valuation
from valuation_system.data.company_data import load_company_data
from valuation_system.data.peer_data import attach_yahoo_comparables, selected_peer_beta
from valuation_system.data.sp500_batch import SECTOR_BETA, run_sp500_batch
from valuation_system.models.assumptions import ValuationAssumptions, apply_scenario_overrides
from valuation_system.reporting.excel_export import export_excel
from valuation_system.reporting.report_export import export_report
from valuation_system.reporting.sp500_excel import export_sp500_excel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assumption-aware APV public company valuation")
    parser.add_argument("--ticker")
    parser.add_argument("--sp500", action="store_true", help="Run the standardized S&P 500 APV analysis")
    parser.add_argument("--constituents-source", default="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--forecast-years", type=int, default=10)
    parser.add_argument("--assumptions")
    parser.add_argument("--data-file")
    parser.add_argument("--sec-user-agent", help="SEC-compliant application name and contact email; defaults to SEC_USER_AGENT")
    parser.add_argument("--output", default="./output")
    parser.add_argument("--live", action="store_true", help="Attempt live retrieval, then fail back to auditable offline data")
    parser.add_argument("--allow-financial-company", action="store_true")
    parser.add_argument("--market-price-override", type=float)
    parser.add_argument(
        "--scenario-probability", action="append", default=[], metavar="NAME=PERCENT",
        help="Repeatable scenario probability override, for example base=40.",
    )
    parser.add_argument("--no-excel", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.sp500:
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        json_path = output / f"SP500_APV_Analysis_{stamp}.json"
        xlsx_path = output / f"SP500_APV_Summary_{stamp}.xlsx"
        run_sp500_batch(
            json_path,
            constituents_source=args.constituents_source,
            cache_dir=output / "sp500_cache",
            workers=args.workers,
        )
        export_sp500_excel(json_path, xlsx_path, output / "sp500_previews")
        print(f"Analysis: {json_path}")
        print(f"Workbook: {xlsx_path}")
        return 0
    if not args.ticker:
        raise SystemExit("Provide --ticker TICKER or use --sp500")
    if args.assumptions:
        assumptions = ValuationAssumptions.from_yaml(args.assumptions, ticker=args.ticker)
    else:
        assumptions = ValuationAssumptions(ticker=args.ticker.upper(), forecast_years=args.forecast_years)
    assumptions.forecast_years = args.forecast_years
    assumptions.allow_financial_company = args.allow_financial_company
    if args.market_price_override is not None:
        assumptions.market_price_override = args.market_price_override
    apply_scenario_overrides(assumptions, probability_specs=args.scenario_probability)
    assumptions.validate()
    company = load_company_data(args.ticker, args.data_file, args.live, args.sec_user_agent)
    attach_yahoo_comparables(company, assumptions.debt_beta, assumptions.peer_tickers)
    peer_beta = selected_peer_beta(company.comparables)
    if peer_beta is not None:
        assumptions.selected_asset_beta = peer_beta
        assumptions.peer_tickers = [row["peer"] for row in company.comparables]
    else:
        assumptions.selected_asset_beta = SECTOR_BETA.get(company.sector, assumptions.selected_asset_beta)
        assumptions.peer_tickers = []
    assumptions.validate()
    if assumptions.market_price_override is not None:
        company.share_price = assumptions.market_price_override
    result = run_valuation(company, assumptions)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(assumptions.valuation_date).strftime("%Y%m%d")
    report_path = output / f"{company.ticker}_Valuation_Report_{stamp}.md"
    export_report(result, report_path)
    workbook_path = output / f"{company.ticker}_Valuation_{stamp}.xlsx"
    if not args.no_excel:
        export_excel(result, workbook_path)
    (output / f"{company.ticker}_Valuation_{stamp}.json").write_text(
        json.dumps(result.to_dict(), indent=2, allow_nan=False)
    )
    print(f"Status: {result.summary['overall_model_status']}")
    print(f"Intrinsic value/share: {result.summary['intrinsic_value_per_share']:.2f}")
    print(f"Report: {report_path}")
    if not args.no_excel:
        print(f"Workbook: {workbook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
