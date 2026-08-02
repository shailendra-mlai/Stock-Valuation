from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


COLORS = {"historical": "#7f8c8d", "forecast": "#1f4e78", "fade": "#8064a2", "tocc": "#c55a11"}


def valuation_waterfall(summary: dict[str, Any]) -> go.Figure:
    labels = ["Explicit FCF", "Continuing value", "Financing effects", "Debt & claims", "Excess cash", "Equity value"]
    values = [
        summary["pv_explicit_fcf"], summary["pv_continuing_value"], summary["pv_financing_effects"],
        -(summary["gross_debt"] + summary["other_financing_claims"]), summary["excess_cash"], summary["equity_value"],
    ]
    figure = go.Figure(go.Waterfall(
        x=labels, y=values, measure=["relative", "relative", "relative", "relative", "relative", "total"],
        connector={"line": {"color": "#b7c4ce"}}, increasing={"marker": {"color": "#548235"}},
        decreasing={"marker": {"color": "#c00000"}}, totals={"marker": {"color": "#1f4e78"}},
    ))
    figure.update_layout(title="APV Enterprise-to-Equity Bridge", showlegend=False, yaxis_title="$mm", height=390)
    return figure


def historical_chart(rows: list[dict[str, Any]], value: str, title: str, percent: bool = False) -> go.Figure:
    frame = pd.DataFrame(rows)
    figure = px.line(frame, x="year", y=value, markers=True, title=title, color_discrete_sequence=[COLORS["historical"]])
    figure.update_layout(height=320, showlegend=False, yaxis_tickformat=".1%" if percent else ",.0f")
    return figure


def combined_chart(result: Any, value: str, title: str, percent: bool = False) -> go.Figure:
    rows = []
    for row in result.historical:
        rows.append({"year": row["year"], "value": row.get(value), "phase": "Historical"})
    for row in result.forecast:
        rows.append({"year": row["year"], "value": row.get(value), "phase": "Explicit forecast"})
    for row in result.overperformance:
        rows.append({"year": row["year"], "value": row.get(value), "phase": "Competitive-advantage fade"})
    frame = pd.DataFrame(rows)
    figure = px.line(
        frame, x="year", y="value", color="phase", markers=True, title=title,
        color_discrete_map={"Historical": COLORS["historical"], "Explicit forecast": COLORS["forecast"], "Competitive-advantage fade": COLORS["fade"]},
    )
    figure.update_layout(height=340, yaxis_tickformat=".1%" if percent else ",.0f", legend_title_text="")
    return figure


def roic_ronic_chart(result: Any) -> go.Figure:
    figure = go.Figure()
    history = pd.DataFrame(result.historical)
    forecast = pd.DataFrame(result.forecast + result.overperformance)
    figure.add_trace(go.Scatter(x=history["year"], y=history["roic"], name="Historical ROIC", line={"color": COLORS["historical"]}))
    figure.add_trace(go.Scatter(x=forecast["year"], y=forecast["roic"], name="Forecast ROIC", line={"color": COLORS["forecast"]}))
    figure.add_trace(go.Scatter(x=forecast["year"], y=forecast["ronic"], name="RONIC", line={"color": COLORS["fade"], "dash": "dot"}))
    figure.add_trace(go.Scatter(x=[history["year"].min(), forecast["year"].max()], y=[result.summary["tocc"]] * 2, name="TOCC", line={"color": COLORS["tocc"], "dash": "dash"}))
    figure.update_layout(title="ROIC and RONIC versus TOCC", yaxis_tickformat=".1%", height=360, legend_title_text="")
    return figure


def scenario_chart(rows: list[dict[str, Any]]) -> go.Figure:
    frame = pd.DataFrame(rows)
    figure = px.bar(frame, x="scenario", y="intrinsic_value_per_share", color="scenario", text_auto=".2f", title="Scenario Intrinsic Value per Share")
    figure.update_layout(height=350, showlegend=False, xaxis_title="", yaxis_title="$/share")
    return figure


def sensitivity_heatmap(rows: list[dict[str, Any]], column_key: str, title: str) -> tuple[pd.DataFrame, go.Figure]:
    frame = pd.DataFrame(rows)
    table = frame.pivot_table(index="tocc", columns=column_key, values="value_per_share", aggfunc="first").sort_index(ascending=False)
    figure = px.imshow(table, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn", title=title)
    figure.update_layout(height=390, xaxis_title=column_key.replace("_", " ").title(), yaxis_title="TOCC")
    figure.update_xaxes(tickformat=".1%")
    figure.update_yaxes(tickformat=".1%")
    return table, figure
