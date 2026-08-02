# Public Company Valuation System

This project implements a three-period, assumption-aware Adjusted Present Value (APV) system for nonfinancial public companies. It separates operating performance from financing, diagnoses ROIC drivers before forecasting, explicitly fades competitive advantage, locks terminal RONIC to unlevered TOCC, models NOL-constrained interest tax shields, tests liquidity, and completes a scenario-specific enterprise-to-equity bridge.

## Installation

Python 3.12+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The Excel exporter uses the Codex bundled `@oai/artifact-tool` runtime. In this workspace, set:

```bash
export VALUATION_NODE="$(command -v node)"
```

and create `node_modules` in the project root as a symlink to the Codex dependency path shown by the workspace loader.

## Two standalone analysis scripts

### 1. S&P 500 batch analysis

```bash
python sp500_analysis.py --workers 12 --output ./output
```

This downloads the current constituent universe, retrieves available Nasdaq annual statements and market data, runs the standardized APV screen for eligible nonfinancial companies, and creates a consolidated summary workbook. Financial institutions remain explicitly unvalued because the operating invested-capital framework is not appropriate for them.

### 2. Complete single-company analysis

```bash
python company_analysis.py --ticker NVDA --forecast-years 10 --competitive-advantage-years 10 --output ./output
```

The company script accepts any publicly traded nonfinancial-company ticker supported by the data provider. It creates:

- `<TICKER>_Valuation_<YYYYMMDD>.xlsx`
- `<TICKER>_Valuation_Report_<YYYYMMDD>.md`
- `<TICKER>_Valuation_<YYYYMMDD>.json`

The Excel workbook follows the expanded Rivian-style architecture: historical diagnosis, reclassification, ROIC tree, value drivers, explicit forecast, competitive-advantage fade, working capital, fixed assets, free cash flow, TOCC, debt, liquidity, parallel NOL/interest tax shields, continuing value, APV, equity bridge, scenarios, sensitivities, model checks, and dashboard.

Use an assumptions override when needed:

```bash
python company_analysis.py \
  --ticker RIVN \
  --assumptions assumptions_example.yaml \
  --output ./output
```

For an offline/reviewed normalized dataset:

```bash
python company_analysis.py \
  --ticker RIVN \
  --data-file sample_company_data.csv \
  --output ./output
```

## Combined app usage

```bash
python app.py --ticker RIVN --forecast-years 10 --output ./output
```

The original combined entry point remains available:

```bash
python app.py --sp500 --workers 12 --output ./output
```

The batch app caches responses for restartability and leaves financial institutions or missing-data rows explicitly unvalued. Its `Summary` tab contains TOCC, continuing-value, APV, equity, per-share, price, and premium/(discount) columns for every index share class.

With assumptions:

```bash
python app.py \
  --ticker RIVN \
  --forecast-years 10 \
  --assumptions assumptions_example.yaml \
  --output ./output
```

Use `--live` to attempt a live provider. The implementation deliberately rejects incomplete or low-confidence statement mappings and falls back to the auditable offline sample. Supply a normalized CSV with `--data-file` for another company.

## Data-source hierarchy

1. User override, clearly marked.
2. Reviewed SEC filing or SEC company-facts mapping.
3. Reviewed market-data provider values.
4. Offline normalized CSV.
5. Explicit forecast assumption.

The system does not silently fabricate a missing live value. Ambiguous accounting classifications are surfaced in provenance and checks.

## Assumptions-file format

See `assumptions_example.yaml`. Core sections cover the explicit and over-performance periods, terminal growth, the terminal RONIC-to-TOCC lock, TOCC inputs, NOL and interest-deductibility conventions, liquidity, dilution, debt policy, and coherent failure/downside/base/upside scenarios. Scenario probabilities must total 100%.

## Key formulas

- `Cash NOPAT = Adjusted EBIT − cash operating tax after NOL utilization`.
- `UFCF = NOPAT + D&A − Capex − ΔOWC − other operating investment`.
- `ROIC = NOPAT / average operating invested capital`.
- `ROIC = NOPAT margin × capital turnover`.
- `RONIC = ΔNOPAT / net new investment`; near-zero or negative investment returns `n.m.`.
- `Over-performance FCF = NOPAT − ΔNOPAT / fading RONIC`.
- `Continuing value = NOPAT(N+1) × (1 − g/TOCC) / (TOCC − g)` because terminal RONIC equals TOCC.
- `TOCC = risk-free rate + selected asset beta × market risk premium`.
- `APV = operating enterprise value + PV of financing effects`.
- `Equity value = APV EV − financing claims + excess cash + non-operating assets`.

## Workbook structure

The generated workbook contains 25 tabs, adding dedicated `Over-Performance` and `Liquidity` schedules and expanding the tax-shield schedule to show parallel NOL cases.

Blue font denotes user-editable inputs, black formulas, green cross-sheet links, gray historical periods, light blue forecast periods, yellow assumptions, and red/green status cells.

## Known limitations

- The included RIVN dataset and market price are illustrative and are not current investment data.
- The S&P 500 mode is a standardized screening model. It applies the three-period structure and terminal RONIC discipline, but sector beta, margin convergence, capital-turnover convergence, and financing details must be replaced by issuer-specific evidence before investment use.
- SEC XBRL tags vary materially by issuer. Production use requires issuer-specific mapping review rather than a universal zero-fill mapping.
- Peer beta and debt beta rows are illustrative until refreshed from sourced market data.
- The simplified U.S. interest limitation uses EBIT-like ATI and does not model every jurisdictional transition rule; initial NOLs require a reviewed input.
- Convertibles, option tranches, pensions, minority interests, liquidation recoveries, and future financing require security- or note-level inputs when material.
- Financial institutions are rejected by default because they require a different valuation framework.

## Troubleshooting

- `Workbook export failed`: confirm `VALUATION_NODE` and the `node_modules` symlink.
- `No offline sample data`: pass a normalized CSV containing the requested ticker.
- `terminal growth must be less than TOCC`: revise terminal growth, beta, risk-free rate, or market risk premium.
- `scenario probabilities must total 100%`: correct the YAML probabilities.
- Missing market price: pass `--market-price-override`.

## Testing

```bash
pytest -q
```

The tested sample command is:

```bash
python company_analysis.py \
  --ticker RIVN \
  --data-file sample_company_data.csv \
  --forecast-years 10 \
  --output ./output
```

Tests cover the core calculation engine, three-period APV/equity bridge, terminal RONIC lock, parallel NOL schedules, Section 163(j)-style interest limitation, scenario dilution/liquidation, model status, and an end-to-end mock-company valuation.

## Version 2 methodology update

- Separates the explicit forecast, competitive-advantage fade, and true steady state.
- Includes both over-performance-period and terminal components in PV continuing value.
- Calculates usable interest shields from cash taxes in parallel NOL schedules.
- Adds explicit cash roll-forward and minimum-liquidity checks.
- Supports scenario-specific borrowing, equity raises, new shares, and liquidation recovery.
- Applies a limited-liability floor of zero to scenario equity value.

## Example run

```bash
python app.py \
  --ticker RIVN \
  --forecast-years 10 \
  --assumptions assumptions_example.yaml \
  --output valuation_system/output
```

Review the Sources, Forecast Assumptions, Value Drivers, and Model Checks tabs before relying on any valuation output.
