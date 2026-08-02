"""Run a complete ticker-specific APV analysis and export a Rivian-style workbook."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from statistics import median

from valuation_system.analysis.engine import run_valuation
from valuation_system.data.company_data import load_company_data
from valuation_system.data.sp500_batch import MARKET_RISK_PREMIUM, RISK_FREE_RATE, SECTOR_BETA
from valuation_system.models.assumptions import ValuationAssumptions
from valuation_system.reporting.excel_export import export_excel
from valuation_system.reporting.report_export import export_report


def _sector_key(sector: str) -> str:
    aliases = {
        "Technology": "Information Technology", "Consumer Cyclical": "Consumer Discretionary",
        "Consumer Defensive": "Consumer Staples", "Healthcare": "Health Care",
        "Basic Materials": "Materials", "Communication Services": "Communication Services",
    }
    return aliases.get(sector, sector)


def assumptions_from_history(ticker: str, company, years: int) -> ValuationAssumptions:
    history = sorted(company.historical, key=lambda row: row.year)
    growth = [history[i].revenue / history[i - 1].revenue - 1 for i in range(1, len(history)) if history[i - 1].revenue > 0]
    margins = [row.ebit / row.revenue for row in history if row.revenue > 0]
    sector = _sector_key(company.sector)
    start_growth = min(0.20, max(-0.05, median(growth) if growth else 0.05))
    start_margin = min(0.40, max(-0.30, margins[-1] if margins else 0.05))
    terminal_margin = min(0.30, max(0.05, median(margins[-3:]) if margins else 0.10))
    beta = SECTOR_BETA.get(sector, 1.0)
    terminal_growth = 0.02 if sector in {"Energy", "Materials", "Real Estate", "Utilities"} else 0.025
    return ValuationAssumptions(
        ticker=ticker.upper(), valuation_date=date.today().isoformat(), forecast_years=years,
        revenue_growth_start=start_growth, revenue_growth_terminal=terminal_growth,
        ebit_margin_start=start_margin, ebit_margin_terminal=terminal_margin,
        risk_free_rate=RISK_FREE_RATE, market_risk_premium=MARKET_RISK_PREMIUM,
        selected_asset_beta=beta, terminal_growth_rate=terminal_growth,
        terminal_ronic=None, enforce_terminal_ronic_to_tocc=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete APV valuation for one nonfinancial public company")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--forecast-years", type=int, default=10)
    parser.add_argument("--competitive-advantage-years", type=int, default=10)
    parser.add_argument("--initial-nol", type=float)
    parser.add_argument("--minimum-cash", type=float)
    parser.add_argument("--annual-sbc-dilution-rate", type=float)
    parser.add_argument("--assumptions")
    parser.add_argument("--data-file")
    parser.add_argument("--output", default="./output")
    parser.add_argument("--market-price-override", type=float)
    parser.add_argument("--allow-financial-company", action="store_true")
    args = parser.parse_args()
    company = load_company_data(args.ticker, args.data_file, live=args.data_file is None)
    assumptions = (
        ValuationAssumptions.from_yaml(args.assumptions, ticker=args.ticker)
        if args.assumptions else assumptions_from_history(args.ticker, company, args.forecast_years)
    )
    assumptions.forecast_years = args.forecast_years
    assumptions.competitive_advantage_years = args.competitive_advantage_years
    if args.initial_nol is not None:
        assumptions.initial_operating_nol = args.initial_nol
    if args.minimum_cash is not None:
        assumptions.minimum_cash = args.minimum_cash
    if args.annual_sbc_dilution_rate is not None:
        assumptions.annual_sbc_dilution_rate = args.annual_sbc_dilution_rate
    assumptions.validate()
    assumptions.allow_financial_company = args.allow_financial_company
    if args.market_price_override is not None:
        company.share_price = args.market_price_override
    result = run_valuation(company, assumptions)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = assumptions.valuation_date.replace("-", "")
    workbook = output / f"{company.ticker}_Valuation_{stamp}.xlsx"
    report = output / f"{company.ticker}_Valuation_Report_{stamp}.md"
    export_excel(result, workbook)
    export_report(result, report)
    (output / f"{company.ticker}_Valuation_{stamp}.json").write_text(json.dumps(result.to_dict(), indent=2, allow_nan=False))
    print(f"Status: {result.summary['overall_model_status']}")
    print(f"Intrinsic value/share: {result.summary['intrinsic_value_per_share']:.2f}")
    print(f"Workbook: {workbook}")
    print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
