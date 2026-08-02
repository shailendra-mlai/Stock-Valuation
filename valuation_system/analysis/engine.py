from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from valuation_system.analysis.calculations import (
    apv, asset_beta, cash_tax_with_nol, continuing_value, deductible_interest, diluted_shares,
    economic_profit, equity_value, nopat, premium_discount, pv, roic, ronic,
    scenario_weighted_value, unlevered_fcf,
)
from valuation_system.data.normalization import (
    financing_invested_capital, operating_invested_capital, operating_working_capital,
)
from valuation_system.models.assumptions import ValuationAssumptions
from valuation_system.models.company import CompanyData
from valuation_system.models.valuation_results import CheckResult, ValuationResult


def _ramp(start: float, end: float, count: int) -> list[float]:
    return list(np.linspace(start, end, count))


def _historical(company: CompanyData, assumptions: ValuationAssumptions) -> tuple[list[dict], list[str]]:
    output: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    history = sorted(company.historical, key=lambda y: y.year)
    prior_owc = None
    prior_ic = None
    for item in history:
        owc = operating_working_capital(item)
        ic = operating_invested_capital(item)
        fin_ic = financing_invested_capital(item)
        avg_ic = ic if prior_ic is None else (prior_ic + ic) / 2
        normalized_nopat = nopat(item.ebit, assumptions.tax_rate)
        change_owc = 0 if prior_owc is None else owc - prior_owc
        fcf = unlevered_fcf(normalized_nopat, item.da, item.capex, change_owc)
        roic_value = roic(normalized_nopat, avg_ic)
        margin = normalized_nopat / item.revenue if item.revenue else None
        turnover = item.revenue / avg_ic if abs(avg_ic) > 1e-6 else None
        output.append({
            **asdict(item),
            "gross_profit": item.revenue - item.cogs,
            "gross_margin": (item.revenue - item.cogs) / item.revenue if item.revenue else None,
            "ebit_margin": item.ebit / item.revenue if item.revenue else None,
            "nopat": normalized_nopat,
            "tax_efficiency": normalized_nopat / item.ebit if item.ebit else None,
            "nopat_margin": margin,
            "owc": owc,
            "operating_invested_capital": ic,
            "financing_invested_capital": fin_ic,
            "invested_capital_difference": ic - fin_ic,
            "average_invested_capital": avg_ic,
            "capital_turnover": turnover,
            "roic": roic_value,
            "tocc": assumptions.tocc,
            "roic_spread": None if roic_value is None else roic_value - assumptions.tocc,
            "economic_profit": economic_profit(normalized_nopat, assumptions.tocc, avg_ic),
            "fcf": fcf,
            "fcf_alt": normalized_nopat - (item.capex - item.da + change_owc),
            "receivable_days": item.receivables / item.revenue * 365 if item.revenue else None,
            "inventory_days": item.inventory / item.cogs * 365 if item.cogs else None,
            "payable_days": item.accounts_payable / item.cogs * 365 if item.cogs else None,
        })
        prior_owc, prior_ic = owc, ic
    if len(output) >= 2:
        first, last = output[0], output[-1]
        if (last["ebit_margin"] or 0) > (first["ebit_margin"] or 0):
            diagnostics.append("EBIT margin improved over the historical period, but remains a forecast hypothesis.")
        if (last["capital_turnover"] or 0) < (first["capital_turnover"] or 0):
            diagnostics.append("Capital turnover deteriorated; forecast growth must be supported by better asset utilization.")
        if last["roic"] is not None and last["roic"] < assumptions.tocc:
            diagnostics.append("Latest historical ROIC is below TOCC, indicating recent economic value destruction.")
    return output, diagnostics


