from pathlib import Path

import pytest

from valuation_system.analysis.engine import run_valuation
from valuation_system.data.company_data import load_company_data
from valuation_system.models.assumptions import (
    ValuationAssumptions, apply_scenario_overrides, parse_scenario_spec,
)
from valuation_system.ui.components import (
    build_valuation_config, clean_ticker, parse_optional_float,
    parse_peer_tickers, run_company_valuation, validate_scenario_probabilities,
    validate_terminal_growth,
)
from valuation_system.ui.formatting import (
    format_currency, format_large_currency, format_percentage,
)


def test_ticker_cleaning_and_validation():
    assert clean_ticker(" rivn ") == "RIVN"
    assert clean_ticker("brk.b") == "BRK.B"
    with pytest.raises(ValueError):
        clean_ticker("bad ticker!")


def test_peer_ticker_parsing():
    assert parse_peer_tickers(" TSLA, gm, F, TSLA, LCID ") == ["TSLA", "GM", "F", "LCID"]
    with pytest.raises(ValueError):
        parse_peer_tickers("TSLA, BAD PEER")


def test_blank_optional_input_handling():
    assert parse_optional_float("") is None
    assert parse_optional_float(None) is None
    assert parse_optional_float("0.125") == pytest.approx(0.125)


def test_terminal_growth_validation():
    validate_terminal_growth(0.025, 0.09)
    with pytest.raises(ValueError):
        validate_terminal_growth(0.09, 0.09)


def test_scenario_probability_validation():
    assumptions = ValuationAssumptions()
    validate_scenario_probabilities(assumptions.scenarios)
    assert [scenario.probability for scenario in assumptions.scenarios.values()] == [0.25] * 4
    bad = ValuationAssumptions().scenarios
    bad["base"].probability = 0.39
    with pytest.raises(ValueError):
        validate_scenario_probabilities(bad)


def test_cli_scenario_inputs_and_probability_overrides():
    name, values = parse_scenario_spec("downside;revenue_growth_delta=-0.08;tocc_delta=0.015")
    assert name == "downside"
    assert values["revenue_growth_delta"] == pytest.approx(-0.08)
    assumptions = ValuationAssumptions()
    apply_scenario_overrides(
        assumptions,
        ["downside;ebit_margin_delta=-0.06", "upside;new_shares=25"],
        ["failure=10", "downside=20", "base=50", "upside=20"],
    )
    assumptions.validate()
    assert assumptions.scenarios["base"].probability == pytest.approx(0.50)
    assert assumptions.scenarios["downside"].ebit_margin_delta == pytest.approx(-0.06)
    assert assumptions.scenarios["upside"].new_shares == pytest.approx(25)


def test_ui_configuration_accepts_scenario_inputs():
    scenarios = {
        "failure": {"probability": 0.10, "revenue_growth_delta": 99},
        "downside": {"probability": 0.20, "revenue_growth_delta": 99},
        "base": {"probability": 0.50},
        "upside": {"probability": 0.20},
    }
    config = build_valuation_config(
        ticker="RIVN", valuation_date="2026-08-02", forecast_years=10,
        currency="USD", peer_tickers="TSLA, GM", terminal_growth_rate=0.025,
        scenarios=scenarios,
    )
    assert config.scenarios["downside"].probability == pytest.approx(0.20)
    assert config.scenarios["downside"].revenue_growth_delta == pytest.approx(-0.05)


def test_configuration_object_creation():
    config = build_valuation_config(
        ticker=" rivn ", valuation_date="2026-08-02", forecast_years=10,
        currency="USD", peer_tickers="TSLA, GM", terminal_growth_rate=0.025,
        risk_free_rate=None, market_risk_premium=0.0418, selected_asset_beta=None,
    )
    assert config.ticker == "RIVN"
    assert config.peer_tickers == ["TSLA", "GM"]
    assert config.risk_free_rate is None


def test_result_formatting():
    assert format_currency(-12.5) == "($12.50)"
    assert format_percentage(-0.125) == "(12.5%)"
    assert format_large_currency(12_500) == "$12.5bn"
    assert format_large_currency(776_000) == "$776.0bn"
    assert format_currency(None) == "—"


def test_engine_invocation_and_download_files(tmp_path):
    called = {"engine": False}

    def engine(company, assumptions):
        called["engine"] = True
        return run_valuation(company, assumptions)

    def excel(result, path):
        path = Path(path)
        path.write_bytes(b"workbook")
        return path

    def report(result, path):
        path = Path(path)
        path.write_text("report")
        return path

    config = build_valuation_config(
        ticker="RIVN", valuation_date="2026-08-02", forecast_years=10,
        currency="USD", peer_tickers="TSLA, GM, F, LCID", terminal_growth_rate=0.025,
        data_file="sample_company_data.csv", output_dir=str(tmp_path),
    )
    peers = lambda *_args, **_kwargs: [
        {"peer": "TSLA", "company_name": "Tesla", "equity_beta": 2.0, "equity": 100,
         "debt": 10, "debt_beta": 0.15, "raw_asset_beta": 1.83,
         "adjusted_asset_beta": 1.56, "recommendation_score": 1.0, "weight": 1.0,
         "source": "test"}
    ]
    artifacts = run_company_valuation(config, engine_runner=engine, excel_exporter=excel, report_exporter=report, peer_loader=peers)
    assert called["engine"] is True
    assert artifacts.result.ticker == "RIVN"
    assert artifacts.excel_path.exists()
    assert artifacts.report_path.exists()
    assert artifacts.assumptions_path.exists()
    assert artifacts.source_data_path.exists()


def test_unsupported_financial_company_handling(tmp_path):
    company = load_company_data("RIVN")
    company.sector = "Banking"

    def loader(*_args, **_kwargs):
        return company

    config = build_valuation_config(
        ticker="RIVN", valuation_date="2026-08-02", forecast_years=10,
        currency="USD", peer_tickers="TSLA", terminal_growth_rate=0.025,
        output_dir=str(tmp_path),
    )
    with pytest.raises(ValueError, match="Financial institution"):
        run_company_valuation(config, company_loader=loader, peer_loader=lambda *_args, **_kwargs: [])
