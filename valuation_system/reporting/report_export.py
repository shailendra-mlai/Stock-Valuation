from __future__ import annotations

from pathlib import Path

from valuation_system.models.valuation_results import ValuationResult


def _money(value: float | None) -> str:
    return "n.m." if value is None else f"${value:,.1f}"


def _pct(value: float | None) -> str:
    return "n.m." if value is None else f"{value:.1%}"


def export_report(result: ValuationResult, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = result.summary
    c = result.company
    scenario_lines = "\n".join(
        f"- {row['scenario']}: {_money(row['intrinsic_value_per_share'])}/share "
        f"at {row['probability']:.0%} probability."
        for row in result.scenarios
    )
    diagnostics = "\n".join(f"- {item}" for item in result.diagnostics) or "- No automated diagnostic observations."
    sources = "\n".join(
        f"- {row['variable']}: {row['source']} ({row['source_date']}); "
        f"confidence {row['confidence']}."
        for row in result.provenance
    )
    failed = [check for check in result.checks if check.status != "PASS"]
    check_notes = "\n".join(f"- {c.status}: {c.name}. {c.notes}" for c in failed) or "- All checks passed."
    text = f"""# {result.ticker} Intrinsic Valuation Report

## 1. Executive summary

The APV framework produces an intrinsic value of **{_money(s['intrinsic_value_per_share'])} per share** and a probability-weighted value of **{_money(s['probability_weighted_value'])}**. The illustrative market-price comparison is {_pct(s['premium_discount'])}. Overall model status: **{s['overall_model_status']}**.

This result is a structured hypothesis, not a price target. The offline sample financials, market price, peer betas, and forecast drivers must be refreshed from current filings and market sources before investment use.

## 2. Purpose and valuation date

The model values {c['name']} as of {result.assumptions['valuation_date']} in {c['currency']} millions, separating operating value from financing effects.

## 3. Business description

Sector classification: {c['sector']}. The default framework is designed for nonfinancial operating companies.

## 4. Historical financial diagnosis

{diagnostics}

## 5. ROIC-tree analysis

ROIC is calculated as NOPAT divided by average operating invested capital and reconciled to NOPAT margin multiplied by capital turnover. Economic profit deducts TOCC times average invested capital from NOPAT.

## 6. Sustainable competitive advantage

The model does not assume that historical returns persist. Durable terminal returns require evidence of customer demand, pricing power, scale economies, technology advantage, working-capital structure, or superior capital efficiency.

## 7. Forecast story and value drivers

Revenue growth, EBIT margin, and capital turnover are explicit drivers. Each includes downside, base, upside, and falsification hypotheses in the workbook.

## 8. Explicit forecast

The forecast spans {len(result.forecast)} years. Free cash flow equals NOPAT plus D&A less capex and change in operating working capital. Capex is derived from the PP&E requirement rather than set equal to depreciation.

## 9. Continuing value

Continuing value uses normalized NOPAT, terminal growth of {_pct(s['terminal_growth'])}, terminal RONIC of {_pct(s['terminal_ronic'])}, and TOCC of {_pct(s['tocc'])}. The implied reinvestment rate is {_pct(s['terminal_reinvestment_rate'])}; continuing value is {_pct(s['continuing_value_share'])} of APV enterprise value.

## 10. TOCC estimation

TOCC is {_pct(s['tocc'])}, using CAPM with an operating asset beta rather than the company’s borrowing cost. Workbook peer data are clearly identified as illustrative assumptions pending source refresh.

## 11. Financing policy and tax shields

Interest tax shields are modeled separately with an EBIT-like ATI convention and a 30% deductibility limit. Carryforwards are rolled explicitly. No continuing tax shield is capitalized in the sample because the long-run debt and deductibility hypothesis is not sufficiently supported.

## 12. APV valuation

- PV of explicit unlevered FCF: {_money(s['pv_explicit_fcf'])} million
- PV of continuing value: {_money(s['pv_continuing_value'])} million
- Operating enterprise value: {_money(s['operating_enterprise_value'])} million
- PV of financing effects: {_money(s['pv_financing_effects'])} million
- APV enterprise value: {_money(s['apv_enterprise_value'])} million

## 13. Equity bridge

APV enterprise value is adjusted for gross debt, other financing claims, excess cash, and non-operating assets. Equity value is {_money(s['equity_value'])} million across {s['diluted_shares']:,.1f} million diluted shares.

## 14. Market-price comparison

Illustrative market price: {_money(s['market_price'])}. Intrinsic value differs by {_pct(s['premium_discount'])}. This comparison is meaningful only after the market price and share count are refreshed to compatible dates.

## 15. Scenario and sensitivity analysis

{scenario_lines}

The workbook includes a formula-driven TOCC-versus-terminal-growth sensitivity grid.

## 16. Principal risks

- Forecast revenue and margin convergence may not occur.
- Capital requirements may exceed the modeled PP&E and working-capital needs.
- Terminal RONIC may not remain above TOCC.
- Tax shields may be delayed or unusable.
- Dilution and financing claims may be incomplete without security-level disclosures.

## 17. Model limitations

{check_notes}

Live data retrieval intentionally refuses low-confidence automatic XBRL mappings. Missing or ambiguous classifications must be reviewed or overridden; the system does not silently substitute zero for required live inputs.

## 18. Data sources

{sources}
"""
    path.write_text(text)
    return path