def _forecast(
    company: CompanyData,
    assumptions: ValuationAssumptions,
    growth_delta: float = 0,
    margin_delta: float = 0,
    turnover_delta: float = 0,
    terminal_growth_delta: float = 0,
    tocc_delta: float = 0,
    new_borrowing: float = 0,
    equity_raise: float = 0,
    new_shares: float = 0,
    liquidation: bool = False,
    liquidation_recovery_rate: float = 0.35,
    terminal_ronic_override: float | None = None,
) -> tuple[list[dict], list[dict], dict[str, float], list[dict]]:
    latest = company.latest
    years = assumptions.forecast_years
    scenario_tocc = assumptions.tocc + tocc_delta
    growth = _ramp(assumptions.revenue_growth_start + growth_delta, assumptions.revenue_growth_terminal + terminal_growth_delta, years)
    margins = _ramp(assumptions.ebit_margin_start + margin_delta, assumptions.ebit_margin_terminal + margin_delta / 2, years)
    historical_turnover = latest.revenue / max(operating_invested_capital(latest), 1)
    target_turnover = max(0.25, historical_turnover + turnover_delta)
    turnovers = _ramp(max(0.2, historical_turnover), target_turnover, years)
    da_pct = latest.da / latest.revenue if latest.revenue else 0.08
    starting_debt = 0.0 if assumptions.debt_policy == "no_debt" else latest.debt
    revenue, prior_ic, prior_owc, debt = latest.revenue, operating_invested_capital(latest), operating_working_capital(latest), starting_debt
    carryforward = 0.0
    nol_without_interest = assumptions.initial_operating_nol
    nol_with_interest = assumptions.initial_operating_nol
    cash_balance = latest.cash + latest.marketable_securities
    forecast: list[dict[str, Any]] = []
    shield_rows: list[dict[str, Any]] = []
    for index in range(years):
        year = latest.year + index + 1
        revenue *= 1 + growth[index]
        ebit = revenue * margins[index]
        operating_taxes, nol_used_without, nol_without_end = cash_tax_with_nol(
            ebit, nol_without_interest, assumptions.tax_rate
        )
        nopat_value = ebit - operating_taxes
        invested_capital = revenue / turnovers[index]
        owc_ratio = operating_working_capital(latest) / latest.revenue if latest.revenue else 0
        owc = revenue * owc_ratio
        net_ppe = max(0, invested_capital - owc)
        da = revenue * da_pct
        capex = max(0, net_ppe - max(0, prior_ic - prior_owc) + da)
        change_owc = owc - prior_owc
        fcf = unlevered_fcf(nopat_value, da, capex, change_owc)
        net_investment = invested_capital - prior_ic
        prior_nopat = nopat(forecast[-1]["ebit"], assumptions.tax_rate) if forecast else nopat(latest.ebit, assumptions.tax_rate)
        ronic_value = ronic(nopat_value - prior_nopat, net_investment)
        opening_debt = debt
        mandatory_repayment = min(debt, debt / max(1, years - index)) if assumptions.debt_policy == "scheduled_amortization" else 0
        borrowing = new_borrowing if index == 0 else 0.0
        raise_amount = equity_raise if index == 0 else 0.0
        debt = max(0, debt + borrowing - mandatory_repayment)
        avg_debt = (opening_debt + debt) / 2
        interest = avg_debt * assumptions.interest_rate
        ati = max(0, ebit)
        deductible, used, carryforward_end = deductible_interest(
            interest, ati, carryforward, assumptions.interest_limit_percentage
        )
        tax_with_interest, nol_used_with, nol_with_end = cash_tax_with_nol(
            ebit - deductible, nol_with_interest, assumptions.tax_rate
        )
        shield = max(0.0, operating_taxes - tax_with_interest)
        opening_cash = cash_balance
        cash_balance = opening_cash + fcf + borrowing + raise_amount - mandatory_repayment - interest + shield
        forecast.append({
            "year": year, "revenue_growth": growth[index], "revenue": revenue,
            "cogs": revenue * (1 - max(0.05, margins[index] + 0.24)),
            "gross_profit": revenue * max(0.05, margins[index] + 0.24),
            "sga": revenue * 0.16, "rd": revenue * max(0.06, 0.15 - index * 0.007),
            "phase": "Explicit", "da": da, "ebit_margin": margins[index], "ebit": ebit,
            "operating_taxes": operating_taxes, "nopat": nopat_value,
            "owc": owc, "change_owc": change_owc, "net_ppe": net_ppe,
            "capex": capex, "invested_capital": invested_capital,
            "net_investment": net_investment, "fcf": fcf,
            "roic": roic(nopat_value, (prior_ic + invested_capital) / 2),
            "ronic": ronic_value, "capital_turnover": turnovers[index],
            "economic_profit": economic_profit(nopat_value, assumptions.tocc + tocc_delta, (prior_ic + invested_capital) / 2),
            "opening_debt": opening_debt, "new_borrowing": borrowing,
            "mandatory_repayment": mandatory_repayment, "ending_debt": debt,
            "average_debt": avg_debt, "interest_rate": assumptions.interest_rate,
            "interest_expense": interest,
            "opening_cash": opening_cash, "equity_raise": raise_amount,
            "ending_cash": cash_balance, "discount_factor": 1 / (1 + scenario_tocc) ** (index + 1),
            "pv_fcf": fcf / (1 + scenario_tocc) ** (index + 1),
        })
        shield_rows.append({
            "year": year, "phase": "Explicit", "ati": ati, "limit": assumptions.interest_limit_percentage * ati,
            "interest": interest, "opening_carryforward": carryforward,
            "carryforward_used": used, "deductible_interest": deductible,
            "nondeductible_current": max(0, interest - min(interest, assumptions.interest_limit_percentage * ati)),
            "ending_carryforward": carryforward_end, "cash_tax_rate": assumptions.cash_tax_rate,
            "usable_tax_shield": shield, "opening_nol_without_interest": nol_without_interest,
            "nol_used_without_interest": nol_used_without, "ending_nol_without_interest": nol_without_end,
            "opening_nol_with_interest": nol_with_interest, "nol_used_with_interest": nol_used_with,
            "ending_nol_with_interest": nol_with_end, "cash_tax_without_interest": operating_taxes,
            "cash_tax_with_interest": tax_with_interest,
        })
        carryforward = carryforward_end
        nol_without_interest, nol_with_interest = nol_without_end, nol_with_end
        prior_ic, prior_owc = invested_capital, owc
    terminal_g = assumptions.terminal_growth_rate + terminal_growth_delta
    overperformance: list[dict[str, Any]] = []
    fade_years = assumptions.competitive_advantage_years
    start_ronic = forecast[-1]["ronic"]
    if start_ronic is None or start_ronic <= scenario_tocc:
        start_ronic = scenario_tocc * 1.5
    previous_nopat = forecast[-1]["nopat"]
    previous_revenue = forecast[-1]["revenue"]
    previous_margin = forecast[-1]["ebit_margin"]
    for index in range(fade_years):
        year = latest.year + years + index + 1
        fade_ronic = start_ronic + (scenario_tocc - start_ronic) * ((index + 1) / fade_years)
        revenue = previous_revenue * (1 + terminal_g)
        ebit = revenue * previous_margin
        operating_taxes, nol_used_without, nol_without_end = cash_tax_with_nol(
            ebit, nol_without_interest, assumptions.tax_rate
        )
        nopat_value = ebit - operating_taxes
        net_investment = max(0.0, (nopat_value - previous_nopat) / max(fade_ronic, 1e-9))
        invested_capital = prior_ic + net_investment
        owc_ratio = operating_working_capital(latest) / latest.revenue if latest.revenue else 0
        owc = revenue * owc_ratio
        change_owc = owc - prior_owc
        da = revenue * da_pct
        fcf = nopat_value - net_investment
        capex = nopat_value + da - change_owc - fcf
        net_ppe = max(0.0, invested_capital - owc)
        opening_debt = debt
        mandatory_repayment = min(debt, debt / max(1, fade_years - index)) if assumptions.debt_policy == "scheduled_amortization" else 0
        debt = max(0.0, debt - mandatory_repayment)
        avg_debt = (opening_debt + debt) / 2
        interest = avg_debt * assumptions.interest_rate
        ati = max(0.0, ebit)
        deductible, used, carryforward_end = deductible_interest(
            interest, ati, carryforward, assumptions.interest_limit_percentage
        )
        tax_with_interest, nol_used_with, nol_with_end = cash_tax_with_nol(
            ebit - deductible, nol_with_interest, assumptions.tax_rate
        )
        shield = max(0.0, operating_taxes - tax_with_interest)
        opening_cash = cash_balance
        cash_balance = opening_cash + fcf - mandatory_repayment - interest + shield
        row = {
            "year": year, "phase": "Over-performance", "revenue_growth": terminal_g,
            "revenue": revenue, "cogs": revenue * (1 - max(0.05, previous_margin + 0.24)),
            "gross_profit": revenue * max(0.05, previous_margin + 0.24), "sga": revenue * 0.16,
            "rd": revenue * 0.06, "da": da, "ebit_margin": previous_margin, "ebit": ebit,
            "operating_taxes": operating_taxes, "nopat": nopat_value, "owc": owc,
            "change_owc": change_owc, "net_ppe": net_ppe, "capex": capex,
            "invested_capital": invested_capital, "net_investment": net_investment, "fcf": fcf,
            "roic": roic(nopat_value, (prior_ic + invested_capital) / 2), "ronic": fade_ronic,
            "capital_turnover": revenue / invested_capital if invested_capital else None,
            "economic_profit": economic_profit(nopat_value, scenario_tocc, (prior_ic + invested_capital) / 2),
            "opening_debt": opening_debt, "new_borrowing": 0.0, "mandatory_repayment": mandatory_repayment,
            "ending_debt": debt, "average_debt": avg_debt, "interest_rate": assumptions.interest_rate,
            "interest_expense": interest, "opening_cash": opening_cash, "equity_raise": 0.0,
            "ending_cash": cash_balance,
            "discount_factor": 1 / (1 + scenario_tocc) ** (years + index + 1),
            "pv_fcf": fcf / (1 + scenario_tocc) ** (years + index + 1),
        }
        overperformance.append(row)
        shield_rows.append({
            "year": year, "phase": "Over-performance", "ati": ati,
            "limit": assumptions.interest_limit_percentage * ati, "interest": interest,
            "opening_carryforward": carryforward, "carryforward_used": used,
            "deductible_interest": deductible,
            "nondeductible_current": max(0.0, interest - min(interest, assumptions.interest_limit_percentage * ati)),
            "ending_carryforward": carryforward_end, "cash_tax_rate": assumptions.tax_rate,
            "usable_tax_shield": shield, "opening_nol_without_interest": nol_without_interest,
            "nol_used_without_interest": nol_used_without, "ending_nol_without_interest": nol_without_end,
            "opening_nol_with_interest": nol_with_interest, "nol_used_with_interest": nol_used_with,
            "ending_nol_with_interest": nol_with_end, "cash_tax_without_interest": operating_taxes,
            "cash_tax_with_interest": tax_with_interest,
        })
        carryforward = carryforward_end
        nol_without_interest, nol_with_interest = nol_without_end, nol_with_end
        prior_ic, prior_owc = invested_capital, owc
        previous_nopat, previous_revenue = nopat_value, revenue

    terminal_ronic = terminal_ronic_override or assumptions.effective_terminal_ronic(scenario_tocc)
    final_row = overperformance[-1] if overperformance else forecast[-1]
    total_years = years + fade_years
    cv = continuing_value(final_row["nopat"], terminal_g, terminal_ronic, scenario_tocc)
    pv_explicit = pv([row["fcf"] for row in forecast], scenario_tocc)
    pv_overperformance = sum(row["fcf"] / (1 + scenario_tocc) ** (years + i + 1) for i, row in enumerate(overperformance))
    pv_terminal = cv / (1 + scenario_tocc) ** total_years
    pv_cv = pv_overperformance + pv_terminal
    op_value = pv_explicit + pv_cv
    explicit_shields = shield_rows[:years]
    continuing_shields = shield_rows[years:]
    pv_explicit_shields = pv([row["usable_tax_shield"] for row in explicit_shields], assumptions.shield_rate)
    pv_fade_shields = sum(row["usable_tax_shield"] / (1 + assumptions.shield_rate) ** (years + i + 1) for i, row in enumerate(continuing_shields))
    terminal_interest = final_row["ending_debt"] * assumptions.interest_rate
    terminal_deductible = min(terminal_interest, assumptions.interest_limit_percentage * max(0.0, final_row["ebit"] * (1 + terminal_g)))
    terminal_shield_cash = terminal_deductible * assumptions.tax_rate if nol_with_interest <= 0 else 0.0
    terminal_shield_value = 0.0 if terminal_shield_cash <= 0 else terminal_shield_cash / (assumptions.shield_rate - terminal_g) / (1 + assumptions.shield_rate) ** total_years
    pv_continuing_shield = pv_fade_shields + terminal_shield_value
    pv_shields = pv_explicit_shields + pv_continuing_shield
    apv_value = apv(op_value, pv_shields)
    operating_cash = max(assumptions.minimum_cash, latest.revenue * assumptions.operating_cash_percentage)
    excess_cash = max(0, latest.cash + latest.marketable_securities - operating_cash - company.restricted_cash)
    other_claims = latest.lease_liabilities + company.pension_liability + company.preferred_stock + company.minority_interest
    equity = equity_value(apv_value, latest.debt, other_claims, excess_cash, company.non_operating_investments)
    shares = diluted_shares(
        company.basic_shares, company.rsus, company.restricted_stock, company.options,
        company.option_strike, company.share_price, company.warrants, company.convertibles,
    ) * (1 + assumptions.annual_sbc_dilution_rate) ** years + new_shares
    if liquidation:
        liquidation_assets = max(0.0, liquidation_recovery_rate * final_row["invested_capital"] + latest.cash + latest.marketable_securities)
        equity = max(0.0, liquidation_assets - latest.debt - other_claims)
        apv_value = liquidation_assets
        op_value = liquidation_recovery_rate * final_row["invested_capital"]
    equity = max(0.0, equity)
    per_share = equity / shares if shares > 0 else 0
    summary = {
        "pv_explicit_fcf": pv_explicit, "pv_continuing_value": pv_cv,
        "pv_overperformance_fcf": pv_overperformance, "pv_terminal_value": pv_terminal,
        "operating_enterprise_value": op_value,
        "pv_explicit_tax_shields": pv_explicit_shields,
        "pv_continuing_tax_shield": pv_continuing_shield, "pv_other_financing_effects": 0.0,
        "pv_financing_effects": pv_shields, "apv_enterprise_value": apv_value,
        "gross_debt": latest.debt, "other_financing_claims": other_claims,
        "operating_cash": operating_cash, "excess_cash": excess_cash,
        "equity_value": equity, "diluted_shares": shares,
        "intrinsic_value_per_share": per_share,
        "market_price": company.share_price,
        "premium_discount": premium_discount(per_share, company.share_price),
        "continuing_value_share": pv_cv / apv_value if apv_value else None,
        "tocc": scenario_tocc, "terminal_growth": terminal_g,
        "terminal_ronic": terminal_ronic,
        "terminal_reinvestment_rate": terminal_g / terminal_ronic,
        "terminal_nopat": final_row["nopat"],
        "terminal_nopat_next": final_row["nopat"] * (1 + terminal_g),
        "terminal_fcf": final_row["nopat"] * (1 + terminal_g) * (1 - terminal_g / terminal_ronic),
        "continuing_value_at_terminal": cv,
        "minimum_cash_balance": min([latest.cash + latest.marketable_securities] + [r["ending_cash"] for r in forecast + overperformance]),
        "liquidity_shortfall": max(0.0, assumptions.minimum_cash - min([latest.cash + latest.marketable_securities] + [r["ending_cash"] for r in forecast + overperformance])),
        "liquidation": liquidation,
    }
    return forecast, overperformance, summary, shield_rows


