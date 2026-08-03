from __future__ import annotations

import csv
from datetime import date, datetime
from functools import lru_cache
import logging
import math
import os
from pathlib import Path
import time
from typing import Any

import requests

from valuation_system.config import DEFAULT_SAMPLE_DATA
from valuation_system.models.company import CompanyData, HistoricalYear, ProvenanceRecord
from valuation_system.data.sp500_batch import NASDAQ_FINANCIALS, NASDAQ_SUMMARY, _fetch_json, _num, _table, _latest, _series

logger = logging.getLogger(__name__)


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip()
SEC_ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


NUMERIC_FIELDS = {
    field for field in HistoricalYear.__dataclass_fields__ if field != "year"
}


def _load_sample(ticker: str, path: Path) -> CompanyData:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = sorted(
        [r for r in rows if r["ticker"].upper() == ticker.upper()],
        key=lambda row: int(row["year"]),
    )
    if not selected:
        raise ValueError(f"No offline sample data is available for {ticker}")
    historical = []
    for row in selected:
        values = {"year": int(row["year"])}
        values.update({name: float(row.get(name) or 0) for name in NUMERIC_FIELDS})
        historical.append(HistoricalYear(**values))
    historical = sorted(historical, key=lambda item: item.year)[-5:]
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
        market_cap=float(last["share_price"]) * float(last["basic_shares"]),
        rsus=float(last.get("rsus") or 0),
        options=float(last.get("options") or 0),
        option_strike=float(last.get("option_strike") or 0),
        warrants=float(last.get("warrants") or 0),
        convertibles=float(last.get("convertibles") or 0),
        provenance=provenance,
    )


def _sec_get_json(url: str, attempts: int = 4, user_agent: str | None = None) -> dict[str, Any]:
    declared_agent = (user_agent or SEC_USER_AGENT).strip()
    if "@" not in declared_agent:
        raise RuntimeError("SEC requires an identifying user agent with a contact email. Set SEC_USER_AGENT or enter an SEC contact email in the app.")
    headers = {
        "User-Agent": declared_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"SEC request failed after {attempts} attempts: {last_error}")


@lru_cache(maxsize=16)
def _sec_ticker_map(user_agent: str) -> dict[str, int]:
    payload = _sec_get_json(SEC_TICKERS_URL, user_agent=user_agent)
    return {
        str(row["ticker"]).upper(): int(row["cik_str"])
        for row in payload.values()
        if row.get("ticker") and row.get("cik_str") is not None
    }


def _annual_concept(
    payload: dict[str, Any],
    tags: tuple[str, ...],
    *,
    unit: str = "USD",
    instant: bool = False,
    taxonomies: tuple[str, ...] = ("us-gaap", "ifrs-full", "dei"),
) -> dict[int, float]:
    selected: dict[int, tuple[str, float]] = {}
    facts = payload.get("facts") or {}
    for taxonomy in taxonomies:
        taxonomy_facts = facts.get(taxonomy) or {}
        for tag in tags:
            concept = taxonomy_facts.get(tag) or {}
            units = concept.get("units") or {}
            entries = units.get(unit) or []
            tag_selected: dict[int, tuple[str, float]] = {}
            for entry in entries:
                if entry.get("form") not in SEC_ANNUAL_FORMS or entry.get("val") is None or not entry.get("end"):
                    continue
                if not instant:
                    if not entry.get("start"):
                        continue
                    try:
                        duration = (datetime.fromisoformat(entry["end"]) - datetime.fromisoformat(entry["start"])).days
                    except ValueError:
                        continue
                    if not 300 <= duration <= 400:
                        continue
                try:
                    year = datetime.fromisoformat(entry["end"]).year
                    value = float(entry["val"])
                except (TypeError, ValueError):
                    continue
                filed = str(entry.get("filed") or "")
                if year not in tag_selected or filed > tag_selected[year][0]:
                    tag_selected[year] = (filed, value)
            for year, candidate in tag_selected.items():
                selected.setdefault(year, candidate)
        if selected:
            break
    return {year: value for year, (_, value) in selected.items()}


