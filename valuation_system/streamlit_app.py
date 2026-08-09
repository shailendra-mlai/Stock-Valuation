from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from valuation_system.ui.charts import (
    combined_chart, historical_chart, roic_ronic_chart, scenario_chart,
    sensitivity_heatmap, valuation_waterfall,
)
from valuation_system.ui.components import (
    DEBT_POLICIES, build_valuation_config, flatten_uploaded_assumptions,
    parse_assumptions_upload, render_downloads, render_metric_cards,
    render_overall_status, run_company_valuation, valuation_bridge_rows,
)
from valuation_system.ui.formatting import (
    format_currency, format_large_currency, format_percentage,
)
from valuation_system.ui.session_state import clear_results, initialize_session_state, store_artifacts
from valuation_system.models.assumptions import ScenarioAssumption, ValuationAssumptions


logger = logging.getLogger(__name__)


def _display_value(value):
    if value is None:
        return "—"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str, sort_keys=True)
    return str(value)


def _default(uploaded: dict, key: str, fallback):
    value = uploaded.get(key)
    return fallback if value is None else value


def _persist_historical_upload(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    target_dir = Path("valuation_system/output/uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix.lower()
    target = target_dir / uploaded_file.name
    if suffix == ".csv":
        target.write_bytes(uploaded_file.getvalue())
        return str(target)
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(uploaded_file)
        csv_target = target.with_suffix(".csv")
        frame.to_csv(csv_target, index=False)
        return str(csv_target)
    raise ValueError("Historical data must be uploaded as CSV or Excel.")


def _format_frame(frame: pd.DataFrame, percent_columns: list[str] | None = None, money_columns: list[str] | None = None):
    percent_columns = [column for column in (percent_columns or []) if column in frame]
    money_columns = [column for column in (money_columns or []) if column in frame]
    formats = {column: "{:.1%}" for column in percent_columns}
    formats.update({column: "{:,.1f}" for column in money_columns})
    return frame.style.format(formats, na_rep="—")


def _scenario_editor(uploaded_defaults: dict) -> dict[str, dict]:
    uploaded = uploaded_defaults.get("scenarios")
    canonical = ValuationAssumptions().scenarios
    rows = []
    for name, raw in canonical.items():
        uploaded_raw = (uploaded or {}).get(name, {})
        if isinstance(uploaded_raw, ScenarioAssumption):
            probability = uploaded_raw.probability
        else:
            probability = uploaded_raw.get("probability", raw.probability)
        rows.append({
            "Scenario": str(name).title(),
            "Probability (%)": float(probability) * 100,
        })
    with st.sidebar.expander("Scenarios and Probabilities", expanded=True):
        st.caption("The four valuation scenarios are fixed. Change only their probabilities; each defaults to 25% and the total must equal 100%.")
        edited = st.data_editor(
            pd.DataFrame(rows), num_rows="fixed", hide_index=True,
            use_container_width=True, key="scenario_editor",
            column_config={
                "Scenario": st.column_config.TextColumn(disabled=True),
                "Probability (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=5.0, format="%.1f"),
            },
        )
        total = float(pd.to_numeric(edited.get("Probability (%)"), errors="coerce").fillna(0).sum())
        if abs(total - 100) < 1e-8:
            st.success("Probability total: 100.0%")
        else:
            st.error(f"Probability total: {total:.1f}% — adjust to 100.0% before running.")
    scenarios: dict[str, dict] = {}
    for row in edited.to_dict("records"):
        name = str(row.get("Scenario") or "").lower().strip()
        values = asdict(canonical[name])
        values["probability"] = float(row.get("Probability (%)") or 0) / 100
        scenarios[name] = values
    return scenarios


def _sidebar_inputs() -> tuple[bool, dict]:
    st.sidebar.header("Valuation Inputs")
    uploaded_assumptions = st.sidebar.file_uploader("Upload Parameter File", type=["yaml", "yml", "json"])
    example_assumptions = Path(__file__).resolve().parents[1] / "assumptions_example.yaml"
    st.sidebar.download_button(
        "Download Example Parameter File",
        data=example_assumptions.read_bytes(),
        file_name="aapl_assumptions_example.yaml",
        mime="application/x-yaml",
        help="Download, edit, and upload this AAPL template to populate the app inputs.",
        use_container_width=True,
    )
    uploaded_defaults: dict = {}
    if uploaded_assumptions:
        try:
            raw = parse_assumptions_upload(uploaded_assumptions.getvalue(), uploaded_assumptions.name)
            uploaded_defaults = {k: v for k, v in flatten_uploaded_assumptions(raw).items() if v is not None}
            st.sidebar.success("Loaded: " + ", ".join(sorted(uploaded_defaults)))
        except Exception as exc:
            st.sidebar.error(f"Could not read assumptions: {exc}")

    ticker = st.sidebar.text_input("Ticker", value=str(_default(uploaded_defaults, "ticker", "AAPL"))).upper().strip()
    peers_default = uploaded_defaults.get("peer_tickers") or []
    peers = st.sidebar.text_input(
        "Comparable Companies (optional override)",
        value=", ".join(peers_default),
        placeholder="Example: TSLA, GM, F",
        help="Enter comma-separated ticker symbols. When blank, Yahoo Finance selects the comparables automatically.",
    )
    st.sidebar.caption("Supplied comparables are used as entered and equal-weighted; leave blank for automatic Yahoo Finance selection.")
    valuation_default = pd.to_datetime(_default(uploaded_defaults, "valuation_date", date.today())).date()
    valuation_date = st.sidebar.date_input("Valuation Date", value=valuation_default)
    forecast_years = st.sidebar.slider("Explicit Forecast Period", 5, 15, int(_default(uploaded_defaults, "forecast_years", 10)))
    competitive_years = st.sidebar.slider("Competitive-Advantage Fade", 0, 20, int(_default(uploaded_defaults, "competitive_advantage_years", 10)))
    currencies = ["USD", "EUR", "GBP", "JPY", "CAD"]
    currency_default = str(_default(uploaded_defaults, "currency", "USD"))
    currency = st.sidebar.selectbox("Reporting Currency", currencies, index=currencies.index(currency_default) if currency_default in currencies else 0)

    with st.sidebar.expander("Forecast Assumptions", expanded=True):
        estimate_growth = st.checkbox("Estimate base revenue growth automatically", value=uploaded_defaults.get("revenue_growth_start") is None)
        revenue_growth = None if estimate_growth else st.number_input("Base Revenue Growth", -0.50, 1.00, float(_default(uploaded_defaults, "revenue_growth_start", 0.10)), 0.01, format="%.3f")
        terminal_growth = st.number_input("Terminal Growth Rate", -0.05, 0.10, float(_default(uploaded_defaults, "terminal_growth_rate", 0.025)), 0.005, format="%.3f")
        enforce_terminal = st.checkbox("Enforce terminal RONIC = TOCC", value=bool(_default(uploaded_defaults, "enforce_terminal_ronic_to_tocc", True)))
        terminal_ronic = None if enforce_terminal else st.number_input("Terminal RONIC", 0.01, 0.50, float(_default(uploaded_defaults, "terminal_ronic", 0.10)), 0.01, format="%.3f")
        estimate_margin = st.checkbox("Estimate normalized EBIT margin automatically", value=uploaded_defaults.get("ebit_margin_terminal") is None)
        terminal_margin = None if estimate_margin else st.number_input("Normalized EBIT Margin", -0.50, 0.60, float(_default(uploaded_defaults, "ebit_margin_terminal", 0.10)), 0.01, format="%.3f")
        tax_rate = st.number_input("Normalized Operating Tax Rate", 0.0, 0.50, float(_default(uploaded_defaults, "tax_rate", 0.21)), 0.01, format="%.3f")

    with st.sidebar.expander("TOCC Assumptions"):
        auto_risk_free = st.checkbox("Estimate risk-free rate automatically", value=uploaded_defaults.get("risk_free_rate") is None)
        risk_free = None if auto_risk_free else st.number_input("Risk-free Rate", 0.0, 0.20, float(_default(uploaded_defaults, "risk_free_rate", 0.0445)), 0.0025, format="%.4f")
        market_premium = st.number_input("Market Risk Premium", 0.0, 0.20, float(_default(uploaded_defaults, "market_risk_premium", 0.0418)), 0.0025, format="%.4f")
        debt_beta = st.number_input("Debt Beta", 0.0, 1.0, 0.15, 0.05)
        st.caption("The adjusted asset beta from the selected peer set is used in TOCC.")

    with st.sidebar.expander("Financing and APV"):
        uploaded_policy = uploaded_defaults.get("debt_policy", "scheduled_amortization")
        labels = list(DEBT_POLICIES)
        default_label = next((label for label, value in DEBT_POLICIES.items() if value == uploaded_policy), "Scheduled amortization")
        debt_label = st.selectbox("Debt Policy", labels, index=labels.index(default_label))
        cash_tax_rate = st.number_input("Cash Tax Rate", 0.0, 0.50, float(_default(uploaded_defaults, "cash_tax_rate", 0.21)), 0.01, format="%.3f")
        interest_limit = st.number_input("Interest Deduction Limitation (% ATI)", 0.0, 1.0, float(_default(uploaded_defaults, "interest_limit_percentage", 0.30)), 0.05, format="%.2f")
        auto_shield_rate = st.checkbox("Use TOCC for tax-shield discount rate", value=True)
        shield_rate = None if auto_shield_rate else st.number_input("Tax-Shield Discount Rate", 0.0, 0.30, 0.09, 0.005, format="%.3f")
        minimum_cash = st.number_input("Minimum Operating Cash ($mm)", 0.0, value=float(_default(uploaded_defaults, "minimum_cash", 500.0)), step=100.0)

    scenarios = _scenario_editor(uploaded_defaults)

    historical_upload = st.sidebar.file_uploader("Upload Historical Financial Data", type=["csv", "xlsx", "xls"])
    configured_sec_agent = os.getenv("SEC_USER_AGENT", "").strip()
    sec_user_agent = configured_sec_agent or None
    if historical_upload is None:
        if configured_sec_agent:
            st.sidebar.caption("SEC Company Facts download is configured for this deployment.")
        else:
            sec_email = st.sidebar.text_input(
                "SEC Request Contact Email",
                help="SEC requires automated requests to identify the application and a contact email. The address is sent only in the SEC request header.",
            ).strip()
            sec_user_agent = f"Stock-Valuation {sec_email}" if sec_email else None
            if not sec_email:
                st.sidebar.warning("Enter a contact email to download financial statements from SEC, or upload historical data.")
    allow_financial = st.sidebar.checkbox("Allow financial-company override", value=False)
    run_clicked = st.sidebar.button("Run Valuation", type="primary", use_container_width=True)
    if st.sidebar.button("Clear Results", use_container_width=True):
        clear_results(st.session_state)
        st.rerun()
    return run_clicked, {
        "ticker": ticker, "valuation_date": valuation_date, "forecast_years": forecast_years,
        "competitive_advantage_years": competitive_years, "currency": currency,
        "peer_tickers": peers, "revenue_growth_start": revenue_growth,
        "terminal_growth_rate": terminal_growth, "terminal_ronic": terminal_ronic,
        "enforce_terminal_ronic_to_tocc": enforce_terminal,
        "ebit_margin_terminal": terminal_margin, "tax_rate": tax_rate,
        "risk_free_rate": risk_free, "market_risk_premium": market_premium,
        "selected_asset_beta": None, "debt_beta": debt_beta,
        "debt_policy": DEBT_POLICIES[debt_label], "cash_tax_rate": cash_tax_rate,
        "interest_limit_percentage": interest_limit, "tax_shield_discount_rate": shield_rate,
        "minimum_cash": minimum_cash, "historical_upload": historical_upload,
        "allow_financial_company": allow_financial, "scenarios": scenarios,
        "sec_user_agent": sec_user_agent,
    }


def _render_summary(result) -> None:
    render_metric_cards(result)
    st.caption("Positive premium/(discount) means intrinsic value is above market price; negative means it is below market price. This is not a buy/sell recommendation.")
    if result.summary.get("liquidity_shortfall", 0) > 0:
        st.warning(
            f"Financing required: the forecast needs at least "
            f"{format_large_currency(result.summary['minimum_external_funding'])} of external funding "
            f"to maintain minimum cash, beginning in {result.summary['first_liquidity_breach_year']}. "
            "This is treated as a risk warning, not a model calculation failure."
        )
    render_overall_status(result.summary["overall_model_status"])
    left, right = st.columns([1, 1.25])
    with left:
        st.subheader("Valuation Bridge")
        st.dataframe(pd.DataFrame(valuation_bridge_rows(result)), hide_index=True, use_container_width=True)
    with right:
        st.plotly_chart(valuation_waterfall(result.summary), use_container_width=True, key="summary_waterfall")
    st.subheader("Downloads")
    render_downloads({"excel": st.session_state.excel_path, "report": st.session_state.report_path, "assumptions": st.session_state.assumptions_path, "source": st.session_state.source_data_path}, result.ticker, key_prefix="summary")


def _render_historical(result) -> None:
    st.caption("Historical analysis uses the latest five comparable fiscal years. When no file is uploaded, annual statements are downloaded from SEC Company Facts.")
    columns = ["year", "revenue", "revenue_growth", "ebit", "ebit_margin", "nopat", "operating_invested_capital", "roic", "tocc", "roic_spread", "economic_profit", "fcf"]
    frame = pd.DataFrame(result.historical)
    frame["revenue_growth"] = frame["revenue"].pct_change()
    st.dataframe(_format_frame(frame[columns], ["revenue_growth", "ebit_margin", "roic", "tocc", "roic_spread"], ["revenue", "ebit", "nopat", "operating_invested_capital", "economic_profit", "fcf"]), use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    c1.plotly_chart(historical_chart(result.historical, "revenue", "Revenue History"), use_container_width=True, key="historical_revenue")
    c2.plotly_chart(historical_chart(result.historical, "ebit_margin", "EBIT Margin", True), use_container_width=True, key="historical_margin")
    c3, c4 = st.columns(2)
    c3.plotly_chart(historical_chart(result.historical, "roic", "Historical ROIC", True), use_container_width=True, key="historical_roic")
    c4.plotly_chart(historical_chart(result.historical, "fcf", "Historical Free Cash Flow"), use_container_width=True, key="historical_fcf")


def _render_roic_tree(result) -> None:
    frame = pd.DataFrame(result.historical)[["year", "roic", "ebit_margin", "tax_efficiency", "capital_turnover", "roic_spread", "economic_profit"]]
    st.latex(r"ROIC = EBIT\ Margin \times Tax\ Efficiency \times Capital\ Turnover")
    st.dataframe(_format_frame(frame, ["roic", "ebit_margin", "tax_efficiency", "roic_spread"], ["economic_profit"]), use_container_width=True, hide_index=True)
    check = next((row for row in result.checks if row.name == "ROIC tree reconciliation"), None)
    if check and check.status == "PASS":
        st.success("ROIC tree reconciliation: PASS")
    elif check:
        st.warning(f"ROIC tree reconciliation: {check.status}")


def _target_roic_comparable_row(result) -> dict:
    history = sorted(result.historical, key=lambda row: row["year"])
    latest = history[-1]
    prior = history[-2] if len(history) > 1 else latest
    revenue = latest["revenue"]
    average_ic = latest["average_invested_capital"]
    tax_rate = result.assumptions["tax_rate"] if latest["ebit"] > 0 else 0.0
    return {
        "Company": result.ticker,
        "Fiscal Year": latest["year"],
        "Revenue Growth": revenue / prior["revenue"] - 1 if prior["revenue"] else None,
        "After-tax Operating ROIC": latest["ebit"] * (1 - tax_rate) / average_ic if average_ic else None,
        "Pre-tax ROIC": latest["ebit"] / average_ic if average_ic else None,
        "Cash Tax Rate": tax_rate,
        "EBIT Margin": latest["ebit_margin"],
        "Capital Turnover": latest["capital_turnover"],
        "COGS / Revenue": latest["cogs"] / revenue if revenue else None,
        "SG&A / Revenue": latest["sga"] / revenue if revenue else None,
        "R&D / Revenue": latest["rd"] / revenue if revenue else None,
        "Net PP&E / Revenue": latest["net_ppe"] / revenue if revenue else None,
        "WCR / Revenue": latest["owc"] / revenue if revenue else None,
        "Cash / Revenue": (latest["cash"] + latest["marketable_securities"]) / revenue if revenue else None,
        "Receivables / Revenue": latest["receivables"] / revenue if revenue else None,
        "Inventory / Revenue": latest["inventory"] / revenue if revenue else None,
        "Payables / Revenue": latest["accounts_payable"] / revenue if revenue else None,
        "Source": "Valuation historical data",
    }


def _roic_comparable_frame(result) -> pd.DataFrame:
    mapping = {
        "roic_fiscal_year": "Fiscal Year", "revenue_growth": "Revenue Growth",
        "after_tax_roic": "After-tax Operating ROIC", "pre_tax_roic": "Pre-tax ROIC",
        "cash_tax_rate": "Cash Tax Rate", "ebit_margin": "EBIT Margin",
        "capital_turnover": "Capital Turnover", "cogs_revenue": "COGS / Revenue",
        "sga_revenue": "SG&A / Revenue", "rd_revenue": "R&D / Revenue",
        "net_ppe_revenue": "Net PP&E / Revenue", "wcr_revenue": "WCR / Revenue",
        "cash_revenue": "Cash / Revenue", "receivables_revenue": "Receivables / Revenue",
        "inventory_revenue": "Inventory / Revenue", "payables_revenue": "Payables / Revenue",
    }
    rows = [_target_roic_comparable_row(result)]
    for peer in result.tocc_peers:
        if not any(peer.get(key) is not None for key in mapping):
            continue
        row = {"Company": peer.get("peer"), "Source": peer.get("source")}
        row.update({label: peer.get(key) for key, label in mapping.items()})
        rows.append(row)
    return pd.DataFrame(rows)


def _comparison_chart(frame: pd.DataFrame, metric: str, *, percentage: bool = True):
    data = frame[["Company", metric]].dropna().copy()
    data["Series"] = data["Company"].eq(frame.iloc[0]["Company"]).map({True: "Selected company", False: "Comparable"})
    figure = px.bar(
        data, x="Company", y=metric, color="Series", title=metric,
        color_discrete_map={"Selected company": "#17365d", "Comparable": "#5b9bd5"},
    )
    figure.update_layout(showlegend=False, margin=dict(l=20, r=20, t=45, b=20), height=330)
    figure.update_yaxes(tickformat=".1%" if percentage else ".2f")
    return figure


def _render_roic_comparables(result) -> None:
    st.subheader("Kevin Kaiser ROIC Tree — Comparable-Company Diagnostic")
    st.caption(
        "Lecture structure: after-tax operating ROIC = pre-tax ROIC × (1 − cash tax rate); "
        "pre-tax ROIC = normalized EBIT margin × capital turnover. Lower branches diagnose cost structure, "
        "working-capital intensity, and fixed-asset intensity."
    )
    frame = _roic_comparable_frame(result)
    if len(frame) == 1:
        st.warning("Yahoo annual-statement data were unavailable for the automatically selected comparables.")
    percent_columns = [column for column in frame.columns if column not in {"Company", "Fiscal Year", "Capital Turnover", "Source"}]
    st.dataframe(_format_frame(frame, percent_columns), use_container_width=True, hide_index=True)

    st.markdown("#### ROIC outcome and first-level decomposition")
    c1, c2, c3 = st.columns(3)
    c1.plotly_chart(_comparison_chart(frame, "After-tax Operating ROIC"), use_container_width=True, key="comp_roic")
    c2.plotly_chart(_comparison_chart(frame, "Pre-tax ROIC"), use_container_width=True, key="comp_pretax_roic")
    c3.plotly_chart(_comparison_chart(frame, "Cash Tax Rate"), use_container_width=True, key="comp_tax")

    st.markdown("#### Operating efficiency × capital effectiveness")
    c4, c5 = st.columns(2)
    c4.plotly_chart(_comparison_chart(frame, "EBIT Margin"), use_container_width=True, key="comp_margin")
    c5.plotly_chart(_comparison_chart(frame, "Capital Turnover", percentage=False), use_container_width=True, key="comp_turnover")

    st.markdown("#### EBIT-margin drivers")
    cost_metrics = ["COGS / Revenue", "SG&A / Revenue", "R&D / Revenue"]
    for column, metric in zip(st.columns(3), cost_metrics):
        column.plotly_chart(_comparison_chart(frame, metric), use_container_width=True, key=f"comp_{metric}")

    st.markdown("#### Invested-capital and operating-cycle drivers")
    capital_metrics = ["Net PP&E / Revenue", "WCR / Revenue", "Receivables / Revenue", "Inventory / Revenue", "Payables / Revenue", "Cash / Revenue"]
    for start in range(0, len(capital_metrics), 3):
        for column, metric in zip(st.columns(3), capital_metrics[start:start + 3]):
            column.plotly_chart(_comparison_chart(frame, metric), use_container_width=True, key=f"comp_{metric}")
    st.caption(
        "Yahoo's reported invested capital is used for peer turnover; WCR is approximated as current assets less cash, "
        "less current liabilities, plus current debt. Missing provider classifications remain blank rather than being estimated."
    )


def _render_forecast(result) -> None:
    frame = pd.DataFrame(result.forecast + result.overperformance)
    columns = ["year", "phase", "revenue", "revenue_growth", "ebit_margin", "nopat", "invested_capital", "net_investment", "roic", "ronic", "fcf", "discount_factor", "pv_fcf"]
    st.dataframe(_format_frame(frame[columns], ["revenue_growth", "ebit_margin", "roic", "ronic", "discount_factor"], ["revenue", "nopat", "invested_capital", "net_investment", "fcf", "pv_fcf"]), use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    c1.plotly_chart(combined_chart(result, "revenue", "Historical and Forecast Revenue"), use_container_width=True, key="forecast_revenue")
    c2.plotly_chart(combined_chart(result, "ebit_margin", "Historical and Forecast EBIT Margin", True), use_container_width=True, key="forecast_margin")
    c3, c4 = st.columns(2)
    c3.plotly_chart(combined_chart(result, "fcf", "Free Cash Flow"), use_container_width=True, key="forecast_fcf")
    c4.plotly_chart(roic_ronic_chart(result), use_container_width=True, key="forecast_returns")


def _render_tocc(result) -> None:
    s, a = result.summary, result.assumptions
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk-free Rate", format_percentage(a["risk_free_rate"]))
    c2.metric("Market Risk Premium", format_percentage(a["market_risk_premium"]))
    c3.metric("Selected Asset Beta", f"{a['selected_asset_beta']:.2f}x")
    c4.metric("Unlevered TOCC", format_percentage(s["tocc"]))
    peers = pd.DataFrame(result.tocc_peers).rename(columns={"peer": "Peer", "company_name": "Company", "selection_method": "Selection", "recommendation_score": "Yahoo Score", "equity_beta": "Equity Beta", "debt_beta": "Debt Beta", "debt": "Debt", "equity": "Market Equity", "raw_asset_beta": "Raw Asset Beta", "adjusted_asset_beta": "Adjusted Asset Beta", "weight": "Selected Weight"})
    if peers.empty:
        st.warning("Yahoo peer statistics were unavailable. The selected asset beta is the disclosed sector-beta fallback.")
    else:
        visible = ["Peer", "Company", "Selection", "currency", "Yahoo Score", "Equity Beta", "Debt Beta", "Debt", "Market Equity", "Raw Asset Beta", "Adjusted Asset Beta", "Selected Weight", "source"]
        st.dataframe(_format_frame(peers[visible], ["Selected Weight"], ["Debt", "Market Equity"]), use_container_width=True, hide_index=True)


def _render_apv(result) -> None:
    s = result.summary
    st.subheader("APV and Equity Bridge")
    st.dataframe(pd.DataFrame(valuation_bridge_rows(result)), use_container_width=True, hide_index=True)
    st.plotly_chart(valuation_waterfall(s), use_container_width=True, key="apv_waterfall")
    st.subheader("Continuing Value")
    continuing = pd.DataFrame([
        ["Final fade-period NOPAT", s["terminal_nopat"]], ["Next-year NOPAT", s["terminal_nopat_next"]],
        ["Terminal growth", s["terminal_growth"]], ["Terminal RONIC", s["terminal_ronic"]],
        ["Reinvestment rate", s["terminal_reinvestment_rate"]], ["Terminal FCF", s["terminal_fcf"]],
        ["Continuing value", s["continuing_value_at_terminal"]], ["PV continuing value", s["pv_continuing_value"]],
        ["PV continuing value / APV EV", s["continuing_value_share"]],
    ], columns=["Metric", "Value"])
    st.dataframe(continuing, use_container_width=True, hide_index=True)
    for check in result.checks:
        if check.category == "Continuing value" and check.status != "PASS":
            st.warning(f"{check.name}: {check.notes or check.status}")
    st.subheader("Financing Effects")
    first = result.tax_shield[0] if result.tax_shield else {}
    financing = pd.DataFrame([
        ["Interest expense — Year 1", first.get("interest")], ["ATI — Year 1", first.get("ati")],
        ["ATI deduction limit", first.get("limit")], ["Deductible interest", first.get("deductible_interest")],
        ["Cash tax rate", first.get("cash_tax_rate")], ["Usable interest tax shield", first.get("usable_tax_shield")],
        ["PV explicit tax shields", s["pv_explicit_tax_shields"]], ["PV continuing tax shield", s["pv_continuing_tax_shield"]],
        ["Ending interest carryforward", first.get("ending_carryforward")],
    ], columns=["Metric", "Value"])
    st.dataframe(financing, use_container_width=True, hide_index=True)
    st.latex(r"Usable\ Tax\ Shield = Cash\ Tax\ Rate \times \min(Interest,\ 30\% \times ATI)")
    st.caption("The engine further constrains this simplified formula through parallel NOL and interest-carryforward schedules.")


def _render_scenarios(result) -> None:
    st.metric("Probability-Weighted Intrinsic Value", format_currency(result.summary["probability_weighted_value"]))
    frame = pd.DataFrame(result.scenarios)
    st.subheader("Scenario Inputs Used")
    input_columns = ["scenario", "probability"]
    st.dataframe(_format_frame(frame[input_columns], ["probability"]), use_container_width=True, hide_index=True)
    st.subheader("Scenario Valuation Results")
    st.dataframe(_format_frame(frame[["scenario", "probability", "tocc", "terminal_growth", "terminal_ronic", "apv_enterprise_value", "equity_value", "diluted_shares", "intrinsic_value_per_share"]], ["probability", "tocc", "terminal_growth", "terminal_ronic"], ["apv_enterprise_value", "equity_value"]), use_container_width=True, hide_index=True)
    st.plotly_chart(scenario_chart(result.scenarios), use_container_width=True, key="scenario_values")
    scenario_tabs = st.tabs([row["scenario"] for row in result.scenarios])
    for tab, row in zip(scenario_tabs, result.scenarios):
        with tab:
            cols = st.columns(4)
            cols[0].metric("Probability", format_percentage(row["probability"]))
            cols[1].metric("TOCC", format_percentage(row["tocc"]))
            cols[2].metric("Terminal Growth", format_percentage(row["terminal_growth"]))
            cols[3].metric("Intrinsic Value / Share", format_currency(row["intrinsic_value_per_share"]))
            st.write("Liquidation scenario" if row.get("liquidation") else "Going-concern scenario")


def _render_sensitivity(result) -> None:
    growth_table, growth_chart = sensitivity_heatmap(result.sensitivities["tocc_vs_growth"], "terminal_growth", "TOCC versus Terminal Growth")
    st.plotly_chart(growth_chart, use_container_width=True, key="sensitivity_growth")
    st.dataframe(growth_table.style.format("${:,.2f}", na_rep="—"), use_container_width=True)
    ronic_table, ronic_chart = sensitivity_heatmap(result.sensitivities["tocc_vs_ronic"], "terminal_ronic", "TOCC versus Terminal RONIC")
    st.plotly_chart(ronic_chart, use_container_width=True, key="sensitivity_ronic")
    st.dataframe(ronic_table.style.format("${:,.2f}", na_rep="—"), use_container_width=True)
    st.caption("The base case locks terminal RONIC to TOCC; the second table is a diagnostic departure from that steady-state discipline.")


def _render_checks(result) -> None:
    render_overall_status(result.summary["overall_model_status"])
    frame = pd.DataFrame([{"Category": row.category, "Check": row.name, "Status": row.status, "Observed Value": _display_value(row.actual), "Expected Condition": _display_value(row.expected), "Explanation": row.notes} for row in result.checks])
    st.dataframe(frame, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Public Company Valuation", page_icon="📊", layout="wide")
    initialize_session_state(st.session_state)
    st.markdown("""
        <style>
        .block-container {padding-top: 1.7rem; padding-bottom: 3rem;}
        [data-testid="stMetric"] {background: #f7f9fb; border: 1px solid #d9e2f3; padding: 14px; border-radius: 8px;}
        [data-testid="stMetricValue"] {font-size: 1.65rem; overflow: visible;}
        h1, h2, h3 {color: #17365d;}
        </style>
    """, unsafe_allow_html=True)
    st.title("Public Company Valuation")
    st.subheader("Assumption-Free Corporate Valuation Framework")
    st.write("Analyze historical performance, forecast future free cash flow, estimate TOCC (The Opportunity Cost of Capital), calculate continuing value, and complete an Adjusted Present Value valuation.")

    run_clicked, values = _sidebar_inputs()
    if run_clicked:
        progress = st.progress(5, text="Validating inputs…")
        try:
            data_file = _persist_historical_upload(values.pop("historical_upload"))
            config = build_valuation_config(**values, data_file=data_file)
            progress.progress(25, text=f"Loading operating data for {config.ticker}…")
            with st.spinner(f"Running valuation for {config.ticker}…"):
                artifacts = run_company_valuation(config)
            progress.progress(90, text="Preparing workbook and report downloads…")
            store_artifacts(st.session_state, artifacts)
            progress.progress(100, text="Valuation complete")
            st.success(f"Valuation completed for {config.ticker}.")
        except Exception as exc:
            logger.exception("Valuation failed")
            progress.empty()
            message = str(exc)
            if "No offline sample data" in message or "period" in message.lower():
                message = "Historical operating data could not be retrieved from SEC Company Facts or the Yahoo Finance annual-statement fallback. Upload a normalized historical-data file or try again later."
            st.error(f"Valuation could not be completed: {message}")

    result = st.session_state.valuation_results
    if result is None:
        st.info("AAPL is prefilled as an example. Review the assumptions, then select **Run Valuation**. The included synthetic DEMO company remains available for offline use.")
        return

    st.caption(f"Last run: {st.session_state.last_run_timestamp} | Ticker: {result.ticker} | Values in {result.company['currency']} millions unless noted")
    tabs = st.tabs(["Summary", "Historical Analysis", "ROIC Tree", "ROIC Tree — Comparables", "Forecast", "TOCC", "APV and Equity Bridge", "Scenarios", "Sensitivity", "Model Checks", "Data Sources"])
    with tabs[0]: _render_summary(result)
    with tabs[1]: _render_historical(result)
    with tabs[2]: _render_roic_tree(result)
    with tabs[3]: _render_roic_comparables(result)
    with tabs[4]: _render_forecast(result)
    with tabs[5]: _render_tocc(result)
    with tabs[6]: _render_apv(result)
    with tabs[7]: _render_scenarios(result)
    with tabs[8]: _render_sensitivity(result)
    with tabs[9]: _render_checks(result)
    with tabs[10]:
        provenance = [{key: _display_value(value) for key, value in row.items()} for row in result.provenance]
        st.dataframe(pd.DataFrame(provenance), use_container_width=True, hide_index=True)
        render_downloads({"excel": st.session_state.excel_path, "report": st.session_state.report_path, "assumptions": st.session_state.assumptions_path, "source": st.session_state.source_data_path}, result.ticker, key_prefix="sources")


if __name__ == "__main__":
    main()
