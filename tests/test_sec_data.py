import pytest
import pandas as pd

from valuation_system.data import company_data


def _annual_entries(years, values, *, instant=False, unit="USD"):
    rows = []
    for year, value in zip(years, values):
        row = {
            "end": f"{year}-12-31", "val": value, "form": "10-K",
            "filed": f"{year + 1}-02-20", "fy": year, "fp": "FY",
        }
        if not instant:
            row["start"] = f"{year}-01-01"
        rows.append(row)
    return {"units": {unit: rows}}


def _sec_payload():
    years = list(range(2019, 2025))
    revenue = [1_000_000_000 + index * 100_000_000 for index in range(len(years))]
    ebit = [100_000_000 + index * 10_000_000 for index in range(len(years))]
    us_gaap = {
        "Revenues": _annual_entries(years, revenue),
        "OperatingIncomeLoss": _annual_entries(years, ebit),
        "CostOfRevenue": _annual_entries(years, [value * 0.6 for value in revenue]),
        "SellingGeneralAndAdministrativeExpense": _annual_entries(years, [value * 0.2 for value in revenue]),
        "DepreciationDepletionAndAmortization": _annual_entries(years, [50_000_000] * len(years)),
        "IncomeTaxExpenseBenefit": _annual_entries(years, [20_000_000] * len(years)),
        "PaymentsToAcquirePropertyPlantAndEquipment": _annual_entries(years, [70_000_000] * len(years)),
        "CashAndCashEquivalentsAtCarryingValue": _annual_entries(years, [300_000_000] * len(years), instant=True),
        "AccountsReceivableNetCurrent": _annual_entries(years, [120_000_000] * len(years), instant=True),
        "InventoryNet": _annual_entries(years, [90_000_000] * len(years), instant=True),
        "PropertyPlantAndEquipmentNet": _annual_entries(years, [500_000_000] * len(years), instant=True),
        "AccountsPayableCurrent": _annual_entries(years, [80_000_000] * len(years), instant=True),
        "LongTermDebtNoncurrent": _annual_entries(years, [200_000_000] * len(years), instant=True),
        "StockholdersEquity": _annual_entries(years, [700_000_000] * len(years), instant=True),
        "WeightedAverageNumberOfDilutedSharesOutstanding": _annual_entries(years, [100_000_000] * len(years), unit="shares"),
    }
    dei = {
        "EntityCommonStockSharesOutstanding": _annual_entries(
            years, [100_000_000] * len(years), instant=True, unit="shares"
        )
    }
    return {
        "entityName": "Test Corporation", "sicDescription": "Industrial Machinery",
        "facts": {"us-gaap": us_gaap, "dei": dei},
    }


def test_sec_company_facts_normalizes_latest_five_years(monkeypatch):
    monkeypatch.setattr(company_data, "_sec_ticker_map", lambda _user_agent: {"TEST": 1})
    monkeypatch.setattr(company_data, "_sec_get_json", lambda _url, **_kwargs: _sec_payload())
    monkeypatch.setattr(company_data, "_sec_market_data", lambda _ticker: (10.0, 1_000.0))

    company = company_data.load_sec_company_data("test", "Test Application test@example.com")

    assert [row.year for row in company.historical] == [2020, 2021, 2022, 2023, 2024]
    assert company.historical[-1].revenue == 1_500.0
    assert company.basic_shares == 100.0
    assert company.market_cap == 1_000.0
    assert company.provenance[0].retrieval_method == "SEC Company Facts API"


def test_uploaded_data_takes_precedence_over_sec(monkeypatch):
    monkeypatch.setattr(
        company_data, "load_sec_company_data",
        lambda _ticker: (_ for _ in ()).throw(AssertionError("SEC should not be called")),
    )
    company = company_data.load_company_data("DEMO", "sample_company_data.csv", live=True)
    assert len(company.historical) == 5
    assert company.provenance[0].retrieval_method == "Offline sample CSV"


def test_sec_requires_declared_contact_before_request(monkeypatch):
    monkeypatch.setattr(
        company_data.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("request should not be sent")),
    )
    with pytest.raises(RuntimeError, match="contact email"):
        company_data._sec_get_json("https://data.sec.gov/example.json", attempts=1, user_agent="Stock-Valuation")


def test_yahoo_foreign_issuer_fallback_normalizes_statements_and_fx():
    columns = [pd.Timestamp(f"{year}-12-31") for year in (2025, 2024, 2023, 2022)]
    income = pd.DataFrame({column: [100_000_000, 20_000_000, 60_000_000, 5_000_000, 10_000_000, 4_000_000, 100_000_000] for column in columns}, index=[
        "TotalRevenue", "OperatingIncome", "CostOfRevenue", "SellingGeneralAndAdministration",
        "ResearchAndDevelopment", "TaxProvision", "DilutedAverageShares",
    ], dtype=float)
    balance = pd.DataFrame({column: [10_000_000, 2_000_000, 8_000_000, 5_000_000, 3_000_000, 1_000_000, 30_000_000, 20_000_000, 5_000_000, 1_000_000, 2_000_000, 4_000_000, 25_000_000, 1_000_000, 50_000_000] for column in columns}, index=[
        "CashAndCashEquivalents", "OtherShortTermInvestments", "Receivables", "Inventory",
        "OtherCurrentAssets", "AccountsPayable", "PayablesAndAccruedExpenses", "CurrentLiabilities",
        "CurrentDebt", "CurrentDeferredRevenue", "NonCurrentDeferredRevenue", "NetPPE", "TotalDebt",
        "CapitalLeaseObligations", "StockholdersEquity",
    ], dtype=float)
    cash_flow = pd.DataFrame({column: [3_000_000, -6_000_000, 500_000] for column in columns}, index=[
        "DepreciationAmortizationDepletion", "CapitalExpenditure", "StockBasedCompensation",
    ], dtype=float)
    income.loc[:, columns[-1]] = float("nan")
    balance.loc[:, columns[-1]] = float("nan")
    cash_flow.loc[:, columns[-1]] = float("nan")

    class Security:
        def get_income_stmt(self, **_kwargs): return income
        def get_balance_sheet(self, **_kwargs): return balance
        def get_cash_flow(self, **_kwargs): return cash_flow
        def get_info(self): return {"shortName": "Test Foreign Co", "sector": "Industrials", "financialCurrency": "EUR", "currency": "USD", "currentPrice": 10.0, "marketCap": 1_000_000_000, "sharesOutstanding": 100_000_000}

    class Fx:
        fast_info = {"last_price": 1.10}

    company = company_data.load_yahoo_company_data(
        "TEST", ticker_factory=lambda symbol: Fx() if symbol == "EURUSD=X" else Security(),
    )
    assert [row.year for row in company.historical] == [2023, 2024, 2025]
    assert company.latest.revenue == pytest.approx(110.0)
    assert company.latest.capex == pytest.approx(6.6)
    assert company.currency == "USD"
    assert company.market_cap == pytest.approx(1_000.0)
    assert company.provenance[1].value == pytest.approx(1.10)


def test_live_loader_uses_yahoo_before_offline_sample(monkeypatch):
    expected = company_data._load_sample("DEMO", company_data.DEFAULT_SAMPLE_DATA)
    monkeypatch.setattr(company_data, "load_sec_company_data", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("insufficient SEC periods")))
    monkeypatch.setattr(company_data, "load_yahoo_company_data", lambda _ticker: expected)
    assert company_data.load_company_data("ANY", live=True) is expected
