from __future__ import annotations

from datetime import date
from typing import Any, Callable

import requests

from valuation_system.analysis.calculations import asset_beta
from valuation_system.models.company import CompanyData, ProvenanceRecord


YAHOO_RECOMMENDATIONS_URL = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{ticker}"
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{ticker}/"
USER_AGENT = "Mozilla/5.0 (compatible; Stock-Valuation/1.0)"


def discover_yahoo_comparables(
    ticker: str,
    limit: int = 4,
    *,
    request_get: Callable[..., Any] = requests.get,
) -> list[dict[str, Any]]:
    """Return Yahoo Finance 'People Also Watch' symbols and relevance scores."""
    symbol = ticker.upper().strip()
    response = request_get(
        YAHOO_RECOMMENDATIONS_URL.format(ticker=symbol),
        headers={"User-Agent": USER_AGENT},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    results = ((payload.get("finance") or {}).get("result") or [])
    recommendations = results[0].get("recommendedSymbols", []) if results else []
    output: list[dict[str, Any]] = []
    seen = {symbol}
    for item in recommendations:
        peer = str(item.get("symbol") or "").upper().strip()
        if not peer or peer in seen:
            continue
        seen.add(peer)
        output.append({"peer": peer, "recommendation_score": float(item.get("score") or 0)})
        if len(output) >= limit:
            break
    return output


def _default_info_loader(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    return yf.Ticker(ticker).get_info()


def _statement_value(frame: Any, label: str, column: Any, default: float | None = None) -> float | None:
    try:
        value = frame.loc[label, column]
        return default if value is None else float(value)
    except (KeyError, TypeError, ValueError):
        return default


def load_yahoo_roic_metrics(ticker: str) -> dict[str, float | None]:
    """Calculate Kevin Kaiser-style ROIC-tree ratios from Yahoo annual statements."""
    import yfinance as yf

    company = yf.Ticker(ticker)
    income = company.get_income_stmt(freq="yearly")
    balance = company.get_balance_sheet(freq="yearly")
    if income.empty or balance.empty:
        return {}
    income_columns = sorted(income.columns, reverse=True)
    balance_columns = sorted(balance.columns, reverse=True)
    current_income = income_columns[0]
    prior_income = income_columns[1] if len(income_columns) > 1 else current_income
    current_balance = balance_columns[0]
    prior_balance = balance_columns[1] if len(balance_columns) > 1 else current_balance
    revenue = _statement_value(income, "TotalRevenue", current_income, 0.0) or 0.0
    prior_revenue = _statement_value(income, "TotalRevenue", prior_income, 0.0) or 0.0
    ebit = _statement_value(income, "OperatingIncome", current_income, 0.0) or 0.0
    pretax = _statement_value(income, "PretaxIncome", current_income, 0.0) or 0.0
    tax = _statement_value(income, "TaxProvision", current_income, 0.0) or 0.0
    current_ic = _statement_value(balance, "InvestedCapital", current_balance, 0.0) or 0.0
    prior_ic = _statement_value(balance, "InvestedCapital", prior_balance, current_ic) or current_ic
    average_ic = (current_ic + prior_ic) / 2
    tax_rate = min(0.40, max(0.0, tax / pretax)) if pretax > 0 else 0.0
    cash = _statement_value(balance, "CashCashEquivalentsAndShortTermInvestments", current_balance, 0.0) or 0.0
    current_assets = _statement_value(balance, "CurrentAssets", current_balance, 0.0) or 0.0
    current_liabilities = _statement_value(balance, "CurrentLiabilities", current_balance, 0.0) or 0.0
    current_debt = _statement_value(balance, "CurrentDebt", current_balance, 0.0) or 0.0
    operating_wcr = current_assets - cash - current_liabilities + current_debt

    def ratio(statement: Any, label: str, column: Any) -> float | None:
        value = _statement_value(statement, label, column)
        return value / revenue if value is not None and revenue else None

    return {
        "roic_fiscal_year": int(getattr(current_income, "year", 0) or 0),
        "revenue_growth": revenue / prior_revenue - 1 if prior_revenue else None,
        "after_tax_roic": ebit * (1 - tax_rate) / average_ic if average_ic else None,
        "pre_tax_roic": ebit / average_ic if average_ic else None,
        "cash_tax_rate": tax_rate,
        "ebit_margin": ebit / revenue if revenue else None,
        "capital_turnover": revenue / average_ic if average_ic else None,
        "cogs_revenue": ratio(income, "CostOfRevenue", current_income),
        "sga_revenue": ratio(income, "SellingGeneralAndAdministration", current_income),
        "rd_revenue": ratio(income, "ResearchAndDevelopment", current_income),
        "net_ppe_revenue": ratio(balance, "NetPPE", current_balance),
        "wcr_revenue": operating_wcr / revenue if revenue else None,
        "cash_revenue": cash / revenue if revenue else None,
        "receivables_revenue": ratio(balance, "Receivables", current_balance),
        "inventory_revenue": ratio(balance, "Inventory", current_balance),
        "payables_revenue": ratio(balance, "AccountsPayable", current_balance),
    }


def load_yahoo_peer_data(
    ticker: str,
    debt_beta: float = 0.15,
    limit: int = 4,
    comparable_tickers: list[str] | None = None,
    *,
    request_get: Callable[..., Any] = requests.get,
    info_loader: Callable[[str], dict[str, Any]] = _default_info_loader,
    metric_loader: Callable[[str], dict[str, Any]] = load_yahoo_roic_metrics,
) -> list[dict[str, Any]]:
    """Build a sourced peer-beta table from Yahoo related symbols and quote statistics."""
    if comparable_tickers:
        recommendations = [
            {"peer": symbol.upper().strip(), "recommendation_score": 1.0}
            for symbol in comparable_tickers
            if symbol.upper().strip() != ticker.upper().strip()
        ]
        selection_method = "User-defined comparable"
    else:
        recommendations = discover_yahoo_comparables(ticker, limit, request_get=request_get)
        selection_method = "Yahoo Finance People Also Watch"
    rows: list[dict[str, Any]] = []
    for item in recommendations:
        try:
            info = info_loader(item["peer"]) or {}
            if info.get("quoteType") not in (None, "EQUITY"):
                continue
            quote_currency = info.get("currency")
            financial_currency = info.get("financialCurrency")
            if quote_currency and financial_currency and quote_currency != financial_currency:
                continue
            equity_beta = float(info["beta"])
            equity = float(info["marketCap"]) / 1_000_000
            debt = max(0.0, float(info.get("totalDebt") or 0) / 1_000_000)
            if equity <= 0:
                continue
        except Exception:
            continue
        raw_beta = asset_beta(equity_beta, equity, debt_beta, debt)
        try:
            roic_metrics = metric_loader(item["peer"]) or {}
        except Exception:
            roic_metrics = {}
        rows.append({
            "peer": item["peer"],
            "company_name": info.get("shortName") or info.get("longName") or item["peer"],
            "equity_beta": equity_beta,
            "equity": equity,
            "debt": debt,
            "debt_beta": debt_beta,
            "raw_asset_beta": raw_beta,
            "adjusted_asset_beta": 0.67 * raw_beta + 0.33,
            "recommendation_score": item["recommendation_score"],
            "currency": quote_currency or financial_currency or "Unknown",
            "selection_method": selection_method,
            "source": f"{selection_method}; Yahoo Finance quote statistics and annual statements",
            **roic_metrics,
        })
    score_total = sum(max(0.0, row["recommendation_score"]) for row in rows)
    for row in rows:
        row["weight"] = (
            max(0.0, row["recommendation_score"]) / score_total
            if score_total > 0 else 1 / len(rows)
        )
    return rows


def selected_peer_beta(rows: list[dict[str, Any]]) -> float | None:
    usable = [row for row in rows if row.get("adjusted_asset_beta") is not None]
    if not usable:
        return None
    weight_total = sum(float(row.get("weight") or 0) for row in usable)
    if weight_total <= 0:
        return sum(float(row["adjusted_asset_beta"]) for row in usable) / len(usable)
    return sum(float(row["adjusted_asset_beta"]) * float(row.get("weight") or 0) for row in usable) / weight_total


def attach_yahoo_comparables(
    company: CompanyData,
    debt_beta: float = 0.15,
    comparable_tickers: list[str] | None = None,
    *,
    loader: Callable[..., list[dict[str, Any]]] = load_yahoo_peer_data,
) -> list[dict[str, Any]]:
    """Attach automatic comparable data without making provider failure fatal."""
    try:
        rows = loader(
            company.ticker, debt_beta=debt_beta,
            comparable_tickers=comparable_tickers or None,
        )
    except Exception:
        rows = []
    company.comparables = rows
    company.provenance.append(ProvenanceRecord(
        variable="comparable_companies",
        value=[row["peer"] for row in rows],
        source=YAHOO_QUOTE_URL.format(ticker=company.ticker),
        source_date=date.today().isoformat(),
        retrieval_method=(
            "User-defined comparables plus Yahoo Finance quote statistics and annual statements"
            if comparable_tickers else
            "Yahoo Finance People Also Watch plus peer quote statistics and annual statements"
        ),
        original_unit="mixed market data",
        normalized_unit="USD millions and beta",
        confidence="medium" if rows else "low",
        notes=(
            ("Equal-weighted adjusted asset beta from the user-defined peer set is used in TOCC."
             if comparable_tickers else "Recommendation-score-weighted adjusted asset beta is used in TOCC.")
            if rows else "Yahoo peer data unavailable; the disclosed sector-beta fallback is used."
        ),
    ))
    return rows
