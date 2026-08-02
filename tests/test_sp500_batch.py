import json

from valuation_system.data.sp500_batch import _provider_ticker, value_sp500


def test_nasdaq_class_share_symbol_is_preserved():
    assert _provider_ticker("BRK.B") == "BRK.B"


def test_financial_company_is_not_forced_into_standard_apv():
    rows, summary = value_sp500([
        {
            "ticker": "TEST",
            "company": "Test Bank",
            "sector": "Financials",
            "sub_industry": "Banks",
            "cik": 1,
            "error": "provider unavailable",
        }
    ])
    assert rows[0].status == "N/A – FINANCIAL"
    assert rows[0].intrinsic_value_per_share is None
    assert summary["financial_count"] == 1


def test_sp500_screen_labels_three_period_methodology():
    _, summary = value_sp500([])
    assert summary["forecast_years"] == 10
    assert summary["competitive_advantage_years"] == 10
