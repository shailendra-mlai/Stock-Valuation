from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
import requests


CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ_FINANCIALS = "https://api.nasdaq.com/api/company/{ticker}/financials?frequency=1"
NASDAQ_SUMMARY = "https://api.nasdaq.com/api/quote/{ticker}/summary?assetclass=stocks"
USER_AGENT = "Mozilla/5.0 (compatible; ValuationSystem/1.0; public-financial-analysis)"

RISK_FREE_RATE = 0.0445
MARKET_RISK_PREMIUM = 0.0418
FORECAST_YEARS = 10

SECTOR_BETA = {
    "Communication Services": 1.00,
    "Consumer Discretionary": 1.15,
    "Consumer Staples": 0.75,
    "Energy": 0.95,
    "Health Care": 0.85,
    "Industrials": 1.00,
    "Information Technology": 1.15,
    "Materials": 1.05,
    "Real Estate": 0.80,
    "Utilities": 0.55,
}

SECTOR_RONIC = {
    "Communication Services": 0.11,
    "Consumer Discretionary": 0.11,
    "Consumer Staples": 0.09,
    "Energy": 0.09,
    "Health Care": 0.11,
    "Industrials": 0.10,
    "Information Technology": 0.12,
    "Materials": 0.09,
    "Real Estate": 0.08,
    "Utilities": 0.08,
}


@dataclass
class BatchValuationRow:
    ticker: str
    company: str
    sector: str
    sub_industry: str
    status: str
    unlevered_tocc: float | None = None
    terminal_growth: float | None = None
    pv_explicit_fcf: float | None = None
    pv_continuing_value: float | None = None
    operating_enterprise_value: float | None = None
    pv_financing_effects: float | None = None
    apv_enterprise_value: float | None = None
    equity_value: float | None = None
    intrinsic_value_per_share: float | None = None
    market_price: float | None = None
    premium_discount: float | None = None
    pv_continuing_value_to_apv_ev: float | None = None
    latest_revenue: float | None = None
    latest_ebit: float | None = None
    latest_operating_invested_capital: float | None = None
    excess_cash: float | None = None
    gross_debt: float | None = None
    other_financing_claims: float | None = None
    diluted_shares: float | None = None
    terminal_ronic: float | None = None
    forecast_start_growth: float | None = None
    terminal_ebit_margin: float | None = None
    source_period: str = ""
    market_source_date: str = ""
    notes: str = ""


def _num(value: Any, scale: float = 1.0) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "--", "N/A", "NA", "null", "None"}:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return None
    result = float(cleaned) / scale
    return -result if negative else result


def _table(data: dict[str, Any], name: str) -> tuple[list[str], dict[str, list[float | None]]]:
    block = data.get(name) or {}
    headers = block.get("headers") or {}
    periods = [headers.get(f"value{i}", "") for i in range(2, 6)]
    rows: dict[str, list[float | None]] = {}
    for row in block.get("rows") or []:
        label = str(row.get("value1") or "").strip()
        if label:
            rows[label] = [_num(row.get(f"value{i}"), 1000.0) for i in range(2, 6)]
    return periods, rows


def _latest(rows: dict[str, list[float | None]], *labels: str) -> float | None:
    for label in labels:
        values = rows.get(label)
        if values and values[0] is not None:
            return values[0]
    return None


def _series(rows: dict[str, list[float | None]], *labels: str) -> list[float | None]:
    for label in labels:
        if label in rows:
            return rows[label]
    return [None, None, None, None]


def _fetch_json(url: str, attempts: int = 4) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if payload.get("data") is None:
                raise ValueError("provider returned no data")
            return payload
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"request failed after {attempts} attempts: {last_error}")


def _provider_ticker(ticker: str) -> str:
    # Nasdaq's company endpoint accepts class-share symbols with a dot (for
    # example BRK.B); converting them to Yahoo-style hyphens drops valid data.
    return ticker


