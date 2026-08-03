from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable

import pandas as pd
import streamlit as st
import yaml

from valuation_system.analysis.engine import run_valuation
from valuation_system.data.company_data import load_company_data
from valuation_system.data.peer_data import attach_yahoo_comparables, load_yahoo_peer_data, selected_peer_beta
from valuation_system.data.sp500_batch import MARKET_RISK_PREMIUM, RISK_FREE_RATE, SECTOR_BETA
from valuation_system.models.assumptions import ScenarioAssumption, ValuationAssumptions
from valuation_system.reporting.cloud_excel import export_cloud_excel
from valuation_system.reporting.excel_export import export_excel
from valuation_system.reporting.report_export import export_report
from valuation_system.ui.formatting import (
    format_currency, format_large_currency, format_percentage, format_status,
)


TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
SCENARIO_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
DEBT_POLICIES = {
    "Use current debt": "use_current_debt",
    "Constant nominal debt": "constant_nominal_debt",
    "Scheduled amortization": "scheduled_amortization",
    "Constant debt-to-value": "constant_debt_to_value",
    "No debt": "no_debt",
}


@dataclass
class UIValuationConfig:
    ticker: str
    valuation_date: str
    forecast_years: int = 10
    competitive_advantage_years: int = 10
    currency: str = "USD"
    peer_tickers: list[str] | None = None
    revenue_growth_start: float | None = None
    terminal_growth_rate: float = 0.025
    terminal_ronic: float | None = None
    enforce_terminal_ronic_to_tocc: bool = True
    ebit_margin_terminal: float | None = None
    tax_rate: float | None = None
    risk_free_rate: float | None = None
    market_risk_premium: float | None = None
    selected_asset_beta: float | None = None
    debt_beta: float = 0.15
    debt_policy: str = "scheduled_amortization"
    cash_tax_rate: float = 0.21
    interest_limit_percentage: float = 0.30
    tax_shield_discount_rate: float | None = None
    minimum_cash: float = 500.0
    data_file: str | None = None
    sec_user_agent: str | None = None
    market_price_override: float | None = None
    allow_financial_company: bool = False
    scenarios: dict[str, ScenarioAssumption] | None = None
    output_dir: str = "valuation_system/output"


@dataclass
class ValuationArtifacts:
    result: Any
    config: UIValuationConfig
    excel_path: Path | None
    report_path: Path | None
    assumptions_path: Path | None
    source_data_path: Path | None
    completed_at: str


def clean_ticker(value: str) -> str:
    ticker = (value or "").upper().strip()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise ValueError("Enter a valid ticker using letters, numbers, a period, or a hyphen.")
    return ticker


def parse_peer_tickers(value: str | list[str] | None) -> list[str]:
    raw = value if isinstance(value, list) else (value or "").split(",")
    peers: list[str] = []
    for item in raw:
        text = str(item).upper().strip()
        if not text:
            continue
        if not TICKER_PATTERN.fullmatch(text):
            raise ValueError(f"Invalid peer ticker: {text}")
        if text not in peers:
            peers.append(text)
    return peers


def parse_optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return float(value)


def validate_terminal_growth(terminal_growth: float, tocc: float | None) -> None:
    if tocc is not None and terminal_growth >= tocc:
        raise ValueError("Terminal growth must be below the True Opportunity Cost of Capital.")


def validate_scenario_probabilities(scenarios: dict[str, Any]) -> None:
    probabilities = [float(value.probability if hasattr(value, "probability") else value["probability"]) for value in scenarios.values()]
    if any(value < 0 or value > 1 for value in probabilities):
        raise ValueError("Each scenario probability must be between 0% and 100%.")
    total = sum(probabilities)
    if abs(total - 1.0) > 1e-9:
        raise ValueError("Scenario probabilities must total 100%.")


