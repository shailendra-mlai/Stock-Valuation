from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DEFAULT_SAMPLE_DATA = PROJECT_DIR / "sample_company_data.csv"
EXCEL_BUILDER = PACKAGE_DIR / "reporting" / "build_workbook.mjs"

REQUIRED_TABS = [
    "Cover", "Sources", "Raw Financials", "Reclassified Financials",
    "Historical Analysis", "ROIC Tree", "Value Drivers", "Forecast Assumptions",
    "Forecast", "Working Capital", "Fixed Assets", "Free Cash Flow", "TOCC",
    "Debt Schedule", "Interest Tax Shield", "Continuing Value", "APV",
    "Equity Bridge", "Market Comparison", "Scenarios", "Sensitivities",
    "Model Checks", "Dashboard",
]