def _collect_one(record: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    ticker = str(record["ticker"])
    provider = _provider_ticker(ticker)
    cache_file = cache_dir / f"{provider}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        return {**record, **cached}
    financials = _fetch_json(NASDAQ_FINANCIALS.format(ticker=provider))["data"]
    summary = _fetch_json(NASDAQ_SUMMARY.format(ticker=provider))["data"]
    payload = {"financials": financials, "summary": summary}
    cache_file.write_text(json.dumps(payload))
    return {**record, **payload}


def load_constituents(source: str | Path = CONSTITUENTS_URL) -> list[dict[str, Any]]:
    table = pd.read_html(str(source))[0]
    return [
        {
            "ticker": row["Symbol"],
            "company": row["Security"],
            "sector": row["GICS Sector"],
            "sub_industry": row["GICS Sub-Industry"],
            "cik": int(row["CIK"]),
        }
        for _, row in table.iterrows()
    ]


def collect_sp500_data(
    constituents_source: str | Path = CONSTITUENTS_URL,
    cache_dir: str | Path = "valuation_system/output/sp500_cache",
    workers: int = 12,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records = load_constituents(constituents_source)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_collect_one, record, cache): record for record in records}
        for index, future in enumerate(as_completed(futures), 1):
            record = futures[future]
            try:
                collected.append(future.result())
            except Exception as exc:
                failures.append({"ticker": record["ticker"], "error": str(exc)})
                collected.append({**record, "error": str(exc)})
            if index % 50 == 0:
                print(f"Collected {index}/{len(records)} companies; failures={len(failures)}", flush=True)
    collected.sort(key=lambda row: row["ticker"])
    return collected, failures


