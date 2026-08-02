from __future__ import annotations

import math
from statistics import median


def nopat(ebit: float, tax_rate: float) -> float:
    return ebit * (1 - tax_rate) if ebit > 0 else ebit


def average_capital(beginning: float, ending: float) -> float:
    return (beginning + ending) / 2


def roic(nopat_value: float, avg_invested_capital: float, epsilon: float = 1e-6) -> float | None:
    if abs(avg_invested_capital) <= epsilon:
        return None
    return nopat_value / avg_invested_capital


def economic_profit(nopat_value: float, tocc: float, avg_capital: float) -> float:
    return nopat_value - tocc * avg_capital


def unlevered_fcf(
    nopat_value: float,
    depreciation: float,
    capex: float,
    change_owc: float,
    other_investment: float = 0.0,
) -> float:
    return nopat_value + depreciation - capex - change_owc - other_investment


def ronic(change_nopat: float, net_new_investment: float, epsilon: float = 1e-6) -> float | None:
    if net_new_investment <= epsilon:
        return None
    return change_nopat / net_new_investment


def continuing_value(nopat_n: float, growth: float, terminal_ronic: float, tocc: float) -> float:
    if growth >= tocc:
        raise ValueError("terminal growth must be less than TOCC")
    if terminal_ronic <= 0:
        raise ValueError("terminal RONIC must be positive")
    reinvestment_rate = growth / terminal_ronic
    if not 0 <= reinvestment_rate <= 1:
        raise ValueError("terminal reinvestment rate must be between zero and one")
    nopat_next = nopat_n * (1 + growth)
    return nopat_next * (1 - reinvestment_rate) / (tocc - growth)


def capm(risk_free_rate: float, asset_beta: float, market_risk_premium: float) -> float:
    return risk_free_rate + asset_beta * market_risk_premium


def asset_beta(equity_beta: float, equity: float, debt_beta: float, debt: float) -> float:
    if equity + debt <= 0:
        raise ValueError("peer enterprise capital must be positive")
    return (equity_beta * equity + debt_beta * debt) / (equity + debt)


def deductible_interest(
    interest: float,
    ati: float,
    carryforward: float,
    limit_percentage: float = 0.30,
) -> tuple[float, float, float]:
    capacity = max(0.0, limit_percentage * ati)
    deductible_current = min(max(interest, 0.0), capacity)
    unused_capacity = max(0.0, capacity - deductible_current)
    carry_used = min(max(carryforward, 0.0), unused_capacity)
    ending_carry = max(0.0, carryforward - carry_used) + max(0.0, interest - deductible_current)
    return deductible_current + carry_used, carry_used, ending_carry


def cash_tax_with_nol(
    taxable_income: float,
    opening_nol: float,
    tax_rate: float,
) -> tuple[float, float, float]:
    """Return cash tax, NOL used, and ending NOL for one period."""
    positive_income = max(0.0, taxable_income)
    nol_used = min(max(0.0, opening_nol), positive_income)
    cash_tax = max(0.0, positive_income - nol_used) * tax_rate
    ending_nol = max(0.0, opening_nol - nol_used) + max(0.0, -taxable_income)
    return cash_tax, nol_used, ending_nol


def pv(cash_flows: list[float], discount_rate: float) -> float:
    return sum(value / (1 + discount_rate) ** (i + 1) for i, value in enumerate(cash_flows))


def apv(operating_value: float, financing_effects: float) -> float:
    return operating_value + financing_effects


def equity_value(
    apv_enterprise_value: float,
    debt: float,
    other_claims: float,
    excess_cash: float,
    non_operating_assets: float = 0.0,
) -> float:
    return apv_enterprise_value - debt - other_claims + excess_cash + non_operating_assets


def diluted_shares(
    basic: float,
    rsus: float = 0,
    restricted: float = 0,
    options: float = 0,
    strike: float = 0,
    market_price: float | None = None,
    warrants: float = 0,
    convertibles: float = 0,
) -> float:
    option_dilution = 0.0
    if market_price and market_price > strike and market_price > 0:
        option_dilution = options * (1 - strike / market_price)
    return basic + rsus + restricted + option_dilution + warrants + convertibles


def premium_discount(intrinsic: float, market_price: float | None) -> float | None:
    if market_price is None or market_price <= 0:
        return None
    return intrinsic / market_price - 1


def scenario_weighted_value(values: list[float], probabilities: list[float]) -> float:
    if len(values) != len(probabilities):
        raise ValueError("values and probabilities must have the same length")
    if abs(sum(probabilities) - 1.0) > 1e-9:
        raise ValueError("probabilities must total 100%")
    return sum(v * p for v, p in zip(values, probabilities))


def selected_peer_beta(peers: list[dict]) -> float:
    valid = [p["asset_beta"] for p in peers if p.get("asset_beta") is not None and math.isfinite(p["asset_beta"])]
    if not valid:
        raise ValueError("no valid peer asset beta")
    return median(valid)
