from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from valuation_system.analysis.calculations import (
    apv, asset_beta, continuing_value, deductible_interest, diluted_shares,
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
) -> tuple[list[dict], dict[str, float], list[dict]]:
    latest = company.latest
    years = assumptions.forecast_years
    growth = _ramp(assumptions.revenue_growth_start + growth_delta, assumptions.revenue_growth_terminal + terminal_growth_delta, years)
    margins = _ramp(assumptions.ebit_margin_start + margin_delta, assumptions.ebit_margin_terminal + margin_delta / 2, years)
    historical_turnover = latest.revenue / max(operating_invested_capital(latest), 1)
    target_turnover = max(0.25, historical_turnover + turnover_delta)
    turnovers = _ramp(max(0.2, historical_turnover), target_turnover, years)
    da_pct = latest.da / latest.revenue if latest.revenue else 0.08
    revenue, prior_ic, prior_owc, debt = latest.revenue, operating_invested_capital(latest), operating_working_capital(latest), latest.debt
    carryforward = 0.0
    forecast: list[dict[str, Any]] = []
    shield_rows: list[dict[str, Any]] = []
    for index in range(years):
        year = latest.year + index + 1
        revenue *= 1 + growth[index]
        ebit = revenue * margins[index]
        nopat_value = nopat(ebit, assumptions.tax_rate)
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
        new_borrowing = 0.0
        debt = max(0, debt + new_borrowing - mandatory_repayment)
        avg_debt = (opening_debt + debt) / 2
        interest = avg_debt * assumptions.interest_rate
        ati = max(0, ebit)
        deductible, used, carryforward_end = deductible_interest(
            interest, ati, carryforward, assumptions.interest_limit_percentage
        )
        shield = deductible * assumptions.cash_tax_rate
        forecast.append({
            "year": year, "revenue_growth": growth[index], "revenue": revenue,
            "cogs": revenue * (1 - max(0.05, margins[index] + 0.24)),
            "gross_profit": revenue * max(0.05, margins[index] + 0.24),
            "sga": revenue * 0.16, "rd": revenue * max(0.06, 0.15 - index * 0.007),
            "da": da, "ebit_margin": margins[index], "ebit": ebit,
            "operating_taxes": max(0, ebit * assumptions.tax_rate), "nopat": nopat_value,
            "owc": owc, "change_owc": change_owc, "net_ppe": net_ppe,
            "capex": capex, "invested_capital": invested_capital,
            "net_investment": net_investment, "fcf": fcf,
            "roic": roic(nopat_value, (prior_ic + invested_capital) / 2),
            "ronic": ronic_value, "capital_turnover": turnovers[index],
            "economic_profit": economic_profit(nopat_value, assumptions.tocc + tocc_delta, (prior_ic + invested_capital) / 2),
            "opening_debt": opening_debt, "new_borrowing": new_borrowing,
            "mandatory_repayment": mandatory_repayment, "ending_debt": debt,
            "average_debt": avg_debt, "interest_rate": assumptions.interest_rate,
            "interest_expense": interest,
        })
        shield_rows.append({
            "year": year, "ati": ati, "limit": assumptions.interest_limit_percentage * ati,
            "interest": interest, "opening_carryforward": carryforward,
            "carryforward_used": used, "deductible_interest": deductible,
            "nondeductible_current": max(0, interest - min(interest, assumptions.interest_limit_percentage * ati)),
            "ending_carryforward": carryforward_end, "cash_tax_rate": assumptions.cash_tax_rate,
            "usable_tax_shield": shield,
        })
        carryforward = carryforward_end
        prior_ic, prior_owc = invested_capital, owc
    scenario_tocc = assumptions.tocc + tocc_delta
    terminal_g = assumptions.terminal_growth_rate + terminal_growth_delta
    cv = continuing_value(forecast[-1]["nopat"], terminal_g, assumptions.terminal_ronic, scenario_tocc)
    pv_explicit = pv([row["fcf"] for row in forecast], scenario_tocc)
    pv_cv = cv / (1 + scenario_tocc) ** years
    op_value = pv_explicit + pv_cv
    pv_shields = pv([row["usable_tax_shield"] for row in shield_rows], assumptions.shield_rate)
    apv_value = apv(op_value, pv_shields)
    operating_cash = max(assumptions.minimum_cash, latest.revenue * assumptions.operating_cash_percentage)
    excess_cash = max(0, latest.cash + latest.marketable_securities - operating_cash - company.restricted_cash)
    other_claims = latest.lease_liabilities + company.pension_liability + company.preferred_stock + company.minority_interest
    equity = equity_value(apv_value, latest.debt, other_claims, excess_cash, company.non_operating_investments)
    shares = diluted_shares(
        company.basic_shares, company.rsus, company.restricted_stock, company.options,
        company.option_strike, company.share_price, company.warrants, company.convertibles,
    )
    per_share = equity / shares if shares > 0 else 0
    summary = {
        "pv_explicit_fcf": pv_explicit, "pv_continuing_value": pv_cv,
        "operating_enterprise_value": op_value, "pv_explicit_tax_shields": pv_shields,
        "pv_continuing_tax_shield": 0.0, "pv_other_financing_effects": 0.0,
        "pv_financing_effects": pv_shields, "apv_enterprise_value": apv_value,
        "gross_debt": latest.debt, "other_financing_claims": other_claims,
        "operating_cash": operating_cash, "excess_cash": excess_cash,
        "equity_value": equity, "diluted_shares": shares,
        "intrinsic_value_per_share": per_share,
        "market_price": company.share_price,
        "premium_discount": premium_discount(per_share, company.share_price),
        "continuing_value_share": pv_cv / apv_value if apv_value else None,
        "tocc": scenario_tocc, "terminal_growth": terminal_g,
        "terminal_ronic": assumptions.terminal_ronic,
        "terminal_reinvestment_rate": terminal_g / assumptions.terminal_ronic,
    }
    return forecast, summary, shield_rows