def _series_value(series: dict[int, float], year: int, scale: float = 1_000_000.0) -> float:
    return float(series.get(year, 0.0)) / scale


def _sec_market_data(symbol: str) -> tuple[float | None, float | None]:
    try:
        summary_payload = _fetch_json(NASDAQ_SUMMARY.format(ticker=symbol))["data"]
        summary = (summary_payload or {}).get("summaryData") or {}
        price = _num((summary.get("PreviousClose") or {}).get("value"))
        market_cap = _num((summary.get("MarketCap") or {}).get("value"), 1_000_000.0)
        return price, market_cap
    except Exception as exc:
        logger.warning("Market-data retrieval failed after SEC download: %s", exc)
        return None, None


def load_sec_company_data(ticker: str, user_agent: str | None = None) -> CompanyData:
    """Download and normalize the latest five annual periods from SEC Company Facts."""
    symbol = ticker.upper().strip()
    declared_agent = (user_agent or SEC_USER_AGENT).strip()
    cik = _sec_ticker_map(declared_agent).get(symbol)
    if cik is None:
        raise RuntimeError(f"SEC ticker-to-CIK mapping is unavailable for {symbol}")
    source_url = SEC_COMPANY_FACTS_URL.format(cik=cik)
    payload = _sec_get_json(source_url, user_agent=declared_agent)

    revenue = _annual_concept(payload, ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "Revenue"))
    ebit = _annual_concept(payload, ("OperatingIncomeLoss", "OperatingProfitLoss"))
    years = sorted(set(revenue) & set(ebit))[-5:]
    if len(years) < 3:
        raise RuntimeError("SEC Company Facts returned fewer than three comparable annual periods; upload reviewed financial data")

    duration_tags = {
        "cogs": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales"),
        "sga": ("SellingGeneralAndAdministrativeExpense", "SellingAndMarketingExpense"),
        "rd": ("ResearchAndDevelopmentExpense",),
        "da": ("DepreciationDepletionAndAmortization", "Depreciation", "DepreciationAndAmortization"),
        "taxes": ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"),
        "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipment"),
        "stock_comp": ("ShareBasedCompensation", "ShareBasedPayment"),
    }
    instant_tags = {
        "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"),
        "marketable_securities": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
        "receivables": ("AccountsReceivableNetCurrent", "TradeAndOtherCurrentReceivables"),
        "inventory": ("InventoryNet", "Inventories"),
        "other_current_operating_assets": ("OtherCurrentAssets", "OtherCurrentNonfinancialAssets"),
        "net_ppe": ("PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipment"),
        "operating_lease_assets": ("OperatingLeaseRightOfUseAsset", "RightOfUseAsset"),
        "accounts_payable": ("AccountsPayableCurrent", "TradeAndOtherCurrentPayables"),
        "accrued_operating_liabilities": ("AccruedLiabilitiesCurrent", "OtherCurrentLiabilities"),
        "deferred_revenue": ("ContractWithCustomerLiabilityCurrent", "ContractLiabilitiesCurrent"),
        "other_operating_liabilities": ("OtherLiabilitiesNoncurrent", "OtherNoncurrentLiabilities"),
        "debt_current": ("LongTermDebtCurrent", "ShortTermBorrowings"),
        "debt_noncurrent": ("LongTermDebtNoncurrent", "LongTermDebt"),
        "lease_current": ("OperatingLeaseLiabilityCurrent",),
        "lease_noncurrent": ("OperatingLeaseLiabilityNoncurrent", "LeaseLiabilitiesNoncurrent"),
        "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"),
        "goodwill": ("Goodwill",),
        "intangibles": ("FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill", "IntangibleAssetsOtherThanGoodwill"),
    }
    duration = {name: _annual_concept(payload, tags) for name, tags in duration_tags.items()}
    instant = {name: _annual_concept(payload, tags, instant=True) for name, tags in instant_tags.items()}

    historical: list[HistoricalYear] = []
    for year in years:
        historical.append(HistoricalYear(
            year=year,
            revenue=_series_value(revenue, year),
            cogs=abs(_series_value(duration["cogs"], year)),
            sga=abs(_series_value(duration["sga"], year)),
            rd=abs(_series_value(duration["rd"], year)),
            da=abs(_series_value(duration["da"], year)),
            ebit=_series_value(ebit, year),
            taxes=_series_value(duration["taxes"], year),
            cash=_series_value(instant["cash"], year),
            marketable_securities=_series_value(instant["marketable_securities"], year),
            receivables=_series_value(instant["receivables"], year),
            inventory=_series_value(instant["inventory"], year),
            other_current_operating_assets=_series_value(instant["other_current_operating_assets"], year),
            net_ppe=_series_value(instant["net_ppe"], year),
            operating_lease_assets=_series_value(instant["operating_lease_assets"], year),
            other_operating_assets=_series_value(instant["goodwill"], year) + _series_value(instant["intangibles"], year),
            accounts_payable=_series_value(instant["accounts_payable"], year),
            accrued_operating_liabilities=_series_value(instant["accrued_operating_liabilities"], year),
            deferred_revenue=_series_value(instant["deferred_revenue"], year),
            other_operating_liabilities=_series_value(instant["other_operating_liabilities"], year),
            debt=_series_value(instant["debt_current"], year) + _series_value(instant["debt_noncurrent"], year),
            lease_liabilities=_series_value(instant["lease_current"], year) + _series_value(instant["lease_noncurrent"], year),
            equity=_series_value(instant["equity"], year),
            capex=abs(_series_value(duration["capex"], year)),
            stock_comp=abs(_series_value(duration["stock_comp"], year)),
        ))

    common_shares = _annual_concept(payload, ("EntityCommonStockSharesOutstanding",), unit="shares", instant=True, taxonomies=("dei", "us-gaap"))
    diluted = _annual_concept(payload, ("WeightedAverageNumberOfDilutedSharesOutstanding",), unit="shares")
    latest_year = years[-1]
    basic_shares = _series_value(common_shares, max(common_shares)) if common_shares else 0.0
    diluted_shares = _series_value(diluted, latest_year)
    if diluted_shares <= 0 and diluted:
        diluted_shares = _series_value(diluted, max(diluted))
    diluted_shares = diluted_shares or basic_shares
    price, market_cap = _sec_market_data(symbol)
    if basic_shares <= 0 and price and market_cap:
        basic_shares = market_cap / price
    if diluted_shares <= 0:
        diluted_shares = basic_shares
    if basic_shares <= 0:
        raise RuntimeError("SEC share-count facts are missing; upload reviewed data or provide a supported ticker")
    if market_cap is None and price is not None:
        market_cap = price * basic_shares

    period_note = "Latest five comparable annual periods." if len(years) == 5 else f"Only {len(years)} comparable annual periods were available."
    provenance = [
        ProvenanceRecord(
            variable="Historical financial statements", value=f"{len(years)} fiscal years",
            source=source_url, source_date=str(years[-1]), retrieval_method="SEC Company Facts API",
            confidence="medium", notes=period_note + " Standard-taxonomy mappings require filing review when material.",
        ),
        ProvenanceRecord(
            variable="Share counts", value=basic_shares, source=source_url,
            source_date=str(years[-1]), retrieval_method="SEC Company Facts API",
            original_unit="shares", normalized_unit="millions of shares", confidence="medium",
        ),
        ProvenanceRecord(
            variable="Market price and capitalization", value=market_cap if market_cap is not None else "n.m.",
            source=NASDAQ_SUMMARY.format(ticker=symbol), source_date=str(date.today()),
            retrieval_method="Nasdaq public JSON API after SEC financial download",
            original_unit="USD", normalized_unit="USD millions", confidence="medium",
            notes="Previous-close market data; financial statements are sourced from SEC Company Facts.",
        ),
    ]
    return CompanyData(
        ticker=symbol, name=str(payload.get("entityName") or f"{symbol} public company"),
        sector=str(payload.get("sicDescription") or "Unknown"), currency="USD",
        historical=historical, share_price=price, diluted_shares=diluted_shares,
        basic_shares=basic_shares, market_cap=market_cap, provenance=provenance,
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
        ticker=symbol, name=name, sector=sector, currency="USD", historical=sorted(historical, key=lambda x: x.year)[-5:],
        share_price=price, diluted_shares=shares, basic_shares=shares,
        market_cap=market_cap, provenance=provenance,
    )


