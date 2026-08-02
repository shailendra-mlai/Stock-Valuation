from __future__ import annotations

from valuation_system.models.company import HistoricalYear


def operating_working_capital(year: HistoricalYear) -> float:
    operating_current_assets = (
        year.receivables + year.inventory + year.other_current_operating_assets
    )
    operating_current_liabilities = (
        year.accounts_payable
        + year.accrued_operating_liabilities
        + year.deferred_revenue
        + year.other_operating_liabilities
    )
    return operating_current_assets - operating_current_liabilities


def operating_invested_capital(year: HistoricalYear) -> float:
    return (
        operating_working_capital(year)
        + year.net_ppe
        + year.operating_lease_assets
        + year.other_operating_assets
    )


def financing_invested_capital(year: HistoricalYear) -> float:
    return (
        year.debt
        + year.lease_liabilities
        + year.equity
        - year.cash
        - year.marketable_securities
    )
