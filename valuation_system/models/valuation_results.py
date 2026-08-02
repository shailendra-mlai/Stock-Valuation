from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CheckResult:
    category: str
    name: str
    status: str
    actual: Any = ""
    expected: Any = ""
    difference: Any = ""
    tolerance: Any = ""
    notes: str = ""


@dataclass
class ValuationResult:
    ticker: str
    historical: list[dict[str, Any]]
    forecast: list[dict[str, Any]]
    overperformance: list[dict[str, Any]]
    tocc_peers: list[dict[str, Any]]
    tax_shield: list[dict[str, Any]]
    scenarios: list[dict[str, Any]]
    sensitivities: dict[str, list[dict[str, Any]]]
    checks: list[CheckResult]
    summary: dict[str, Any]
    equity_bridge: list[dict[str, Any]]
    value_drivers: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    assumptions: dict[str, Any]
    company: dict[str, Any]
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
