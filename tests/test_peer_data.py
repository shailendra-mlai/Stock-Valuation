import pytest

from valuation_system.data.peer_data import (
    discover_yahoo_comparables, load_yahoo_peer_data, selected_peer_beta,
)


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"finance": {"result": [{"recommendedSymbols": [
            {"symbol": "AAA", "score": 0.6},
            {"symbol": "BBB", "score": 0.4},
        ]}]}}


def request_get(*_args, **_kwargs):
    return Response()


def test_discovers_yahoo_people_also_watch_symbols():
    assert discover_yahoo_comparables("RIVN", request_get=request_get) == [
        {"peer": "AAA", "recommendation_score": 0.6},
        {"peer": "BBB", "recommendation_score": 0.4},
    ]


def test_peer_statistics_drive_weighted_adjusted_asset_beta():
    info = {
        "AAA": {"quoteType": "EQUITY", "shortName": "Alpha", "beta": 1.5, "marketCap": 100_000_000, "totalDebt": 20_000_000},
        "BBB": {"quoteType": "EQUITY", "shortName": "Beta", "beta": 1.0, "marketCap": 50_000_000, "totalDebt": 10_000_000},
    }
    rows = load_yahoo_peer_data("RIVN", request_get=request_get, info_loader=info.__getitem__)
    assert [row["peer"] for row in rows] == ["AAA", "BBB"]
    assert [row["weight"] for row in rows] == pytest.approx([0.6, 0.4])
    expected = rows[0]["adjusted_asset_beta"] * 0.6 + rows[1]["adjusted_asset_beta"] * 0.4
    assert selected_peer_beta(rows) == pytest.approx(expected)
