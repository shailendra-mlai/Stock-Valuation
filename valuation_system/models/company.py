from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HistoricalYear:
    year: int
    revenue: float
    cogs: float
    sga: float
    rd: float
    da: float
    ebit: float
    taxes: float
    cash: float
    marketable_securities: float
    receivables: float
    inventory: float
    other_current_operating_assets: float
    net_ppe: float
    operating_lease_assets: float
    other_operating_assets: float
    accounts_payable: float
    accrued_operating_liabilities: float
    deferred_revenue: float
    other_operating_liabilities: float
    debt: float
    lease_liabilities: float
    equity: float
    capex: float
    stock_comp: float = 0.0


@dataclass
class ProvenanceRecord:
    variable: str
    value: Any
    source: str
    source_date: str
    retrieval_method: str
    original_unit: str = "USD millions"
    normalized_unit: str = "USD millions"
    user_override: bool = False
    confidence: str = "medium"
    notes: str = ""


@dataclass
class CompanyData:
    ticker: str
    name: str
    sector: str
    currency: str
    historical: list[HistoricalYear]
    share_price: float | None
    diluted_shares: float
    basic_shares: float
    market_cap: float | None = None
    restricted_stock: float = 0.0
    rsus: float = 0.0
    options: float = 0.0
    option_strike: float = 0.0
    warrants: float = 0.0
    convertibles: float = 0.0
    minority_interest: float = 0.0
    preferred_stock: float = 0.0
    pension_liability: float = 0.0
    non_operating_investments: float = 0.0
    restricted_cash: float = 0.0
    comparables: list[dict[str, Any]] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)

    @property
    def latest(self) -> HistoricalYear:
        return sorted(self.historical, key=lambda x: x.year)[-1]

    @property
    def is_financial(self) -> bool:
        text = self.sector.lower()
        return any(term in text for term in ("bank", "insurance", "financial services", "finance", "broker"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
