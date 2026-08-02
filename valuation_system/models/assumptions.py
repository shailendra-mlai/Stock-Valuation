from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ScenarioAssumption:
    probability: float
    revenue_growth_delta: float = 0.0
    ebit_margin_delta: float = 0.0
    capital_turnover_delta: float = 0.0
    terminal_growth_delta: float = 0.0
    tocc_delta: float = 0.0


@dataclass
class ValuationAssumptions:
    ticker: str = "RIVN"
    valuation_date: str = field(default_factory=lambda: date.today().isoformat())
    forecast_years: int = 10
    currency: str = "USD"
    revenue_growth_start: float = 0.18
    revenue_growth_terminal: float = 0.025
    ebit_margin_start: float = -0.12
    ebit_margin_terminal: float = 0.10
    tax_rate: float = 0.21
    cash_tax_rate: float = 0.17
    risk_free_rate: float = 0.0425
    market_risk_premium: float = 0.045
    selected_asset_beta: float = 1.25
    terminal_growth_rate: float = 0.025
    terminal_ronic: float = 0.10
    operating_cash_percentage: float = 0.02
    minimum_cash: float = 500.0
    debt_beta: float = 0.15
    tax_shield_discount_rate: float | None = None
    debt_policy: str = "scheduled_amortization"
    interest_rate: float = 0.065
    interest_limit_percentage: float = 0.30
    market_price_override: float | None = None
    allow_financial_company: bool = False
    reconciliation_tolerance: float = 1e-6
    scenarios: dict[str, ScenarioAssumption] = field(
        default_factory=lambda: {
            "downside": ScenarioAssumption(0.25, -0.05, -0.04, -0.20, -0.005, 0.01),
            "base": ScenarioAssumption(0.50),
            "upside": ScenarioAssumption(0.25, 0.05, 0.04, 0.20, 0.005, -0.005),
        }
    )

    @property
    def tocc(self) -> float:
        return self.risk_free_rate + self.selected_asset_beta * self.market_risk_premium

    @property
    def shield_rate(self) -> float:
        return self.tax_shield_discount_rate or self.tocc

    def validate(self) -> None:
        if not 1 <= self.forecast_years <= 30:
            raise ValueError("forecast_years must be between 1 and 30")
        if self.terminal_growth_rate >= self.tocc:
            raise ValueError("terminal growth must be less than TOCC")
        if self.terminal_ronic <= 0:
            raise ValueError("terminal RONIC must be positive")
        reinvestment = self.terminal_growth_rate / self.terminal_ronic
        if not 0 <= reinvestment <= 1:
            raise ValueError("terminal reinvestment rate must be between 0% and 100%")
        probability = sum(s.probability for s in self.scenarios.values())
        if abs(probability - 1.0) > 1e-9:
            raise ValueError("scenario probabilities must total 100%")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_yaml(cls, path: str | Path, ticker: str | None = None) -> "ValuationAssumptions":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        terminal = raw.pop("terminal", {})
        tocc = raw.pop("tocc", {})
        tax = raw.pop("tax", {})
        debt = raw.pop("debt_policy", {})
        scenario_raw = raw.pop("scenarios", {})
        mapped: dict[str, Any] = {
            **raw,
            "terminal_growth_rate": terminal.get("growth_rate", cls.terminal_growth_rate),
            "terminal_ronic": terminal.get("ronic", cls.terminal_ronic),
            "risk_free_rate": tocc.get("risk_free_rate") or cls.risk_free_rate,
            "market_risk_premium": tocc.get("market_risk_premium", cls.market_risk_premium),
            "tax_rate": tax.get("normalized_operating_tax_rate", cls.tax_rate),
            "cash_tax_rate": tax.get("cash_tax_rate", cls.cash_tax_rate),
            "interest_limit_percentage": tax.get("interest_limit_percentage", cls.interest_limit_percentage),
            "debt_policy": debt.get("type", cls.debt_policy),
        }
        if ticker:
            mapped["ticker"] = ticker.upper()
        if scenario_raw:
            mapped["scenarios"] = {
                name: ScenarioAssumption(**values) for name, values in scenario_raw.items()
            }
        allowed = set(cls.__dataclass_fields__)
        instance = cls(**{k: v for k, v in mapped.items() if k in allowed})
        instance.validate()
        return instance