def _checks(historical: list[dict], forecast: list[dict], overperformance: list[dict], summary: dict, assumptions: ValuationAssumptions, company: CompanyData) -> list[CheckResult]:
    checks: list[CheckResult] = []
    years = [r["year"] for r in historical]
    checks.append(CheckResult("Data", "Historical periods sequential", "PASS" if years == list(range(min(years), max(years) + 1)) else "FAIL", years, "Sequential"))
    max_fcf_diff = max(abs(r["fcf"] - r["fcf_alt"]) for r in historical)
    checks.append(CheckResult("Operating", "Historical FCF reconciliation", "PASS" if max_fcf_diff < 1e-6 else "FAIL", max_fcf_diff, 0, max_fcf_diff, 1e-6))
    max_roic_diff = max(abs((r["nopat_margin"] or 0) * (r["capital_turnover"] or 0) - (r["roic"] or 0)) for r in historical)
    checks.append(CheckResult("Operating", "ROIC tree reconciliation", "PASS" if max_roic_diff < 1e-6 else "FAIL", max_roic_diff, 0, max_roic_diff, 1e-6))
    ic_diff = abs(historical[-1]["invested_capital_difference"])
    checks.append(CheckResult("Accounting", "Invested capital reconciliation", "WARNING" if ic_diff > 1 else "PASS", ic_diff, 0, ic_diff, 1, "Classification differences are surfaced, not plugged."))
    checks.append(CheckResult("Continuing value", "Terminal g < TOCC", "PASS" if summary["terminal_growth"] < summary["tocc"] else "FAIL", summary["terminal_growth"], summary["tocc"]))
    checks.append(CheckResult("Continuing value", "Terminal reinvestment rate valid", "PASS" if 0 <= summary["terminal_reinvestment_rate"] <= 1 else "FAIL", summary["terminal_reinvestment_rate"], "0% to 100%"))
    checks.append(CheckResult("Continuing value", "Terminal RONIC equals TOCC", "PASS" if abs(summary["terminal_ronic"] - summary["tocc"]) < 1e-9 else "WARNING", summary["terminal_ronic"], summary["tocc"], summary["terminal_ronic"] - summary["tocc"], 1e-9, "True steady state assumes no excess return on new investment."))
    if overperformance:
        checks.append(CheckResult("Continuing value", "Competitive-advantage fade reaches TOCC", "PASS" if abs(overperformance[-1]["ronic"] - summary["tocc"]) < 1e-9 else "FAIL", overperformance[-1]["ronic"], summary["tocc"], overperformance[-1]["ronic"] - summary["tocc"], 1e-9))
    checks.append(CheckResult("APV", "APV equals operating value plus financing effects", "PASS" if abs(summary["apv_enterprise_value"] - summary["operating_enterprise_value"] - summary["pv_financing_effects"]) < 1e-6 else "FAIL"))
    bridge = summary["apv_enterprise_value"] - summary["gross_debt"] - summary["other_financing_claims"] + summary["excess_cash"]
    checks.append(CheckResult("APV", "Equity bridge reconciles", "PASS" if abs(bridge - summary["equity_value"]) < 1e-6 else "FAIL", bridge, summary["equity_value"], bridge-summary["equity_value"], 1e-6))
    probability = sum(s.probability for s in assumptions.scenarios.values())
    checks.append(CheckResult("Scenario", "Scenario probabilities total 100%", "PASS" if abs(probability - 1) < 1e-9 else "FAIL", probability, 1))
    liquidity_status = "PASS" if summary["liquidity_shortfall"] <= 0 else "FAIL"
    checks.append(CheckResult("Liquidity", "Minimum cash maintained", liquidity_status, summary["minimum_cash_balance"], f">= {assumptions.minimum_cash:,.0f}", summary["liquidity_shortfall"], 0, "A failure identifies a financing need; it is not silently plugged."))
    checks.append(CheckResult("Market", "Market price available", "PASS" if company.share_price and company.share_price > 0 else "WARNING", company.share_price, "> 0", notes="Provide an override when missing."))
    checks.append(CheckResult("Risk", "Continuing value concentration", "WARNING" if (summary["continuing_value_share"] or 0) > 0.8 else "PASS", summary["continuing_value_share"], "<= 80%", notes="High terminal-value dependence increases model risk."))
    if company.is_financial and not assumptions.allow_financial_company:
        checks.append(CheckResult("Sector", "Nonfinancial company framework", "FAIL", company.sector, "Nonfinancial", notes="Use a financial-institution-specific framework or explicit override."))
    return checks


