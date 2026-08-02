from __future__ import annotations

import csv
from datetime import date
import logging
from pathlib import Path

from valuation_system.config import DEFAULT_SAMPLE_DATA
from valuation_system.models.company import CompanyData, HistoricalYear, ProvenanceRecord
from valuation_system.data.sp500_batch import NASDAQ_FINANCIALS, NASDAQ_SUMMARY, _fetch_json, _num, _table, _latest, _series

logger = logging.getLogger(__name__)


NUMERIC_FIELDS = {
    field for field in HistoricalYear.__dataclass_fields__ if field != "year"
}


def _load_sample(ticker: str, path: Path) -> CompanyData:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = [r for r in rows if r["ticker"].upper() == ticker.upper()]
    if not selected:
        raise ValueError(f"No offline sample data is available for {ticker}")
    historical = []
    for row in selected:
        values = {"year": int(row["year"])}
        values.update({name: float(row.get(name) or 0) for name in NUMERIC_FIELDS})
        historical.append(HistoricalYear(**values))
    last = selected[-1]
    provenance = [
        ProvenanceRecord(
            variable="Historical financial statements",
            value=f"{len(historical)} fiscal years",
            source=str(path),
            source_date=last["year"],
            retrieval_method="Offline sample CSV",
            confidence="medium",
            notes="Illustrative public-company dataset; refresh from SEC filings for investment use.",
        ),
        ProvenanceRecord(
            variable="Market price",
            value=float(last["share_price"]),
            source=str(path),
            source_date=last["year"],
            retrieval_method="Offline sample CSV",
            original_unit="USD/share",
            normalized_unit="USD/share",
            confidence="low",
            notes="Illustrative price, not a current quote.",
        ),
    ]
    return CompanyData(
        ticker=ticker.upper(),
        name=last["company_name"],
        sector=last["sector"],
        currency=last["currency"],
        historical=historical,
        share_price=float(last["share_price"]),
        diluted_shares=float(last["diluted_shares"]),
        basic_shares=float(last["basic_shares"]),
        rsus=float(last.get("rsus") or 0),
        options=float(last.get("options") or 0),
        option_strike=float(last.get("option_strike") or 0),
        warrants=float(last.get("warrants") or 0),
        convertibles=float(last.get("convertibles") or 0),
        provenance=provenance,
    )


def _load_yfinance(ticker: str) -> CompanyData:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed") from exc
    stock = yf.Ticker(ticker)
    info = stock.info
    financials = stock.financials
    balance = stock.balance_sheet
    cashflow = stock.cashflow
    if financials.empty or balance.empty or cashflow.empty:
        raise RuntimeError("Live provider returned incomplete financial statements")
    raise RuntimeError(
        "Live normalization requires SEC filing-specific tag review; use --data-file or the "
        "offline sample rather than accepting a silent low-confidence mapping."
    )