def _yahoo_statement_value(frame: Any, label: str, column: Any, default: float = 0.0) -> float:
    try:
        value = float(frame.loc[label, column])
        return value if math.isfinite(value) else default
    except (KeyError, TypeError, ValueError):
        return default


def load_yahoo_company_data(ticker: str, ticker_factory: Any | None = None) -> CompanyData:
    """Normalize five Yahoo annual statements when SEC Company Facts is insufficient."""
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    symbol = ticker.upper().strip()
    security = ticker_factory(symbol)
    income = security.get_income_stmt(freq="yearly")
    balance = security.get_balance_sheet(freq="yearly")
    cash_flow = security.get_cash_flow(freq="yearly")
    info = security.get_info() or {}
    candidate_columns = sorted(
        set(income.columns) & set(balance.columns) & set(cash_flow.columns), reverse=True,
    )
    common_columns = [
        column for column in candidate_columns
        if _yahoo_statement_value(income, "TotalRevenue", column) > 0
        and math.isfinite(_yahoo_statement_value(income, "OperatingIncome", column, float("nan")))
    ][:5]
    if len(common_columns) < 3:
        raise RuntimeError("Yahoo Finance returned fewer than three comparable annual periods")

    statement_currency = str(info.get("financialCurrency") or info.get("currency") or "USD").upper()
    quote_currency = str(info.get("currency") or statement_currency).upper()
    fx_rate = 1.0
    fx_source = "No conversion required"
    if statement_currency != quote_currency:
        fx_symbol = f"{statement_currency}{quote_currency}=X"
        fx_security = ticker_factory(fx_symbol)
        fast_info = fx_security.fast_info
        fx_rate = float(fast_info["last_price"] if isinstance(fast_info, dict) else fast_info.last_price)
        if not math.isfinite(fx_rate) or fx_rate <= 0:
            raise RuntimeError(f"Yahoo FX rate unavailable for {statement_currency}/{quote_currency}")
        fx_source = f"Yahoo Finance {fx_symbol} current rate {fx_rate:.6f}"

    def money(frame: Any, label: str, column: Any, default: float = 0.0) -> float:
        return _yahoo_statement_value(frame, label, column, default) / 1_000_000 * fx_rate

    historical: list[HistoricalYear] = []
    for column in sorted(common_columns):
        accounts_payable = money(balance, "AccountsPayable", column)
        payables_accrued = money(balance, "PayablesAndAccruedExpenses", column)
        current_liabilities = money(balance, "CurrentLiabilities", column)
        current_debt = money(balance, "CurrentDebt", column)
        current_deferred = money(balance, "CurrentDeferredRevenue", column)
        noncurrent_deferred = money(balance, "NonCurrentDeferredRevenue", column)
        cash = money(balance, "CashAndCashEquivalents", column)
        short_investments = money(balance, "OtherShortTermInvestments", column)
        historical.append(HistoricalYear(
            year=int(column.year),
            revenue=money(income, "TotalRevenue", column),
            cogs=abs(money(income, "CostOfRevenue", column)),
            sga=abs(money(income, "SellingGeneralAndAdministration", column)),
            rd=abs(money(income, "ResearchAndDevelopment", column)),
            da=abs(money(cash_flow, "DepreciationAmortizationDepletion", column)) or abs(money(income, "ReconciledDepreciation", column)),
            ebit=money(income, "OperatingIncome", column) or money(income, "EBIT", column),
            taxes=money(income, "TaxProvision", column),
            cash=cash,
            marketable_securities=short_investments,
            receivables=money(balance, "Receivables", column),
            inventory=money(balance, "Inventory", column),
            other_current_operating_assets=money(balance, "OtherCurrentAssets", column),
            net_ppe=money(balance, "NetPPE", column),
            operating_lease_assets=0.0,
            other_operating_assets=money(balance, "GoodwillAndOtherIntangibleAssets", column),
            accounts_payable=accounts_payable,
            accrued_operating_liabilities=max(0.0, payables_accrued - accounts_payable),
            deferred_revenue=current_deferred,
            other_operating_liabilities=max(
                0.0, current_liabilities - current_debt - payables_accrued - current_deferred,
            ) + noncurrent_deferred,
            debt=money(balance, "TotalDebt", column),
            lease_liabilities=money(balance, "CapitalLeaseObligations", column),
            equity=money(balance, "StockholdersEquity", column),
            capex=abs(money(cash_flow, "CapitalExpenditure", column)),
            stock_comp=abs(money(cash_flow, "StockBasedCompensation", column)),
        ))
    latest_column = common_columns[0]
    basic_shares = float(info.get("sharesOutstanding") or _yahoo_statement_value(balance, "OrdinarySharesNumber", latest_column)) / 1_000_000
    diluted_shares = _yahoo_statement_value(income, "DilutedAverageShares", latest_column) / 1_000_000 or basic_shares
    share_price = info.get("currentPrice") or info.get("regularMarketPrice")
    share_price = float(share_price) if share_price is not None else None
    market_cap = float(info["marketCap"]) / 1_000_000 if info.get("marketCap") else (
        share_price * basic_shares if share_price is not None else None
    )
    if basic_shares <= 0 or share_price is None:
        raise RuntimeError("Yahoo Finance share price or share count is unavailable")
    source_url = f"https://finance.yahoo.com/quote/{symbol}/financials/"
    provenance = [
        ProvenanceRecord(
            variable="Historical financial statements", value=f"{len(historical)} fiscal years",
            source=source_url, source_date=str(max(row.year for row in historical)),
            retrieval_method="Yahoo Finance annual statements fallback",
            confidence="medium",
            notes="Used after SEC Company Facts did not provide sufficient comparable annual periods.",
        ),
        ProvenanceRecord(
            variable="Statement currency conversion", value=fx_rate,
            source=fx_source, source_date=str(date.today()), retrieval_method="Yahoo Finance FX quote",
            original_unit=statement_currency, normalized_unit=quote_currency,
            confidence="medium", notes="All statement amounts were converted to the security's quote currency.",
        ),
        ProvenanceRecord(
            variable="Market price and capitalization", value=market_cap,
            source=f"https://finance.yahoo.com/quote/{symbol}/", source_date=str(date.today()),
            retrieval_method="Yahoo Finance quote statistics", original_unit=f"{quote_currency}/share",
            normalized_unit=f"{quote_currency}/share and {quote_currency} millions", confidence="medium",
        ),
    ]
    return CompanyData(
        ticker=symbol, name=info.get("shortName") or info.get("longName") or symbol,
        sector=info.get("sector") or "Unknown", currency=quote_currency,
        historical=historical, share_price=share_price, diluted_shares=diluted_shares,
        basic_shares=basic_shares, market_cap=market_cap, provenance=provenance,
    )


def load_company_data(
    ticker: str,
    data_file: str | Path | None = None,
    live: bool = False,
    sec_user_agent: str | None = None,
) -> CompanyData:
    if data_file is not None:
        return _load_sample(ticker, Path(data_file))
    if live:
        try:
            return load_sec_company_data(ticker, sec_user_agent)
        except Exception as exc:
            logger.warning("SEC retrieval unavailable or unreliable: %s", exc)
        try:
            return load_yahoo_company_data(ticker)
        except Exception as exc:
            logger.warning("Yahoo annual-statement fallback unavailable: %s", exc)
    return _load_sample(ticker, DEFAULT_SAMPLE_DATA)