def coerce_scenarios(value: dict[str, Any] | None) -> dict[str, ScenarioAssumption] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        raise ValueError("The four fixed scenarios are required.")
    fixed = ValuationAssumptions().scenarios
    supplied = {str(name).lower().strip(): raw for name, raw in value.items()}
    if set(supplied) != set(fixed):
        raise ValueError("Scenarios are fixed as Failure, Downside, Base, and Upside.")
    scenarios: dict[str, ScenarioAssumption] = {}
    for key, default in fixed.items():
        raw = supplied[key]
        probability = raw.probability if isinstance(raw, ScenarioAssumption) else raw.get("probability")
        scenarios[key] = ScenarioAssumption(**{**asdict(default), "probability": float(probability)})
    validate_scenario_probabilities(scenarios)
    return scenarios


def build_valuation_config(**values: Any) -> UIValuationConfig:
    values["ticker"] = clean_ticker(values.get("ticker", ""))
    values["peer_tickers"] = parse_peer_tickers(values.get("peer_tickers"))
    values["scenarios"] = coerce_scenarios(values.get("scenarios"))
    valuation_date = values.get("valuation_date", date.today())
    values["valuation_date"] = valuation_date.isoformat() if hasattr(valuation_date, "isoformat") else str(valuation_date)
    config = UIValuationConfig(**values)
    manual_tocc = None
    if config.risk_free_rate is not None and config.market_risk_premium is not None and config.selected_asset_beta is not None:
        manual_tocc = config.risk_free_rate + config.selected_asset_beta * config.market_risk_premium
    validate_terminal_growth(config.terminal_growth_rate, manual_tocc)
    if not 5 <= config.forecast_years <= 15:
        raise ValueError("Explicit forecast period must be between 5 and 15 years.")
    return config


