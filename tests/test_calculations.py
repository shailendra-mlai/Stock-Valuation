import math

import pytest

from valuation_system.analysis.calculations import (
    apv, asset_beta, capm, cash_tax_with_nol, continuing_value, deductible_interest,
    diluted_shares, economic_profit, equity_value, nopat, premium_discount,
    roic, ronic, scenario_weighted_value, unlevered_fcf,
)
from valuation_system.analysis.engine import run_valuation
from valuation_system.data.company_data import load_company_data
from valuation_system.data.normalization import operating_invested_capital, operating_working_capital
from valuation_system.models.assumptions import ValuationAssumptions


def test_nopat_positive_and_negative():
    assert nopat(100, 0.21) == pytest.approx(79)
    assert nopat(-100, 0.21) == -100


def test_operating_working_capital():
    y = load_company_data("RIVN").latest
    expected = y.receivables + y.inventory + y.other_current_operating_assets - y.accounts_payable - y.accrued_operating_liabilities - y.deferred_revenue - y.other_operating_liabilities
    assert operating_working_capital(y) == expected


def test_invested_capital():
    y = load_company_data("RIVN").latest
    assert operating_invested_capital(y) == operating_working_capital(y) + y.net_ppe + y.operating_lease_assets + y.other_operating_assets


def test_roic_and_tree():
    value = roic(80, 400)
    assert value == pytest.approx(0.2)
    assert value == pytest.approx((80 / 200) * (200 / 400))
    assert roic(10, 0) is None


def test_economic_profit():
    assert economic_profit(80, 0.1, 400) == 40


def test_fcf_reconciliation():
    value = unlevered_fcf(100, 20, 35, 5)
    assert value == 80
    assert value == 100 - (35 - 20 + 5)


def test_ronic_edge_cases():
    assert ronic(10, 50) == pytest.approx(0.2)
    assert ronic(10, 0) is None
    assert ronic(10, -5) is None


def test_continuing_value():
    assert continuing_value(100, 0.02, 0.10, 0.08) == pytest.approx(1360)
    with pytest.raises(ValueError):
        continuing_value(100, 0.08, 0.1, 0.08)
    with pytest.raises(ValueError):
        continuing_value(100, 0.02, 0, 0.08)
    with pytest.raises(ValueError):
        continuing_value(100, 0.05, 0.04, 0.08)


def test_capm_and_asset_beta():
    assert capm(0.04, 1.2, 0.05) == pytest.approx(0.10)
    assert asset_beta(1.2, 80, 0.2, 20) == pytest.approx(1.0)


def test_interest_limit_and_carryforward():
    deductible, used, ending = deductible_interest(100, 200, 20, 0.30)
    assert deductible == 60
    assert used == 0
    assert ending == 60
    deductible2, used2, ending2 = deductible_interest(10, 200, 50, 0.30)
    assert deductible2 == 60
    assert used2 == 50
    assert ending2 == 0


def test_parallel_nol_cash_tax_schedule():
    tax, used, ending = cash_tax_with_nol(100, 60, 0.21)
    assert tax == pytest.approx(8.4)
    assert used == 60
    assert ending == 0
    loss_tax, loss_used, loss_ending = cash_tax_with_nol(-25, ending, 0.21)
    assert loss_tax == 0
    assert loss_used == 0
    assert loss_ending == 25


def test_apv_and_equity_bridge():
    assert apv(1000, 50) == 1050
    assert equity_value(1050, 200, 25, 100, 10) == 935


def test_diluted_shares():
    assert diluted_shares(100, rsus=5, options=10, strike=10, market_price=20) == pytest.approx(110)
    assert diluted_shares(100, options=10, strike=25, market_price=20) == 100


def test_premium_discount():
    assert premium_discount(120, 100) == pytest.approx(0.2)
    assert premium_discount(120, None) is None


def test_scenario_weighting():
    assert scenario_weighted_value([80, 100, 140], [0.25, 0.5, 0.25]) == 105
    with pytest.raises(ValueError):
        scenario_weighted_value([80, 100], [0.4, 0.5])


def test_integration_mock_company():
    company = load_company_data("RIVN")
    assumptions = ValuationAssumptions()
    result = run_valuation(company, assumptions)
    assert len(result.historical) == 6
    assert len(result.forecast) == 10
    assert len(result.overperformance) == 10
    assert len(result.tax_shield) == 20
    assert result.summary["terminal_growth"] < result.summary["tocc"]
    assert result.summary["terminal_ronic"] == pytest.approx(result.summary["tocc"])
    assert result.overperformance[-1]["ronic"] == pytest.approx(result.summary["tocc"])
    assert result.summary["pv_continuing_value"] == pytest.approx(
        result.summary["pv_overperformance_fcf"] + result.summary["pv_terminal_value"]
    )
    assert result.summary["overall_model_status"] in {"PASS", "WARNING", "FAIL"}
    assert math.isfinite(result.summary["intrinsic_value_per_share"])
    assert abs(sum(s["probability"] for s in result.scenarios) - 1) < 1e-9
    assert abs(result.summary["apv_enterprise_value"] - result.summary["operating_enterprise_value"] - result.summary["pv_financing_effects"]) < 1e-6
    assert all(s["equity_value"] >= 0 for s in result.scenarios)


def test_scenario_specific_dilution_and_liquidation_floor():
    company = load_company_data("RIVN")
    assumptions = ValuationAssumptions()
    assumptions.scenarios["failure"].new_shares = 100
    result = run_valuation(company, assumptions)
    failure = next(row for row in result.scenarios if row["scenario"] == "Failure")
    base = next(row for row in result.scenarios if row["scenario"] == "Base")
    assert failure["liquidation"] is True
    assert failure["diluted_shares"] == pytest.approx(base["diluted_shares"] + 100)
    assert failure["intrinsic_value_per_share"] >= 0


def test_financial_company_rejected():
    company = load_company_data("RIVN")
    company.sector = "Banking"
    with pytest.raises(ValueError):
        run_valuation(company, ValuationAssumptions())