def _checks(historical: list[dict], forecast: list[dict], summary: dict, assumptions: ValuationAssumptions, company: CompanyData) -> list[CheckResult]:
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
    checks.append(CheckResult("APV", "APV equals operating value plus financing effects", "PASS" if abs(summary["apv_enterprise_value"] - summary["operating_enterprise_value"] - summary["pv_financing_effects"]) < 1e-6 else "FAIL"))
    bridge = summary["apv_enterprise_value"] - summary["gross_debt"] - summary["other_financing_claims"] + summary["excess_cash"]
    checks.append(CheckResult("APV", "Equity bridge reconciles", "PASS" if abs(bridge - summary["equity_value"]) < 1e-6 else "FAIL", bridge, summary["equity_value"], bridge-summary["equity_value"], 1e-6))
    probability = sum(s.probability for s in assumptions.scenarios.values())
    checks.append(CheckResult("Scenario", "Scenario probabilities total 100%", "PASS" if abs(probability - 1) < 1e-9 else "FAIL", probability, 1))
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
    forecast, summary, shields = _forecast(company, assumptions)
    peer_specs = [
        ("Peer A", 1.55, 80000, 12000, 0.10),
        ("Peer B", 1.20, 45000, 30000, 0.15),
        ("Peer C", 1.05, 35000, 25000, 0.12),
        ("Peer D", 1.80, 9000, 2500, 0.20),
    ]
    peers = [
        {"peer": name, "equity_beta": eb, "equity": eq, "debt": debt, "debt_beta": db,
         "tax_rate": assumptions.tax_rate, "asset_beta": asset_beta(eb, eq, db, debt),
         "weight": 0.25, "source": "Illustrative peer assumptions; replace with sourced market data"}
        for name, eb, eq, debt, db in peer_specs
    ]
    scenarios = []
    for name, scenario in assumptions.scenarios.items():
        _, scenario_summary, _ = _forecast(
            company, assumptions, scenario.revenue_growth_delta,
            scenario.ebit_margin_delta, scenario.capital_turnover_delta,
            scenario.terminal_growth_delta, scenario.tocc_delta,
        )
        scenarios.append({"scenario": name.title(), "probability": scenario.probability, **scenario_summary})
    summary["probability_weighted_value"] = scenario_weighted_value(
        [s["intrinsic_value_per_share"] for s in scenarios],
        [s["probability"] for s in scenarios],
    )
    sensitivity_rows = []
    for tocc_delta in (-0.02, -0.01, 0, 0.01, 0.02):
        for g_delta in (-0.01, -0.005, 0, 0.005, 0.01):
            try:
                _, sens, _ = _forecast(company, assumptions, terminal_growth_delta=g_delta, tocc_delta=tocc_delta)
                value = sens["intrinsic_value_per_share"]
            except ValueError:
                value = None
            sensitivity_rows.append({"tocc": assumptions.tocc + tocc_delta, "terminal_growth": assumptions.terminal_growth_rate + g_delta, "value_per_share": value})
    sensitivities = {"tocc_vs_growth": sensitivity_rows}
    checks = _checks(historical, forecast, summary, assumptions, company)
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
        ticker=company.ticker, historical=historical, forecast=forecast,
        tocc_peers=peers, tax_shield=shields, scenarios=scenarios,
        sensitivities=sensitivities, checks=checks, summary=summary,
        equity_bridge=bridge, value_drivers=drivers,
        provenance=[asdict(p) for p in company.provenance],
        assumptions=assumptions.to_dict(), company=company.to_dict(),
        diagnostics=diagnostics,
    )
