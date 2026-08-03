import pytest
import pandas as pd

from valuation_system.data.peer_data import (
    discover_yahoo_comparables, load_yahoo_peer_data, load_yahoo_roic_metrics,
    selected_peer_beta,
)


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"finance": {"result": [{"recommendedSymbols": [
            {"symbol": "AAA", "score": 0.6},
            {"symbol": "BBB", "score": 0.4},
        ]}]}}


def request_get(*_args, **_kwargs):
    return Response()


def test_discovers_yahoo_people_also_watch_symbols():
    assert discover_yahoo_comparables("TEST", request_get=request_get) == [
        {"peer": "AAA", "recommendation_score": 0.6},
        {"peer": "BBB", "recommendation_score": 0.4},
    ]


def test_peer_statistics_drive_weighted_adjusted_asset_beta():
    info = {
        "AAA": {"quoteType": "EQUITY", "shortName": "Alpha", "beta": 1.5, "marketCap": 100_000_000, "totalDebt": 20_000_000},
        "BBB": {"quoteType": "EQUITY", "shortName": "Beta", "beta": 1.0, "marketCap": 50_000_000, "totalDebt": 10_000_000},
    }
    rows = load_yahoo_peer_data(
        "TEST", request_get=request_get, info_loader=info.__getitem__,
        metric_loader=lambda symbol: {"ebit_margin": {"AAA": 0.20, "BBB": 0.10}[symbol]},
    )
    assert [row["peer"] for row in rows] == ["AAA", "BBB"]
    assert [row["weight"] for row in rows] == pytest.approx([0.6, 0.4])
    expected = rows[0]["adjusted_asset_beta"] * 0.6 + rows[1]["adjusted_asset_beta"] * 0.4
    assert selected_peer_beta(rows) == pytest.approx(expected)
    assert [row["ebit_margin"] for row in rows] == pytest.approx([0.20, 0.10])


def test_user_defined_comparables_override_yahoo_selection():
    info = {
        symbol: {"quoteType": "EQUITY", "shortName": symbol, "beta": 1.0,
                 "marketCap": 100_000_000, "totalDebt": 10_000_000}
        for symbol in ["AAA", "BBB"]
    }
    rows = load_yahoo_peer_data(
        "TEST", comparable_tickers=["BBB", "AAA"],
        request_get=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("automatic selection should not run")),
        info_loader=info.__getitem__, metric_loader=lambda _symbol: {},
    )
    assert [row["peer"] for row in rows] == ["BBB", "AAA"]
    assert [row["weight"] for row in rows] == pytest.approx([0.5, 0.5])
    assert all(row["selection_method"] == "User-defined comparable" for row in rows)


def test_kevin_lecture_roic_tree_metrics_from_yahoo_statements(monkeypatch):
    current, prior = pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")
    income = pd.DataFrame({
        current: [100, 20, 20, 4, 60, 10, 5],
        prior: [80, 12, 12, 2, 50, 9, 4],
    }, index=[
        "TotalRevenue", "OperatingIncome", "PretaxIncome", "TaxProvision",
        "CostOfRevenue", "SellingGeneralAndAdministration", "ResearchAndDevelopment",
    ])
    balance = pd.DataFrame({
        current: [100, 10, 30, 8, 5, 50, 30, 5, 12],
        prior: [100, 8, 28, 7, 4, 45, 27, 4, 10],
    }, index=[
        "InvestedCapital", "CashCashEquivalentsAndShortTermInvestments", "NetPPE",
        "Receivables", "Inventory", "CurrentAssets", "CurrentLiabilities",
        "CurrentDebt", "AccountsPayable",
    ])

    class Ticker:
        def get_income_stmt(self, **_kwargs): return income
        def get_balance_sheet(self, **_kwargs): return balance

    monkeypatch.setattr("yfinance.Ticker", lambda _symbol: Ticker())
    metrics = load_yahoo_roic_metrics("TEST")
    assert metrics["revenue_growth"] == pytest.approx(0.25)
    assert metrics["after_tax_roic"] == pytest.approx(0.16)
    assert metrics["pre_tax_roic"] == pytest.approx(0.20)
    assert metrics["ebit_margin"] == pytest.approx(0.20)
    assert metrics["capital_turnover"] == pytest.approx(1.0)
    assert metrics["wcr_revenue"] == pytest.approx(0.15)