def run_valuation(company: CompanyData, assumptions: ValuationAssumptions) -> ValuationResult:
    assumptions.validate()
    if company.is_financial and not assumptions.allow_financial_company:
        raise ValueError("Financial institution detected; explicit override and a sector-specific framework are required.")
    historical, diagnostics = _historical(company, assumptions)
    forecast, overperformance, summary, shields = _forecast(company, assumptions)
    peer_specs = [
        ("Peer A", 1.55, 80000, 12000, 0.10),
        ("Peer B", 1.20, 45000, 30000, 0.15),
        ("Peer C", 1.05, 35000, 25000, 0.12),
        ("Peer D", 1.80, 9000, 2500, 0.20),
    ]
    peer_names = (assumptions.peer_tickers + ["Peer A", "Peer B", "Peer C", "Peer D"])[:4]
    peers = [
        {"peer": peer_names[index], "equity_beta": eb, "equity": eq, "debt": debt, "debt_beta": db,
         "tax_rate": assumptions.tax_rate, "raw_asset_beta": asset_beta(eb, eq, db, debt),
         "adjusted_asset_beta": 0.67 * asset_beta(eb, eq, db, debt) + 0.33,
         "asset_beta": asset_beta(eb, eq, db, debt),
         "weight": 0.25, "source": "Illustrative peer assumptions; replace with sourced market data"}
        for index, (_, eb, eq, debt, db) in enumerate(peer_specs)
    ]
    scenarios = []
    for name, scenario in assumptions.scenarios.items():
        _, _, scenario_summary, _ = _forecast(
            company, assumptions, scenario.revenue_growth_delta,
            scenario.ebit_margin_delta, scenario.capital_turnover_delta,
            scenario.terminal_growth_delta, scenario.tocc_delta,
            scenario.new_borrowing, scenario.equity_raise, scenario.new_shares,
            scenario.liquidation, scenario.liquidation_recovery_rate,
        )
        scenarios.append({
            "scenario": name.title(), "probability": scenario.probability,
            "revenue_growth_delta": scenario.revenue_growth_delta,
            "ebit_margin_delta": scenario.ebit_margin_delta,
            "capital_turnover_delta": scenario.capital_turnover_delta,
            "terminal_growth_delta": scenario.terminal_growth_delta,
            "tocc_delta": scenario.tocc_delta,
            "new_borrowing": scenario.new_borrowing,
            "equity_raise": scenario.equity_raise,
            "new_shares": scenario.new_shares,
            "liquidation_recovery_rate": scenario.liquidation_recovery_rate,
            **scenario_summary,
        })
    summary["probability_weighted_value"] = scenario_weighted_value(
        [s["intrinsic_value_per_share"] for s in scenarios],
        [s["probability"] for s in scenarios],
    )
    sensitivity_rows = []
    for tocc_delta in (-0.02, -0.01, 0, 0.01, 0.02):
        for g_delta in (-0.01, -0.005, 0, 0.005, 0.01):
            try:
                _, _, sens, _ = _forecast(company, assumptions, terminal_growth_delta=g_delta, tocc_delta=tocc_delta)
                value = sens["intrinsic_value_per_share"]
            except ValueError:
                value = None
            sensitivity_rows.append({"tocc": assumptions.tocc + tocc_delta, "terminal_growth": assumptions.terminal_growth_rate + g_delta, "value_per_share": value})
    ronic_rows = []
    for tocc_delta in (-0.02, -0.01, 0, 0.01, 0.02):
        scenario_tocc = assumptions.tocc + tocc_delta
        for ronic_delta in (-0.02, -0.01, 0, 0.01, 0.02):
            terminal_ronic = max(assumptions.terminal_growth_rate + 0.001, scenario_tocc + ronic_delta)
            try:
                _, _, sens, _ = _forecast(
                    company, assumptions, tocc_delta=tocc_delta,
                    terminal_ronic_override=terminal_ronic,
                )
                value = sens["intrinsic_value_per_share"]
            except ValueError:
                value = None
            ronic_rows.append({"tocc": scenario_tocc, "terminal_ronic": terminal_ronic, "value_per_share": value})
    sensitivities = {"tocc_vs_growth": sensitivity_rows, "tocc_vs_ronic": ronic_rows}
    checks = _checks(historical, forecast, overperformance, summary, assumptions, company)
    failures = sum(c.status == "FAIL" for c in checks)
    warnings = sum(c.status == "WARNING" for c in checks)
    summary["overall_model_status"] = "FAIL" if failures else ("WARNING" if warnings else "PASS")
    latest = company.latest
    bridge = [
        {"item": "APV enterprise value", "value": summary["apv_enterprise_value"]},
        {"item": "Less: gross debt", "value": -latest.debt},
        {"item": "Less: other financing claims", "value": -summary["other_financing_claims"]},
        {"item": "Add: excess cash and marketable investments", "value": summary["excess_cash"]},
        {"item": "Add: non-operating investments", "value": company.non_operating_investments},
        {"item": "Equity value", "value": summary["equity_value"]},
    ]
    drivers = [
        {"variable": "Revenue growth", "historical_evidence": f"Latest revenue ${latest.revenue:,.0f}mm", "management_evidence": "User/filing review required", "industry_evidence": "Peer demand and capacity", "comparable_evidence": "Peer growth dispersion", "base": assumptions.revenue_growth_start, "downside": assumptions.revenue_growth_start-0.05, "upside": assumptions.revenue_growth_start+0.05, "falsifier": "Orders, deliveries, or backlog fail to support growth"},
        {"variable": "EBIT margin", "historical_evidence": f"Latest EBIT margin {latest.ebit/latest.revenue:.1%}", "management_evidence": "Cost-reduction and scale milestones", "industry_evidence": "Mature peer margins", "comparable_evidence": "Peer margin range", "base": assumptions.ebit_margin_terminal, "downside": assumptions.ebit_margin_terminal-0.04, "upside": assumptions.ebit_margin_terminal+0.04, "falsifier": "Gross margin and fixed-cost absorption miss milestones"},
        {"variable": "Capital turnover", "historical_evidence": f"Latest turnover {latest.revenue/max(1, operating_invested_capital(latest)):.2f}x", "management_evidence": "Capacity utilization", "industry_evidence": "Asset intensity", "comparable_evidence": "Peer turnover range", "base": forecast[-1]["capital_turnover"], "downside": max(0.1, forecast[-1]["capital_turnover"]-0.2), "upside": forecast[-1]["capital_turnover"]+0.2, "falsifier": "Capacity requires more capital than planned"},
    ]
    return ValuationResult(
        ticker=company.ticker, historical=historical, forecast=forecast, overperformance=overperformance,
        tocc_peers=peers, tax_shield=shields, scenarios=scenarios,
        sensitivities=sensitivities, checks=checks, summary=summary,
        equity_bridge=bridge, value_drivers=drivers,
        provenance=[asdict(p) for p in company.provenance],
        assumptions=assumptions.to_dict(), company=company.to_dict(),
        diagnostics=diagnostics,
    )