def parse_assumptions_upload(content: bytes, filename: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        parsed = json.loads(content.decode("utf-8"))
    elif suffix in {".yaml", ".yml"}:
        parsed = yaml.safe_load(content.decode("utf-8"))
    else:
        raise ValueError("Assumptions files must be YAML or JSON.")
    if not isinstance(parsed, dict):
        raise ValueError("The assumptions file must contain a mapping of field names to values.")
    return parsed


def flatten_uploaded_assumptions(raw: dict[str, Any]) -> dict[str, Any]:
    terminal = raw.get("terminal") or {}
    tocc = raw.get("tocc") or {}
    tax = raw.get("tax") or {}
    debt = raw.get("debt_policy") or {}
    overperformance = raw.get("overperformance") or {}
    liquidity = raw.get("liquidity") or {}
    return {
        "ticker": raw.get("ticker"), "valuation_date": raw.get("valuation_date"),
        "forecast_years": raw.get("forecast_years"), "currency": raw.get("currency"),
        "competitive_advantage_years": overperformance.get("years"),
        "terminal_growth_rate": terminal.get("growth_rate"), "terminal_ronic": terminal.get("ronic"),
        "enforce_terminal_ronic_to_tocc": terminal.get("enforce_ronic_equals_tocc"),
        "risk_free_rate": tocc.get("risk_free_rate"), "market_risk_premium": tocc.get("market_risk_premium"),
        "selected_asset_beta": tocc.get("selected_asset_beta"), "peer_tickers": tocc.get("peer_tickers"),
        "tax_rate": tax.get("normalized_operating_tax_rate"), "cash_tax_rate": tax.get("cash_tax_rate"),
        "interest_limit_percentage": tax.get("interest_limit_percentage"),
        "debt_policy": debt.get("type"), "minimum_cash": liquidity.get("minimum_cash"),
        "revenue_growth_start": raw.get("revenue_growth_start"), "ebit_margin_terminal": raw.get("ebit_margin_terminal"),
        "scenarios": raw.get("scenarios"),
    }


def _sector_key(sector: str) -> str:
    aliases = {"Technology": "Information Technology", "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples", "Healthcare": "Health Care", "Basic Materials": "Materials"}
    return aliases.get(sector, sector)


def _assumptions_from_company(company: Any, config: UIValuationConfig) -> ValuationAssumptions:
    history = sorted(company.historical, key=lambda row: row.year)
    growth = [history[i].revenue / history[i - 1].revenue - 1 for i in range(1, len(history)) if history[i - 1].revenue > 0]
    margins = [row.ebit / row.revenue for row in history if row.revenue > 0]
    sector = _sector_key(company.sector)
    risk_free = RISK_FREE_RATE if config.risk_free_rate is None else config.risk_free_rate
    market_premium = MARKET_RISK_PREMIUM if config.market_risk_premium is None else config.market_risk_premium
    peer_beta = selected_peer_beta(company.comparables)
    beta = peer_beta if peer_beta is not None else SECTOR_BETA.get(sector, 1.0)
    start_growth = config.revenue_growth_start
    if start_growth is None:
        start_growth = min(0.20, max(-0.05, median(growth) if growth else 0.05))
    terminal_margin = config.ebit_margin_terminal
    if terminal_margin is None:
        terminal_margin = min(0.30, max(0.05, median(margins[-3:]) if margins else 0.10))
    start_margin = min(0.40, max(-0.30, margins[-1] if margins else 0.05))
    assumptions = ValuationAssumptions(
        ticker=config.ticker, valuation_date=config.valuation_date, forecast_years=config.forecast_years,
        competitive_advantage_years=config.competitive_advantage_years, currency=config.currency,
        revenue_growth_start=start_growth, revenue_growth_terminal=config.terminal_growth_rate,
        ebit_margin_start=start_margin, ebit_margin_terminal=terminal_margin,
        tax_rate=config.tax_rate if config.tax_rate is not None else 0.21,
        cash_tax_rate=config.cash_tax_rate, risk_free_rate=risk_free,
        market_risk_premium=market_premium, selected_asset_beta=beta,
        peer_tickers=[row["peer"] for row in company.comparables],
        terminal_growth_rate=config.terminal_growth_rate, terminal_ronic=config.terminal_ronic,
        enforce_terminal_ronic_to_tocc=config.enforce_terminal_ronic_to_tocc,
        minimum_cash=config.minimum_cash, debt_beta=config.debt_beta,
        tax_shield_discount_rate=config.tax_shield_discount_rate,
        debt_policy=config.debt_policy, interest_limit_percentage=config.interest_limit_percentage,
        allow_financial_company=config.allow_financial_company,
        scenarios=config.scenarios or ValuationAssumptions().scenarios,
    )
    validate_scenario_probabilities(assumptions.scenarios)
    assumptions.validate()
    return assumptions


def _write_source_csv(result: Any, path: Path) -> Path:
    rows = result.company["historical"]
    if not rows:
        raise ValueError("No historical source data are available for download.")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fallback_excel(result: Any, path: Path) -> Path:
    """Build the formula-driven reference-style workbook on Community Cloud."""
    return export_cloud_excel(result, path)


def run_company_valuation(
    config: UIValuationConfig,
    *,
    company_loader: Callable[..., Any] = load_company_data,
    engine_runner: Callable[..., Any] = run_valuation,
    excel_exporter: Callable[..., Any] = export_excel,
    report_exporter: Callable[..., Any] = export_report,
    peer_loader: Callable[..., list[dict[str, Any]]] = load_yahoo_peer_data,
) -> ValuationArtifacts:
    company = company_loader(config.ticker, config.data_file, config.data_file is None, config.sec_user_agent)
    company.currency = config.currency
    attach_yahoo_comparables(
        company, config.debt_beta, config.peer_tickers, loader=peer_loader,
    )
    if config.market_price_override is not None:
        company.share_price = config.market_price_override
    assumptions = _assumptions_from_company(company, config)
    result = engine_runner(company, assumptions)
    completed_at = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.fromisoformat(config.valuation_date).strftime("%Y%m%d")
    run_dir = Path(config.output_dir) / f"{config.ticker}_{stamp}_{datetime.now().strftime('%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_exporter(result, run_dir / f"{config.ticker}_Valuation_Report.md")
    excel_path = run_dir / f"{config.ticker}_Valuation.xlsx"
    try:
        excel_exporter(result, excel_path)
    except Exception:
        _fallback_excel(result, excel_path)
    assumptions_path = run_dir / f"{config.ticker}_Assumptions.yaml"
    assumptions_path.write_text(yaml.safe_dump(assumptions.to_dict(), sort_keys=False))
    source_path = _write_source_csv(result, run_dir / f"{config.ticker}_Source_Data.csv")
    return ValuationArtifacts(result, config, excel_path, Path(report_path), assumptions_path, source_path, completed_at)


def valuation_bridge_rows(result: Any) -> list[dict[str, Any]]:
    s = result.summary
    return [
        {"Valuation component": "PV of explicit unlevered FCF", "Value ($mm)": s["pv_explicit_fcf"]},
        {"Valuation component": "PV of continuing value", "Value ($mm)": s["pv_continuing_value"]},
        {"Valuation component": "Operating enterprise value", "Value ($mm)": s["operating_enterprise_value"]},
        {"Valuation component": "PV of explicit tax shields", "Value ($mm)": s["pv_explicit_tax_shields"]},
        {"Valuation component": "PV of continuing tax shield", "Value ($mm)": s["pv_continuing_tax_shield"]},
        {"Valuation component": "PV of financing effects", "Value ($mm)": s["pv_financing_effects"]},
        {"Valuation component": "APV enterprise value", "Value ($mm)": s["apv_enterprise_value"]},
        {"Valuation component": "Less: debt and other claims", "Value ($mm)": -(s["gross_debt"] + s["other_financing_claims"])},
        {"Valuation component": "Add: excess cash and investments", "Value ($mm)": s["excess_cash"]},
        {"Valuation component": "Equity value", "Value ($mm)": s["equity_value"]},
        {"Valuation component": "Diluted shares (mm)", "Value ($mm)": s["diluted_shares"]},
        {"Valuation component": "Intrinsic value per share", "Value ($mm)": s["intrinsic_value_per_share"]},
    ]


def render_metric_cards(result: Any) -> None:
    s = result.summary
    top = st.columns(3)
    top[0].metric("Intrinsic Value / Share", format_currency(s["intrinsic_value_per_share"]))
    top[1].metric("Market Price", format_currency(s["market_price"]))
    top[2].metric("Market Capitalization", format_large_currency(s.get("market_cap")))
    bottom = st.columns(3)
    bottom[0].metric("Premium / Discount", format_percentage(s["premium_discount"]), delta=format_percentage(s["premium_discount"]))
    bottom[1].metric("APV Enterprise Value", format_large_currency(s["apv_enterprise_value"]))
    bottom[2].metric("Equity Value", format_large_currency(s["equity_value"]))


def render_overall_status(status: str) -> None:
    message = f"Overall Model Status: {format_status(status)}"
    if status == "PASS":
        st.success(message)
    elif status == "WARNING":
        st.warning(message)
    else:
        st.error(message)


def render_downloads(paths: dict[str, Path | str | None], ticker: str, *, key_prefix: str = "download") -> None:
    specs = [
        ("excel", "Download Excel", f"{ticker}_Valuation.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("report", "Download Valuation Report", f"{ticker}_Valuation_Report.md", "text/markdown"),
        ("assumptions", "Download Assumptions", f"{ticker}_Assumptions.yaml", "application/x-yaml"),
        ("source", "Download Source Data", f"{ticker}_Source_Data.csv", "text/csv"),
    ]
    columns = st.columns(4)
    for column, (key, label, filename, mime) in zip(columns, specs):
        path = Path(paths[key]) if paths.get(key) else None
        if path and path.exists():
            column.download_button(label, path.read_bytes(), file_name=filename, mime=mime, use_container_width=True, key=f"{key_prefix}_{key}")
