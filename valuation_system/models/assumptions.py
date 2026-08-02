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
    new_borrowing: float = 0.0
    equity_raise: float = 0.0
    new_shares: float = 0.0
    liquidation: bool = False
    liquidation_recovery_rate: float = 0.35


@dataclass
class ValuationAssumptions:
    ticker: str = "RIVN"
    valuation_date: str = field(default_factory=lambda: date.today().isoformat())
    forecast_years: int = 10
    competitive_advantage_years: int = 10
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
    peer_tickers: list[str] = field(default_factory=lambda: ["TSLA", "GM", "F", "LCID"])
    terminal_growth_rate: float = 0.025
    terminal_ronic: float | None = None
    enforce_terminal_ronic_to_tocc: bool = True
    operating_cash_percentage: float = 0.02
    minimum_cash: float = 500.0
    initial_operating_nol: float = 0.0
    annual_sbc_dilution_rate: float = 0.0
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
            "failure": ScenarioAssumption(0.20, liquidation=True, liquidation_recovery_rate=0.25),
            "downside": ScenarioAssumption(0.25, -0.05, -0.04, -0.20, -0.005, 0.01),
            "base": ScenarioAssumption(0.40),
            "upside": ScenarioAssumption(0.15, 0.05, 0.04, 0.20, 0.005, -0.005),
        }
    )

    @property
    def tocc(self) -> float:
        return self.risk_free_rate + self.selected_asset_beta * self.market_risk_premium

    @property
    def shield_rate(self) -> float:
        return self.tax_shield_discount_rate or self.tocc

    def effective_terminal_ronic(self, tocc: float | None = None) -> float:
        hurdle = self.tocc if tocc is None else tocc
        if self.enforce_terminal_ronic_to_tocc or self.terminal_ronic is None:
            return hurdle
        return self.terminal_ronic

    def validate(self) -> None:
        if not 1 <= self.forecast_years <= 30:
            raise ValueError("forecast_years must be between 1 and 30")
        if not 0 <= self.competitive_advantage_years <= 30:
            raise ValueError("competitive_advantage_years must be between 0 and 30")
        if self.terminal_growth_rate >= self.tocc:
            raise ValueError("terminal growth must be less than TOCC")
        terminal_ronic = self.effective_terminal_ronic()
        if terminal_ronic <= 0:
            raise ValueError("terminal RONIC must be positive")
        reinvestment = self.terminal_growth_rate / terminal_ronic
        if not 0 <= reinvestment <= 1:
            raise ValueError("terminal reinvestment rate must be between 0% and 100%")
        probability = sum(s.probability for s in self.scenarios.values())
        if abs(probability - 1.0) > 1e-9:
            raise ValueError("scenario probabilities must total 100%")
        if self.initial_operating_nol < 0 or self.annual_sbc_dilution_rate < 0:
            raise ValueError("NOL and annual dilution assumptions cannot be negative")
        if any(not 0 <= s.liquidation_recovery_rate <= 1 for s in self.scenarios.values()):
            raise ValueError("liquidation recovery rates must be between 0% and 100%")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_yaml(cls, path: str | Path, ticker: str | None = None) -> "ValuationAssumptions":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        terminal = raw.pop("terminal", {})
        tocc = raw.pop("tocc", {})
        tax = raw.pop("tax", {})
        debt = raw.pop("debt_policy", {})
        overperformance = raw.pop("overperformance", {})
        liquidity = raw.pop("liquidity", {})
        dilution = raw.pop("dilution", {})
        scenario_raw = raw.pop("scenarios", {})
        mapped: dict[str, Any] = {
            **raw,
            "terminal_growth_rate": terminal.get("growth_rate", cls.terminal_growth_rate),
            "terminal_ronic": terminal.get("ronic", cls.terminal_ronic),
            "enforce_terminal_ronic_to_tocc": terminal.get("enforce_ronic_equals_tocc", True),
            "risk_free_rate": tocc.get("risk_free_rate") or cls.risk_free_rate,
            "market_risk_premium": tocc.get("market_risk_premium", cls.market_risk_premium),
            "peer_tickers": tocc.get("peer_tickers", ["TSLA", "GM", "F", "LCID"]),
            "tax_rate": tax.get("normalized_operating_tax_rate", cls.tax_rate),
            "cash_tax_rate": tax.get("cash_tax_rate", cls.cash_tax_rate),
            "interest_limit_percentage": tax.get("interest_limit_percentage", cls.interest_limit_percentage),
            "debt_policy": debt.get("type", cls.debt_policy),
            "competitive_advantage_years": overperformance.get("years", cls.competitive_advantage_years),
            "initial_operating_nol": tax.get("initial_operating_nol", cls.initial_operating_nol),
            "minimum_cash": liquidity.get("minimum_cash", cls.minimum_cash),
            "annual_sbc_dilution_rate": dilution.get("annual_sbc_rate", cls.annual_sbc_dilution_rate),
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
