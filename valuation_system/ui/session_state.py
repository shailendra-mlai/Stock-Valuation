from __future__ import annotations

from typing import MutableMapping, Any


RESULT_KEYS = (
    "valuation_results",
    "valuation_config",
    "ticker",
    "excel_path",
    "report_path",
    "assumptions_path",
    "source_data_path",
    "last_run_timestamp",
)


def initialize_session_state(state: MutableMapping[str, Any]) -> None:
    for key in RESULT_KEYS:
        state.setdefault(key, None)


def clear_results(state: MutableMapping[str, Any]) -> None:
    for key in RESULT_KEYS:
        state[key] = None


def store_artifacts(state: MutableMapping[str, Any], artifacts: Any) -> None:
    state["valuation_results"] = artifacts.result
    state["valuation_config"] = artifacts.config
    state["ticker"] = artifacts.result.ticker
    state["excel_path"] = artifacts.excel_path
    state["report_path"] = artifacts.report_path
    state["assumptions_path"] = artifacts.assumptions_path
    state["source_data_path"] = artifacts.source_data_path
    state["last_run_timestamp"] = artifacts.completed_at