def _raw_metrics(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("error"):
        return {**record, "data_error": record["error"]}
    data = record["financials"]
    periods, income = _table(data, "incomeStatementTable")
    _, balance = _table(data, "balanceSheetTable")
    _, cash_flow = _table(data, "cashFlowTable")
    revenue_series = _series(income, "Total Revenue")
    ebit_series = _series(income, "Operating Income", "Earnings Before Interest and Tax")
    revenue = revenue_series[0]
    ebit = ebit_series[0]
    cash = _latest(balance, "Cash and Cash Equivalents") or 0.0
    short_investments = _latest(balance, "Short-Term Investments") or 0.0
    debt = (_latest(balance, "Short-Term Debt / Current Portion of Long-Term Debt") or 0.0) + (_latest(balance, "Long-Term Debt") or 0.0)
    minority = _latest(balance, "Minority Interest") or 0.0
    operating_current_assets = sum(x or 0.0 for x in [
        _latest(balance, "Net Receivables"), _latest(balance, "Inventory"), _latest(balance, "Other Current Assets")
    ])
    operating_current_liabilities = (_latest(balance, "Accounts Payable") or 0.0) + (_latest(balance, "Other Current Liabilities") or 0.0)
    long_operating_assets = sum(x or 0.0 for x in [
        _latest(balance, "Fixed Assets"), _latest(balance, "Goodwill"), _latest(balance, "Intangible Assets"), _latest(balance, "Other Assets")
    ])
    invested_capital = operating_current_assets - operating_current_liabilities + long_operating_assets
    summary_data = (record["summary"] or {}).get("summaryData") or {}
    price = _num((summary_data.get("PreviousClose") or {}).get("value"))
    market_cap = _num((summary_data.get("MarketCap") or {}).get("value"), 1_000_000.0)
    shares = market_cap / price if market_cap and price and price > 0 else None
    growth_rates = []
    for i in range(3):
        newer, older = revenue_series[i], revenue_series[i + 1]
        if newer is not None and older not in (None, 0):
            growth_rates.append(newer / older - 1)
    margin_values = [e / r for e, r in zip(ebit_series, revenue_series) if e is not None and r and r > 0]
    tax = _latest(income, "Income Tax")
    ebt = _latest(income, "Earnings Before Tax")
    effective_tax = tax / ebt if tax is not None and ebt and ebt > 0 else 0.21
    effective_tax = min(0.28, max(0.15, effective_tax))
    interest = abs(_latest(income, "Interest Expense") or 0.0)
    return {
        **record,
        "periods": periods,
        "revenue_series": revenue_series,
        "ebit_series": ebit_series,
        "latest_revenue": revenue,
        "latest_ebit": ebit,
        "latest_margin": ebit / revenue if ebit is not None and revenue and revenue > 0 else None,
        "historical_growth": median(growth_rates) if growth_rates else None,
        "historical_margin": median(margin_values[:3]) if margin_values else None,
        "cash": cash,
        "short_investments": short_investments,
        "debt": debt,
        "minority_interest": minority,
        "invested_capital": invested_capital,
        "capital_turnover": revenue / invested_capital if revenue and invested_capital > 0 else None,
        "tax_rate": effective_tax,
        "interest_expense": interest,
        "market_price": price,
        "market_cap": market_cap,
        "shares": shares,
    }


def _safe_sector_median(values: list[float], default: float, low: float, high: float) -> float:
    clean = [v for v in values if v is not None and math.isfinite(v) and low <= v <= high]
    return median(clean) if clean else default


def _present_value(values: list[float], rate: float) -> float:
    return sum(value / (1 + rate) ** (i + 1) for i, value in enumerate(values))


def value_sp500(records: list[dict[str, Any]]) -> tuple[list[BatchValuationRow], dict[str, Any]]:
    raw = [_raw_metrics(record) for record in records]
    sector_margins: dict[str, float] = {}
    sector_turnover: dict[str, float] = {}
    for sector in {r["sector"] for r in raw}:
        sector_rows = [r for r in raw if r["sector"] == sector]
        sector_margins[sector] = _safe_sector_median([r.get("historical_margin") for r in sector_rows], 0.10, -0.10, 0.50)
        sector_turnover[sector] = _safe_sector_median([r.get("capital_turnover") for r in sector_rows], 1.0, 0.15, 8.0)
    output: list[BatchValuationRow] = []
    for item in raw:
        base = BatchValuationRow(
            ticker=item["ticker"], company=item["company"], sector=item["sector"],
            sub_industry=item["sub_industry"], status="FAIL", market_source_date=str(date.today()),
        )
        if item["sector"] == "Financials":
            base.status = "N/A – FINANCIAL"
            base.notes = "Standard operating invested-capital/APV framework is not appropriate for banks, insurers, or diversified financials."
            base.market_price = item.get("market_price")
            output.append(base)
            continue
        if item.get("data_error"):
            base.status = "FAIL – DATA"
            base.notes = item["data_error"]
            output.append(base)
            continue
        required = [item.get("latest_revenue"), item.get("latest_ebit"), item.get("market_price"), item.get("shares")]
        if any(value is None for value in required) or item["latest_revenue"] <= 0 or item["shares"] <= 0:
            base.status = "FAIL – MISSING INPUT"
            base.notes = "Revenue, EBIT, market price, or share count is missing/unusable; no value was fabricated."
            base.market_price = item.get("market_price")
            output.append(base)
            continue
        sector = item["sector"]
        beta = SECTOR_BETA.get(sector, 1.0)
        tocc = RISK_FREE_RATE + beta * MARKET_RISK_PREMIUM
        terminal_growth = 0.02 if sector in {"Energy", "Materials", "Real Estate", "Utilities"} else 0.025
        terminal_ronic = max(SECTOR_RONIC.get(sector, 0.10), tocc + 0.01)
        start_growth = min(0.20, max(-0.05, item.get("historical_growth") if item.get("historical_growth") is not None else terminal_growth + 0.02))
        target_margin = min(0.35, max(0.03, sector_margins[sector]))
        start_margin = item.get("historical_margin") if item.get("historical_margin") is not None else item["latest_ebit"] / item["latest_revenue"]
        start_margin = min(0.45, max(-0.30, start_margin))
        target_turnover = sector_turnover[sector]
        current_turnover = item.get("capital_turnover")
        fallback_ic = current_turnover is None or not 0.15 <= current_turnover <= 8.0
        if fallback_ic:
            current_turnover = target_turnover
        revenue = item["latest_revenue"]
        prior_ic = revenue / current_turnover
        forecast_fcfs: list[float] = []
        forecast_ebit: list[float] = []
        last_nopat = item["latest_ebit"] * (1 - item["tax_rate"]) if item["latest_ebit"] > 0 else item["latest_ebit"]
        for year in range(1, FORECAST_YEARS + 1):
            weight = year / FORECAST_YEARS
            growth = start_growth + (terminal_growth - start_growth) * weight
            margin = start_margin + (target_margin - start_margin) * weight
            turnover = current_turnover + (target_turnover - current_turnover) * weight
            revenue *= 1 + growth
            ebit = revenue * margin
            nopat = ebit * (1 - item["tax_rate"]) if ebit > 0 else ebit
            invested_capital = revenue / max(0.15, turnover)
            net_investment = invested_capital - prior_ic
            fcf = nopat - net_investment
            forecast_fcfs.append(fcf)
            forecast_ebit.append(ebit)
            last_nopat = nopat
            prior_ic = invested_capital
        if last_nopat <= 0 or terminal_growth >= tocc:
            base.status = "FAIL – TERMINAL ECONOMICS"
            base.notes = "Terminal NOPAT is non-positive or terminal growth is not below TOCC."
            base.market_price = item["market_price"]
            output.append(base)
            continue
        reinvestment_rate = terminal_growth / terminal_ronic
        continuing_value = last_nopat * (1 + terminal_growth) * (1 - reinvestment_rate) / (tocc - terminal_growth)
        pv_explicit = _present_value(forecast_fcfs, tocc)
        pv_cv = continuing_value / (1 + tocc) ** FORECAST_YEARS
        operating_ev = pv_explicit + pv_cv
        interest = item["interest_expense"]
        shield_cash_flows = []
        for year, ebit in enumerate(forecast_ebit):
            forecast_interest = interest * (0.95 ** year)
            deductible = min(forecast_interest, max(0.0, 0.30 * ebit))
            shield_cash_flows.append(deductible * item["tax_rate"])
        pv_financing = _present_value(shield_cash_flows, tocc)
        apv_ev = operating_ev + pv_financing
        operating_cash = max(0.0, 0.02 * item["latest_revenue"])
        excess_cash = max(0.0, item["cash"] + item["short_investments"] - operating_cash)
        equity = apv_ev - item["debt"] - item["minority_interest"] + excess_cash
        per_share = equity / item["shares"]
        premium = per_share / item["market_price"] - 1
        cv_share = pv_cv / apv_ev if apv_ev != 0 else None
        status = "WARNING" if fallback_ic or cv_share is None or cv_share > 0.80 or sector == "Real Estate" else "PASS"
        notes = []
        if fallback_ic:
            notes.append("Operating invested capital was unstable; sector median capital turnover was used.")
        if cv_share is not None and cv_share > 0.80:
            notes.append("PV continuing value exceeds 80% of APV EV.")
        if sector == "Real Estate":
            notes.append("REIT accounting and distributions can make this corporate APV screen less reliable.")
        base.status = status
        base.unlevered_tocc = tocc
        base.terminal_growth = terminal_growth
        base.pv_explicit_fcf = pv_explicit
        base.pv_continuing_value = pv_cv
        base.operating_enterprise_value = operating_ev
        base.pv_financing_effects = pv_financing
        base.apv_enterprise_value = apv_ev
        base.equity_value = equity
        base.intrinsic_value_per_share = per_share
        base.market_price = item["market_price"]
        base.premium_discount = premium
        base.pv_continuing_value_to_apv_ev = cv_share
        base.latest_revenue = item["latest_revenue"]
        base.latest_ebit = item["latest_ebit"]
        base.latest_operating_invested_capital = item["invested_capital"]
        base.excess_cash = excess_cash
        base.gross_debt = item["debt"]
        base.other_financing_claims = item["minority_interest"]
        base.diluted_shares = item["shares"]
        base.terminal_ronic = terminal_ronic
        base.forecast_start_growth = start_growth
        base.terminal_ebit_margin = target_margin
        base.source_period = item["periods"][0] if item.get("periods") else ""
        base.notes = " ".join(notes) or "Standardized S&P 500 APV screen; issuer-specific disclosures were not individually underwritten."
        output.append(base)
    summary = {
        "as_of": str(date.today()),
        "constituent_count": len(records),
        "valued_count": sum(row.status in {"PASS", "WARNING"} for row in output),
        "pass_count": sum(row.status == "PASS" for row in output),
        "warning_count": sum(row.status == "WARNING" for row in output),
        "financial_count": sum(row.status == "N/A – FINANCIAL" for row in output),
        "failure_count": sum(row.status.startswith("FAIL") for row in output),
        "risk_free_rate": RISK_FREE_RATE,
        "market_risk_premium": MARKET_RISK_PREMIUM,
        "forecast_years": FORECAST_YEARS,
        "constituent_source": CONSTITUENTS_URL,
        "financial_source": "https://api.nasdaq.com/api/company/{ticker}/financials?frequency=1",
        "market_source": "https://api.nasdaq.com/api/quote/{ticker}/summary?assetclass=stocks",
        "risk_source": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm",
    }
    return output, summary


def run_sp500_batch(
    output_json: str | Path,
    constituents_source: str | Path = CONSTITUENTS_URL,
    cache_dir: str | Path = "valuation_system/output/sp500_cache",
    workers: int = 12,
) -> Path:
    records, failures = collect_sp500_data(constituents_source, cache_dir, workers)
    valuations, summary = value_sp500(records)
    payload = {
        "summary": summary,
        "rows": [asdict(row) for row in valuations],
        "collection_failures": failures,
        "sector_beta": SECTOR_BETA,
        "sector_ronic": SECTOR_RONIC,
    }
    path = Path(output_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False))
    return path