def load_nasdaq_company_data(ticker: str) -> CompanyData:
    """Load a normalized four-year company dataset from Nasdaq public endpoints.

    Nasdaq exposes four fiscal years. Items that are not separately disclosed by
    the endpoint remain explicitly documented in provenance rather than being
    presented as issuer-reported zero balances.
    """
    symbol = ticker.upper()
    financials = _fetch_json(NASDAQ_FINANCIALS.format(ticker=symbol))["data"]
    summary_payload = _fetch_json(NASDAQ_SUMMARY.format(ticker=symbol))["data"]
    periods, income = _table(financials, "incomeStatementTable")
    _, balance = _table(financials, "balanceSheetTable")
    _, cash_flow = _table(financials, "cashFlowTable")
    summary = (summary_payload or {}).get("summaryData") or {}
    price = _num((summary.get("PreviousClose") or {}).get("value"))
    market_cap = _num((summary.get("MarketCap") or {}).get("value"), 1_000_000.0)
    shares = market_cap / price if market_cap and price and price > 0 else None
    if price is None or shares is None:
        raise RuntimeError("Nasdaq market price or market capitalization is missing; provide an override/data file")
    revenue = _series(income, "Total Revenue")
    cogs = _series(income, "Cost of Revenue")
    sga = _series(income, "Sales, General and Admin.")
    rd = _series(income, "Research and Development")
    ebit = _series(income, "Operating Income", "Earnings Before Interest and Tax")
    taxes = _series(income, "Income Tax")
    depreciation = _series(cash_flow, "Depreciation")
    capex = _series(cash_flow, "Capital Expenditures")
    historical: list[HistoricalYear] = []
    for index, period in enumerate(periods):
        if not period or revenue[index] is None or ebit[index] is None:
            continue
        year = int(str(period).split("/")[-1])
        fixed_assets = (_series(balance, "Fixed Assets")[index] or 0.0)
        other_operating_assets = sum(x or 0.0 for x in [
            _series(balance, "Goodwill")[index],
            _series(balance, "Intangible Assets")[index],
            _series(balance, "Other Assets")[index],
        ])
        historical.append(HistoricalYear(
            year=year,
            revenue=revenue[index],
            cogs=cogs[index] or 0.0,
            sga=sga[index] or 0.0,
            rd=rd[index] or 0.0,
            da=depreciation[index] or 0.0,
            ebit=ebit[index],
            taxes=taxes[index] or 0.0,
            cash=_series(balance, "Cash and Cash Equivalents")[index] or 0.0,
            marketable_securities=_series(balance, "Short-Term Investments")[index] or 0.0,
            receivables=_series(balance, "Net Receivables")[index] or 0.0,
            inventory=_series(balance, "Inventory")[index] or 0.0,
            other_current_operating_assets=_series(balance, "Other Current Assets")[index] or 0.0,
            net_ppe=fixed_assets,
            operating_lease_assets=0.0,
            other_operating_assets=other_operating_assets,
            accounts_payable=_series(balance, "Accounts Payable")[index] or 0.0,
            accrued_operating_liabilities=_series(balance, "Other Current Liabilities")[index] or 0.0,
            deferred_revenue=0.0,
            other_operating_liabilities=0.0,
            debt=(_series(balance, "Short-Term Debt / Current Portion of Long-Term Debt")[index] or 0.0)
                + (_series(balance, "Long-Term Debt")[index] or 0.0),
            lease_liabilities=0.0,
            equity=_series(balance, "Total Equity")[index] or 0.0,
            capex=abs(capex[index] or 0.0),
        ))
    if len(historical) < 3:
        raise RuntimeError("Fewer than three usable annual periods were returned; provide a normalized data file")
    sector = (summary.get("Sector") or {}).get("value") or "Unknown"
    name = f"{symbol} public company"
    provenance = [
        ProvenanceRecord(
            variable="Annual financial statements",
            value=f"{len(historical)} fiscal years",
            source=NASDAQ_FINANCIALS.format(ticker=symbol),
            source_date=periods[0], retrieval_method="Nasdaq public JSON API",
            confidence="medium", notes="Endpoint provides four fiscal years; SEC filing review is recommended.",
        ),
        ProvenanceRecord(
            variable="Market price and capitalization", value=price,
            source=NASDAQ_SUMMARY.format(ticker=symbol), source_date=str(date.today()),
            retrieval_method="Nasdaq public JSON API", original_unit="USD/share",
            normalized_unit="USD/share", confidence="medium", notes="Previous-close convention.",
        ),
        ProvenanceRecord(
            variable="Unavailable separate classifications", value="n.m.",
            source="Nasdaq endpoint coverage", source_date=periods[0], retrieval_method="Mapping review",
            confidence="low", notes="Lease assets/liabilities and deferred revenue require filing-note overrides when material.",
        ),
    ]
    return CompanyData(
        ticker=symbol, name=name, sector=sector, currency="USD", historical=sorted(historical, key=lambda x: x.year),
        share_price=price, diluted_shares=shares, basic_shares=shares, provenance=provenance,
    )


def load_company_data(
    ticker: str,
    data_file: str | Path | None = None,
    live: bool = False,
) -> CompanyData:
    if live:
        try:
            return load_nasdaq_company_data(ticker)
        except Exception as exc:
            logger.warning("Live retrieval unavailable or unreliable: %s", exc)
    path = Path(data_file) if data_file else DEFAULT_SAMPLE_DATA
    return _load_sample(ticker, path)
