import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("Usage: build_workbook.mjs model.json output.xlsx");
const model = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const tabs = [
  "Cover", "Sources", "Raw Financials", "Reclassified Financials", "Historical Analysis",
  "ROIC Tree", "Value Drivers", "Forecast Assumptions", "Forecast", "Working Capital",
  "Fixed Assets", "Free Cash Flow", "TOCC", "Debt Schedule", "Interest Tax Shield",
  "Continuing Value", "APV", "Equity Bridge", "Market Comparison", "Scenarios",
  "Sensitivities", "Model Checks", "Dashboard",
];
for (const name of tabs) workbook.worksheets.add(name);

const C = { navy: "#17365D", blue: "#1F4E78", white: "#FFFFFF", gray: "#E7E6E6", forecast: "#D9EAF7", yellow: "#FFF2CC", red: "#FCE4D6", green: "#E2F0D9", grid: "#D9E2F3", linked: "#008000", input: "#0000FF" };
const money = "$#,##0;[Red]($#,##0);-";
const perShare = "$0.00;[Red]($0.00);-";
const pct = "0.0%;[Red](0.0%);-";
const multiple = "0.0x;[Red](0.0x);-";
const count = "#,##0.0;[Red](#,##0.0);-";

function colName(index) {
  let result = "";
  for (let n = index; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + ((n - 1) % 26)) + result;
  return result;
}
function title(sheet, text, subtitle, end = "L") {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${end}1`).merge();
  sheet.getRange("A1").values = [[text]];
  sheet.getRange(`A1:${end}1`).format = { fill: C.navy, font: { color: C.white, bold: true, size: 16 }, rowHeight: 28, verticalAlignment: "center" };
  sheet.getRange(`A2:${end}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${end}2`).format = { fill: "#DCE6F1", font: { italic: true, color: "#333333" }, wrapText: true, rowHeight: 30, verticalAlignment: "center" };
}
function head(range) {
  range.format = { fill: C.blue, font: { color: C.white, bold: true }, wrapText: true, verticalAlignment: "center", borders: { preset: "inside", style: "thin", color: C.grid } };
  range.format.rowHeight = 34;
}
function body(range) {
  range.format = { font: { color: "#222222", size: 9 }, verticalAlignment: "center", borders: { insideHorizontal: { style: "thin", color: "#E7E6E6" } } };
}
function setupTable(sheet, address, headerAddress) {
  body(sheet.getRange(address));
  head(sheet.getRange(headerAddress));
  sheet.freezePanes.freezeRows(4);
}
function statusFormatting(range) {
  range.conditionalFormats.add("containsText", { text: "PASS", format: { fill: C.green, font: { color: "#006100", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "WARNING", format: { fill: C.yellow, font: { color: "#9C6500", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "FAIL", format: { fill: C.red, font: { color: "#9C0006", bold: true } } });
}

const h = model.historical;
const f = model.forecast;
const s = model.summary;
const a = model.assumptions;
const company = model.company;
const forecastEnd = colName(f.length + 1);
const histEnd = colName(h.length + 1);
const toccSelectedRow = 11 + model.tocc_peers.length;

// Cover
{
  const sh = workbook.worksheets.getItem("Cover");
  title(sh, `${model.ticker} Intrinsic Valuation`, `${company.name} | APV framework | Valuation date ${a.valuation_date} | ${company.currency} millions`, "H");
  sh.getRange("A4:B4").values = [["Adjusted Present Value and Equity Bridge", "Value"]]; head(sh.getRange("A4:B4"));
  const labels = ["PV of explicit unlevered FCF", "PV of continuing value", "Operating enterprise value", "PV of financing effects", "APV enterprise value", "Equity value", "Diluted shares", "Intrinsic value per share", "Market price", "Premium / (discount) to market", "Continuing value / APV EV", "Overall model status"];
  sh.getRange("A5:A16").values = labels.map(x => [x]);
  sh.getRange("B5:B16").formulas = [["='APV'!B5"], ["='APV'!B6"], ["='APV'!B7"], ["='APV'!B11"], ["='APV'!B12"], ["='Equity Bridge'!B12"], ["='Equity Bridge'!B13"], ["='Equity Bridge'!B14"], ["='Market Comparison'!B6"], ["='Market Comparison'!B7"], ["='APV'!B13"], ["='Model Checks'!B5"]];
  body(sh.getRange("A5:B16")); sh.getRange("B5:B16").format.font = { color: C.linked, bold: true };
  sh.getRange("B5:B10").format.numberFormat = money; sh.getRange("B11:B11").format.numberFormat = count; sh.getRange("B12:B13").format.numberFormat = perShare; sh.getRange("B14:B15").format.numberFormat = pct;
  statusFormatting(sh.getRange("B16"));
  sh.getRange("D4:H4").merge(); sh.getRange("D4").values = [["Model conventions"]]; head(sh.getRange("D4:H4"));
  sh.getRange("D5:H10").merge(true); sh.getRange("D5:D10").values = [["Operating value is discounted at TOCC."], ["Financing effects are added separately."], ["Continuing value links growth to RONIC and reinvestment."], ["Blue/yellow cells are assumptions; green formulas link sheets."], ["Market price is compared only after intrinsic value is calculated."], ["Review Sources, Value Drivers, and Model Checks before use."]];
  sh.getRange("D5:H10").format = { fill: "#F2F2F2", wrapText: true, rowHeight: 30 };
  sh.getRange("A:A").format.columnWidth = 42; sh.getRange("B:B").format.columnWidth = 20; sh.getRange("D:H").format.columnWidth = 18;
}

// Sources
{
  const sh = workbook.worksheets.getItem("Sources"); title(sh, "Sources and Provenance", "Every imported value or assumption should remain traceable", "J");
  const headers = ["Variable", "Value", "Source", "Source date", "Retrieval method", "Original unit", "Normalized unit", "User override?", "Confidence", "Notes"];
  sh.getRange("A4:J4").values = [headers];
  const rows = model.provenance.map(r => [r.variable, String(r.value ?? ""), r.source, r.source_date, r.retrieval_method, r.original_unit, r.normalized_unit, r.user_override ? "Yes" : "No", r.confidence, r.notes]);
  sh.getRange(`A5:J${4 + rows.length}`).values = rows; setupTable(sh, `A5:J${4 + rows.length}`, "A4:J4");
  sh.getRange("A:A").format.columnWidth = 30; sh.getRange("B:B").format.columnWidth = 20; sh.getRange("C:C").format.columnWidth = 62; sh.getRange("D:I").format.columnWidth = 17; sh.getRange("J:J").format.columnWidth = 60; sh.getRange(`A5:J${4 + rows.length}`).format.wrapText = true;
}

// Raw financials
{
  const sh = workbook.worksheets.getItem("Raw Financials"); title(sh, "Raw Financial Statements", "Normalized annual source values; USD millions", forecastEnd);
  sh.getRange(`A4:${histEnd}4`).values = [["Metric", ...h.map(r => r.year)]]; head(sh.getRange(`A4:${histEnd}4`));
  const metrics = [["Revenue", "revenue"], ["COGS", "cogs"], ["SG&A", "sga"], ["R&D", "rd"], ["D&A", "da"], ["EBIT", "ebit"], ["Taxes", "taxes"], ["Cash", "cash"], ["Marketable securities", "marketable_securities"], ["Receivables", "receivables"], ["Inventory", "inventory"], ["Other current operating assets", "other_current_operating_assets"], ["Net PP&E", "net_ppe"], ["Operating lease assets", "operating_lease_assets"], ["Other operating assets", "other_operating_assets"], ["Accounts payable", "accounts_payable"], ["Accrued operating liabilities", "accrued_operating_liabilities"], ["Deferred revenue", "deferred_revenue"], ["Other operating liabilities", "other_operating_liabilities"], ["Debt", "debt"], ["Lease liabilities", "lease_liabilities"], ["Equity", "equity"], ["Capital expenditures", "capex"], ["Stock-based compensation", "stock_comp"]];
  sh.getRange(`A5:${histEnd}${4 + metrics.length}`).values = metrics.map(([label, key]) => [label, ...h.map(r => r[key])]);
  body(sh.getRange(`A5:${histEnd}${4 + metrics.length}`)); sh.getRange(`B5:${histEnd}${4 + metrics.length}`).format.numberFormat = money; sh.getRange(`B5:${histEnd}${4 + metrics.length}`).format.fill = C.gray;
  sh.getRange("A:A").format.columnWidth = 34; sh.getRange(`B:${histEnd}`).format.columnWidth = 15; sh.freezePanes.freezeRows(4); sh.freezePanes.freezeColumns(1);
}

// Reclassification
{
  const sh = workbook.worksheets.getItem("Reclassified Financials"); title(sh, "Reclassified Financials", "Economic classification mapping from reported lines", "F");
  sh.getRange("A4:F4").values = [["Source line item", "Classification", "Model treatment", "Included in OWC?", "Included in invested capital?", "Notes"]];
  const rows = [["Revenue", "Operating", "Operating income", "No", "No", "Value driver"], ["Cash", "Excess / operating", "Operating cash retained; excess added in bridge", "No", "No", "Minimum cash convention"], ["Receivables", "Operating", "Operating current asset", "Yes", "Yes", ""], ["Inventory", "Operating", "Operating current asset", "Yes", "Yes", ""], ["Accounts payable", "Operating", "Operating current liability", "Yes", "Yes", ""], ["Net PP&E", "Operating", "Fixed operating asset", "No", "Yes", ""], ["Goodwill / other assets", "Potentially ambiguous", "Other operating assets", "No", "Yes", "Review acquisition history"], ["Debt", "Financing", "Equity-bridge claim", "No", "No", "Subtracted once"], ["Lease liabilities", "Financing / operating", "Equity-bridge claim", "No", "No", "Avoid double counting"], ["Interest expense", "Financing", "Tax-shield schedule only", "No", "No", "Excluded from NOPAT"]];
  sh.getRange(`A5:F${4 + rows.length}`).values = rows; setupTable(sh, `A5:F${4 + rows.length}`, "A4:F4"); sh.getRange(`A5:F${4 + rows.length}`).format.wrapText = true;
  sh.getRange("A:A").format.columnWidth = 28; sh.getRange("B:E").format.columnWidth = 22; sh.getRange("F:F").format.columnWidth = 48;
}

// Historical analysis
{
  const sh = workbook.worksheets.getItem("Historical Analysis"); title(sh, "Historical Financial Diagnosis", "Growth, profitability, capital efficiency, and free cash flow", histEnd);
  sh.getRange(`A4:${histEnd}4`).values = [["Metric", ...h.map(r => r.year)]]; head(sh.getRange(`A4:${histEnd}4`));
  const metrics = [["Revenue growth", "revenue_growth", pct], ["Gross margin", "gross_margin", pct], ["EBIT margin", "ebit_margin", pct], ["NOPAT margin", "nopat_margin", pct], ["Free cash flow margin", "fcf", money], ["Operating working capital", "owc", money], ["Receivable days", "receivable_days", "0.0"], ["Inventory days", "inventory_days", "0.0"], ["Payable days", "payable_days", "0.0"], ["Operating invested capital", "operating_invested_capital", money], ["Capital turnover", "capital_turnover", multiple], ["ROIC", "roic", pct], ["Economic profit", "economic_profit", money], ["Unlevered FCF", "fcf", money]];
  const values = metrics.map(([label, key]) => [label, ...h.map((r, i) => key === "revenue_growth" ? (i ? r.revenue / h[i - 1].revenue - 1 : null) : (key === "fcf" && label === "Free cash flow margin" ? r.fcf / r.revenue : r[key]))]);
  sh.getRange(`A5:${histEnd}${4 + metrics.length}`).values = values; body(sh.getRange(`A5:${histEnd}${4 + metrics.length}`));
  metrics.forEach((m, i) => sh.getRange(`B${5 + i}:${histEnd}${5 + i}`).format.numberFormat = m[2]);
  sh.getRange(`B5:${histEnd}${4 + metrics.length}`).format.fill = C.gray; sh.getRange("A:A").format.columnWidth = 32; sh.getRange(`B:${histEnd}`).format.columnWidth = 15; sh.freezePanes.freezeRows(4); sh.freezePanes.freezeColumns(1);
}

// ROIC tree
{
  const sh = workbook.worksheets.getItem("ROIC Tree"); title(sh, "ROIC Tree and Economic Profit", "ROIC = NOPAT margin × capital turnover", "J");
  sh.getRange("A4:J4").values = [["Year", "ROIC", "TOCC", "ROIC − TOCC", "Economic profit", "NOPAT margin", "Capital turnover", "EBIT margin", "Tax efficiency", "Value creation"]];
  const rows = h.map(r => [r.year, r.roic, r.tocc, r.roic_spread, r.economic_profit, r.nopat_margin, r.capital_turnover, r.ebit_margin, r.ebit ? r.nopat / r.ebit : null, r.roic_spread == null ? "n.m." : (r.roic_spread > 0 ? "Created value" : "Destroyed value")]);
  sh.getRange(`A5:J${4 + rows.length}`).values = rows; setupTable(sh, `A5:J${4 + rows.length}`, "A4:J4"); sh.getRange(`B5:F${4 + rows.length}`).format.numberFormat = pct; sh.getRange(`G5:G${4 + rows.length}`).format.numberFormat = multiple; sh.getRange(`H5:I${4 + rows.length}`).format.numberFormat = pct; sh.getRange("E:E").format.numberFormat = money; sh.getRange("A:A").format.columnWidth = 12; sh.getRange("B:J").format.columnWidth = 17;
  sh.getRange(`A${7 + rows.length}:J${7 + rows.length}`).merge(); sh.getRange(`A${7 + rows.length}`).values = [[model.diagnostics.join(" ") || "Historical ROIC is diagnostic evidence, not a persistence assumption."]]; sh.getRange(`A${7 + rows.length}:J${7 + rows.length}`).format = { fill: C.yellow, wrapText: true, rowHeight: 36 };
}

// Value drivers
{
  const sh = workbook.worksheets.getItem("Value Drivers"); title(sh, "Operating Story and Value Drivers", "Each forecast input is a falsifiable hypothesis", "I");
  sh.getRange("A4:I4").values = [["Variable", "Historical evidence", "Management evidence", "Industry evidence", "Comparable evidence", "Base", "Downside", "Upside", "What would falsify it?"]];
  const rows = model.value_drivers.map(r => [r.variable, r.historical_evidence, r.management_evidence, r.industry_evidence, r.comparable_evidence, r.base, r.downside, r.upside, r.falsifier]);
  sh.getRange(`A5:I${4 + rows.length}`).values = rows; setupTable(sh, `A5:I${4 + rows.length}`, "A4:I4"); sh.getRange(`A5:I${4 + rows.length}`).format.wrapText = true; sh.getRange("A:A").format.columnWidth = 24; sh.getRange("B:E").format.columnWidth = 30; sh.getRange("F:H").format.columnWidth = 15; sh.getRange("I:I").format.columnWidth = 46;
}

// Assumptions
{
  const sh = workbook.worksheets.getItem("Forecast Assumptions"); title(sh, "Forecast Assumptions", "Editable blue inputs; assumptions are hypotheses rather than facts", "D");
  sh.getRange("A4:D4").values = [["Assumption", "Value", "Units", "Notes"]];
  const rows = [["Forecast years", a.forecast_years, "years", "Explicit period"], ["Starting revenue growth", a.revenue_growth_start, "%", "Historical calibration"], ["Terminal revenue growth", a.revenue_growth_terminal, "%", "Normalized long-run growth"], ["Starting EBIT margin", a.ebit_margin_start, "%", "Historical calibration"], ["Terminal EBIT margin", a.ebit_margin_terminal, "%", "Sustainable operating hypothesis"], ["Normalized tax rate", a.tax_rate, "%", "Operating tax rate"], ["Risk-free rate", a.risk_free_rate, "%", "Currency-matched"], ["Market risk premium", a.market_risk_premium, "%", "Implied market premium"], ["Selected asset beta", a.selected_asset_beta, "beta", "Operating-risk beta"], ["TOCC", s.tocc, "%", "Risk-free + beta × MRP"], ["Terminal growth", a.terminal_growth_rate, "%", "Must be below TOCC"], ["Terminal RONIC", a.terminal_ronic, "%", "Sustainable return on new capital"], ["Operating cash", a.operating_cash_percentage, "% revenue", "Minimum liquidity convention"], ["Cash tax rate", a.cash_tax_rate, "%", "Interest tax shield"], ["Interest limitation", a.interest_limit_percentage, "% ATI", "Simplified 163(j) convention"]];
  sh.getRange(`A5:D${4 + rows.length}`).values = rows; setupTable(sh, `A5:D${4 + rows.length}`, "A4:D4"); sh.getRange(`B5:B${4 + rows.length}`).format = { fill: C.yellow, font: { color: C.input } }; sh.getRange("B6:B16").format.numberFormat = pct; sh.getRange("B13:B13").format.numberFormat = pct; sh.getRange("A:A").format.columnWidth = 32; sh.getRange("B:C").format.columnWidth = 18; sh.getRange("D:D").format.columnWidth = 48;
}

// Forecast
{
  const sh = workbook.worksheets.getItem("Forecast"); title(sh, "Explicit Operating Forecast", "Driver-based ten-year forecast; USD millions", forecastEnd);
  sh.getRange(`A4:${forecastEnd}4`).values = [["Metric", ...f.map(r => r.year)]]; head(sh.getRange(`A4:${forecastEnd}4`));
  const metrics = [["Revenue growth", "revenue_growth", pct], ["Revenue", "revenue", money], ["COGS", "cogs", money], ["Gross profit", "gross_profit", money], ["SG&A", "sga", money], ["R&D", "rd", money], ["D&A", "da", money], ["EBIT margin", "ebit_margin", pct], ["EBIT", "ebit", money], ["Operating taxes", "operating_taxes", money], ["NOPAT", "nopat", money], ["Operating invested capital", "invested_capital", money], ["Capital turnover", "capital_turnover", multiple], ["ROIC", "roic", pct], ["RONIC", "ronic", pct], ["Economic profit", "economic_profit", money]];
  sh.getRange(`A5:${forecastEnd}${4 + metrics.length}`).values = metrics.map(([label, key]) => [label, ...f.map(r => r[key])]); body(sh.getRange(`A5:${forecastEnd}${4 + metrics.length}`)); metrics.forEach((m, i) => sh.getRange(`B${5 + i}:${forecastEnd}${5 + i}`).format.numberFormat = m[2]); sh.getRange(`B5:${forecastEnd}${4 + metrics.length}`).format.fill = C.forecast; sh.getRange("A:A").format.columnWidth = 32; sh.getRange(`B:${forecastEnd}`).format.columnWidth = 14; sh.freezePanes.freezeRows(4); sh.freezePanes.freezeColumns(1);
}

// Working capital
{
  const sh = workbook.worksheets.getItem("Working Capital"); title(sh, "Operating Working Capital", "Forecast working-capital requirement and investment", forecastEnd);
  sh.getRange(`A4:${forecastEnd}4`).values = [["Metric", ...f.map(r => r.year)]]; head(sh.getRange(`A4:${forecastEnd}4`)); sh.getRange(`A5:${forecastEnd}7`).values = [["Revenue", ...f.map(r => r.revenue)], ["Operating working capital", ...f.map(r => r.owc)], ["Increase in operating working capital", ...f.map(r => r.change_owc)]]; body(sh.getRange(`A5:${forecastEnd}7`)); sh.getRange(`B5:${forecastEnd}7`).format = { fill: C.forecast, numberFormat: money }; sh.getRange("A:A").format.columnWidth = 38; sh.getRange(`B:${forecastEnd}`).format.columnWidth = 14; sh.freezePanes.freezeRows(4);
}

// Fixed assets
{
  const sh = workbook.worksheets.getItem("Fixed Assets"); title(sh, "Fixed Assets and Capital Expenditures", "PP&E requirement and roll-forward-derived capital spending", forecastEnd);
  sh.getRange(`A4:${forecastEnd}4`).values = [["Metric", ...f.map(r => r.year)]]; head(sh.getRange(`A4:${forecastEnd}4`)); sh.getRange(`A5:${forecastEnd}8`).values = [["Revenue", ...f.map(r => r.revenue)], ["Net PP&E", ...f.map(r => r.net_ppe)], ["D&A", ...f.map(r => r.da)], ["Capital expenditures", ...f.map(r => r.capex)]]; body(sh.getRange(`A5:${forecastEnd}8`)); sh.getRange(`B5:${forecastEnd}8`).format = { fill: C.forecast, numberFormat: money }; sh.getRange("A:A").format.columnWidth = 36; sh.getRange(`B:${forecastEnd}`).format.columnWidth = 14; sh.freezePanes.freezeRows(4);
}

// FCF
{
  const sh = workbook.worksheets.getItem("Free Cash Flow"); title(sh, "Unlevered Free Cash Flow", "NOPAT + D&A − capex − increase in operating working capital", forecastEnd);
  sh.getRange(`A4:${forecastEnd}4`).values = [["Metric", ...f.map(r => r.year)]]; head(sh.getRange(`A4:${forecastEnd}4`));
  sh.getRange(`A5:${forecastEnd}5`).values = [["NOPAT", ...f.map(r => r.nopat)]];
  sh.getRange(`A6:${forecastEnd}6`).values = [["D&A", ...f.map(r => r.da)]];
  sh.getRange(`A7:${forecastEnd}7`).values = [["Capital expenditures", ...f.map(r => r.capex)]];
  sh.getRange(`A8:${forecastEnd}8`).values = [["Increase in OWC", ...f.map(r => r.change_owc)]];
  sh.getRange(`A9:${forecastEnd}9`).values = [["Other operating investment", ...f.map(() => 0)]];
  for (let i = 0; i < f.length; i++) { const c = colName(i + 2); sh.getRange(`${c}10`).formulas = [[`=${c}5+${c}6-${c}7-${c}8-${c}9`]]; sh.getRange(`${c}11`).formulas = [[`=1/(1+'TOCC'!$B$${toccSelectedRow})^${i + 1}`]]; sh.getRange(`${c}12`).formulas = [[`=${c}10*${c}11`]]; }
  sh.getRange("A10:A12").values = [["Unlevered FCF"], ["Discount factor"], ["PV of FCF"]]; body(sh.getRange(`A5:${forecastEnd}12`)); sh.getRange(`B5:${forecastEnd}10`).format.numberFormat = money; sh.getRange(`B11:${forecastEnd}11`).format.numberFormat = "0.000x"; sh.getRange(`B12:${forecastEnd}12`).format.numberFormat = money; sh.getRange(`B5:${forecastEnd}12`).format.fill = C.forecast; sh.getRange(`B10:${forecastEnd}12`).format.font = { bold: true, color: "#000000" }; sh.getRange("A:A").format.columnWidth = 36; sh.getRange(`B:${forecastEnd}`).format.columnWidth = 14; sh.freezePanes.freezeRows(4);
}

// TOCC
{
  const sh = workbook.worksheets.getItem("TOCC"); title(sh, "True Opportunity Cost of Capital", "Peer asset-beta audit and selected operating-risk hurdle", "I");
  sh.getRange("A4:I4").values = [["Peer", "Equity beta", "Debt beta", "Debt", "Equity", "Tax rate", "Asset beta", "Weight", "Source"]]; const rows = model.tocc_peers.map(r => [r.peer, r.equity_beta, r.debt_beta, r.debt, r.equity, r.tax_rate, r.asset_beta, r.weight, r.source]); sh.getRange(`A5:I${4 + rows.length}`).values = rows; setupTable(sh, `A5:I${4 + rows.length}`, "A4:I4"); sh.getRange(`B5:C${4 + rows.length}`).format.numberFormat = multiple; sh.getRange(`D5:E${4 + rows.length}`).format.numberFormat = money; sh.getRange(`F5:F${4 + rows.length}`).format.numberFormat = pct; sh.getRange(`G5:G${4 + rows.length}`).format.numberFormat = multiple; sh.getRange(`H5:H${4 + rows.length}`).format.numberFormat = pct;
  const start = 7 + rows.length; sh.getRange(`A${start}:B${start + 4}`).values = [["Risk-free rate", a.risk_free_rate], ["Market risk premium", a.market_risk_premium], ["Selected asset beta", a.selected_asset_beta], ["TOCC formula", "Risk-free + asset beta × MRP"], ["Unlevered TOCC", null]]; sh.getRange(`B${start + 4}`).formulas = [[`=B${start}+B${start + 1}*B${start + 2}`]]; sh.getRange(`A${start}:B${start + 4}`).format.borders = { preset: "outside", style: "thin", color: C.blue }; sh.getRange(`B${start}:B${start + 1}`).format.numberFormat = pct; sh.getRange(`B${start + 2}`).format.numberFormat = multiple; sh.getRange(`B${start + 4}`).format.numberFormat = pct; sh.getRange(`B${start}:B${start + 2}`).format = { fill: C.yellow, font: { color: C.input } }; sh.getRange(`B${start + 4}`).format.font = { bold: true, color: "#000000" }; sh.getRange("A:A").format.columnWidth = 26; sh.getRange("B:H").format.columnWidth = 16; sh.getRange("I:I").format.columnWidth = 56;
}

// Debt schedule
{
  const sh = workbook.worksheets.getItem("Debt Schedule"); title(sh, "Debt and Financing Schedule", "Financing policy is modeled separately from operating value", forecastEnd); sh.getRange(`A4:${forecastEnd}4`).values = [["Metric", ...f.map(r => r.year)]]; head(sh.getRange(`A4:${forecastEnd}4`)); const metrics = [["Opening debt", "opening_debt", money], ["New borrowing", "new_borrowing", money], ["Mandatory repayment", "mandatory_repayment", money], ["Ending debt", "ending_debt", money], ["Average debt", "average_debt", money], ["Interest rate", "interest_rate", pct], ["Cash interest", "interest_expense", money], ["Debt / EBITDA", null, multiple], ["EBIT / interest", null, multiple], ["FCF / debt", null, pct]]; const values = metrics.map(([label, key]) => [label, ...f.map(r => key ? r[key] : null)]); sh.getRange(`A5:${forecastEnd}${4 + metrics.length}`).values = values; for (let i = 0; i < f.length; i++) { const c = colName(i + 2), r = f[i]; sh.getRange(`${c}12`).values = [[(r.ending_debt && r.ebit + r.da > 0) ? r.ending_debt / (r.ebit + r.da) : null]]; sh.getRange(`${c}13`).values = [[r.interest_expense ? r.ebit / r.interest_expense : null]]; sh.getRange(`${c}14`).values = [[r.ending_debt ? r.fcf / r.ending_debt : null]]; } body(sh.getRange(`A5:${forecastEnd}14`)); metrics.forEach((m, i) => sh.getRange(`B${5 + i}:${forecastEnd}${5 + i}`).format.numberFormat = m[2]); sh.getRange(`B5:${forecastEnd}14`).format.fill = C.forecast; sh.getRange("A:A").format.columnWidth = 32; sh.getRange(`B:${forecastEnd}`).format.columnWidth = 14; sh.freezePanes.freezeRows(4);
}

// Tax shield
{
  const sh = workbook.worksheets.getItem("Interest Tax Shield"); title(sh, "Interest Deductibility and Tax Shield", "Simplified EBIT-like ATI limitation with carryforward roll-forward", "L"); sh.getRange("A4:L4").values = [["Year", "Interest", "ATI", "30% ATI limit", "Opening carryforward", "Carryforward used", "Deductible interest", "Nondeductible current", "Ending carryforward", "Cash tax rate", "Usable tax shield", "PV tax shield"]]; const rows = model.tax_shield.map((r, i) => [r.year, r.interest, r.ati, r.limit, r.opening_carryforward, r.carryforward_used, r.deductible_interest, r.nondeductible_current, r.ending_carryforward, r.cash_tax_rate, r.usable_tax_shield, r.usable_tax_shield / (1 + (a.tax_shield_discount_rate || s.tocc)) ** (i + 1)]); sh.getRange(`A5:L${4 + rows.length}`).values = rows; setupTable(sh, `A5:L${4 + rows.length}`, "A4:L4"); sh.getRange(`B5:I${4 + rows.length}`).format.numberFormat = money; sh.getRange(`J5:J${4 + rows.length}`).format.numberFormat = pct; sh.getRange(`K5:L${4 + rows.length}`).format.numberFormat = money; sh.getRange("A:A").format.columnWidth = 12; sh.getRange("B:L").format.columnWidth = 18;
  const noteRow = 7 + rows.length; sh.getRange(`A${noteRow}:L${noteRow}`).merge(); sh.getRange(`A${noteRow}`).values = [["Display formula: Tax × min(Interest + Eligible Carryforward, 30% × ATI + Eligible Carryforward). Exact carryforward logic is calculated year by year above."]]; sh.getRange(`A${noteRow}:L${noteRow}`).format = { fill: C.yellow, wrapText: true, rowHeight: 32 };
}

// Continuing value
{
  const sh = workbook.worksheets.getItem("Continuing Value"); title(sh, "Continuing Value", "Normalized NOPAT, growth, RONIC, and reinvestment", "D"); sh.getRange("A4:B4").values = [["Input / calculation", "Value"]]; head(sh.getRange("A4:B4")); const lastFcfCol = forecastEnd; sh.getRange("A5:A13").values = [["Year N NOPAT"], ["Terminal growth"], ["Terminal RONIC"], ["TOCC"], ["NOPAT N+1"], ["Reinvestment rate"], ["Terminal FCF"], ["Continuing value at Year N"], ["PV of continuing value"]]; sh.getRange("B5").formulas = [[`='Free Cash Flow'!${lastFcfCol}5`]]; sh.getRange("B6:B8").values = [[a.terminal_growth_rate], [a.terminal_ronic], [s.tocc]]; sh.getRange("B9").formulas = [["=B5*(1+B6)"]]; sh.getRange("B10").formulas = [["=B6/B7"]]; sh.getRange("B11").formulas = [["=B9*(1-B10)"]]; sh.getRange("B12").formulas = [["=IF(OR(B6>=B8,B7<=0,B10<0,B10>1),\"\",B11/(B8-B6))"]]; sh.getRange("B13").formulas = [[`=B12/(1+B8)^${f.length}`]]; body(sh.getRange("A5:B13")); sh.getRange("B5:B5").format.numberFormat = money; sh.getRange("B6:B10").format.numberFormat = pct; sh.getRange("B11:B13").format.numberFormat = money; sh.getRange("B6:B8").format = { fill: C.yellow, font: { color: C.input } }; sh.getRange("B5:B5").format.font = { color: C.linked }; sh.getRange("A:A").format.columnWidth = 38; sh.getRange("B:B").format.columnWidth = 22; sh.getRange("D5:D10").values = [["Terminal g < TOCC"], ["RONIC positive"], ["Reinvestment 0%–100%"], ["Year N+1 NOPAT used"], ["Capex / D&A normalized"], ["Capital turnover normalized"]]; sh.getRange("D:D").format.columnWidth = 32;
}

// APV
{
  const sh = workbook.worksheets.getItem("APV"); title(sh, "Adjusted Present Value", "Operating value plus separately valued financing effects", "D"); sh.getRange("A4:B4").values = [["Adjusted Present Value and Equity Bridge", "Value"]]; head(sh.getRange("A4:B4")); sh.getRange("A5:A13").values = [["PV of explicit unlevered FCF"], ["PV of continuing value"], ["Operating enterprise value"], ["PV of explicit interest tax shields"], ["PV of continuing interest tax shield"], ["PV of other financing effects"], ["PV of financing effects"], ["APV enterprise value"], ["Continuing value / APV enterprise value"]]; sh.getRange("B5").formulas = [[`=SUM('Free Cash Flow'!B12:${forecastEnd}12)`]]; sh.getRange("B6").formulas = [["='Continuing Value'!B13"]]; sh.getRange("B7").formulas = [["=SUM(B5:B6)"]]; sh.getRange("B8").formulas = [[`=SUM('Interest Tax Shield'!L5:L${4 + model.tax_shield.length})`]]; sh.getRange("B9:B10").values = [[s.pv_continuing_tax_shield], [s.pv_other_financing_effects]]; sh.getRange("B11").formulas = [["=SUM(B8:B10)"]]; sh.getRange("B12").formulas = [["=B7+B11"]]; sh.getRange("B13").formulas = [["=IF(B12=0,\"\",B6/B12)"]]; body(sh.getRange("A5:B13")); sh.getRange("B5:B12").format.numberFormat = money; sh.getRange("B13").format.numberFormat = pct; sh.getRange("B5:B13").format.font = { color: C.linked, bold: true }; sh.getRange("A:A").format.columnWidth = 44; sh.getRange("B:B").format.columnWidth = 22;
}

// Equity bridge
{
  const sh = workbook.worksheets.getItem("Equity Bridge"); title(sh, "Enterprise Value to Equity Value", "Only excess/non-operating cash is added", "D"); sh.getRange("A4:B4").values = [["Equity bridge", "Value"]]; head(sh.getRange("A4:B4")); sh.getRange("A5:A14").values = [["APV enterprise value"], ["Less: gross debt"], ["Less: operating lease liabilities / other claims"], ["Less: pension, preferred, and minority claims"], ["Add: excess cash and marketable securities"], ["Add: non-operating investments"], ["Other non-operating adjustments"], ["Equity value"], ["Diluted shares"], ["Intrinsic value per share"]]; sh.getRange("B5").formulas = [["='APV'!B12"]]; sh.getRange("B6:B11").values = [[s.gross_debt], [company.historical[company.historical.length - 1].lease_liabilities], [Math.max(0, s.other_financing_claims - company.historical[company.historical.length - 1].lease_liabilities)], [s.excess_cash], [company.non_operating_investments], [0]]; sh.getRange("B12").formulas = [["=B5-B6-B7-B8+B9+B10+B11"]]; sh.getRange("B13").values = [[s.diluted_shares]]; sh.getRange("B14").formulas = [["=IF(B13=0,\"\",B12/B13)"]]; body(sh.getRange("A5:B14")); sh.getRange("B5:B12").format.numberFormat = money; sh.getRange("B13").format.numberFormat = count; sh.getRange("B14").format.numberFormat = perShare; sh.getRange("B5:B5").format.font = { color: C.linked }; sh.getRange("B12:B14").format.font = { bold: true, color: "#000000" }; sh.getRange("A:A").format.columnWidth = 52; sh.getRange("B:B").format.columnWidth = 22;
}

// Market comparison
{
  const sh = workbook.worksheets.getItem("Market Comparison"); title(sh, "Intrinsic Value versus Market Price", "Market price is not an input to intrinsic operating value", "D"); sh.getRange("A4:B4").values = [["Metric", "Value"]]; head(sh.getRange("A4:B4")); sh.getRange("A5:A10").values = [["Intrinsic value per share"], ["Market price"], ["Premium / (discount) to market"], ["Market-implied equity value"], ["Intrinsic equity value"], ["Dollar difference per share"]]; sh.getRange("B5").formulas = [["='Equity Bridge'!B14"]]; sh.getRange("B6").values = [[s.market_price]]; sh.getRange("B7").formulas = [["=IF(B6=0,\"\",B5/B6-1)"]]; sh.getRange("B8").formulas = [["=B6*'Equity Bridge'!B13"]]; sh.getRange("B9").formulas = [["='Equity Bridge'!B12"]]; sh.getRange("B10").formulas = [["=B5-B6"]]; body(sh.getRange("A5:B10")); sh.getRange("B5:B6").format.numberFormat = perShare; sh.getRange("B7").format.numberFormat = pct; sh.getRange("B8:B9").format.numberFormat = money; sh.getRange("B10").format.numberFormat = perShare; sh.getRange("B5:B5").format.font = { color: C.linked }; sh.getRange("A:A").format.columnWidth = 42; sh.getRange("B:B").format.columnWidth = 22;
}

// Scenarios
{
  const sh = workbook.worksheets.getItem("Scenarios"); title(sh, "Downside / Base / Upside Scenarios", "Coherent operating hypotheses with probability-weighted value", "F"); sh.getRange("A4:F4").values = [["Scenario", "Probability", "TOCC", "Terminal growth", "Intrinsic value / share", "Probability-weighted value"]]; const rows = model.scenarios.map(r => [r.scenario, r.probability, r.tocc, r.terminal_growth, r.intrinsic_value_per_share, r.probability * r.intrinsic_value_per_share]); sh.getRange(`A5:F${4 + rows.length}`).values = rows; setupTable(sh, `A5:F${4 + rows.length}`, "A4:F4"); sh.getRange(`B5:D${4 + rows.length}`).format.numberFormat = pct; sh.getRange(`E5:F${4 + rows.length}`).format.numberFormat = perShare; const total = 6 + rows.length; sh.getRange(`A${total}:B${total}`).values = [["Probability total", null]]; sh.getRange(`B${total}`).formulas = [[`=SUM(B5:B${4 + rows.length})`]]; sh.getRange(`D${total}:E${total}`).values = [["Expected intrinsic value", null]]; sh.getRange(`E${total}`).formulas = [[`=SUM(F5:F${4 + rows.length})`]]; sh.getRange(`B${total}`).format.numberFormat = pct; sh.getRange(`E${total}`).format.numberFormat = perShare; sh.getRange("A:F").format.columnWidth = 22;
}

// Sensitivities
{
  const sh = workbook.worksheets.getItem("Sensitivities"); title(sh, "Valuation Sensitivities", "TOCC versus terminal growth; values are intrinsic value per share", "H"); const source = model.sensitivities.tocc_vs_growth; const toccs = [...new Set(source.map(r => r.tocc))].sort((x, y) => x - y); const gs = [...new Set(source.map(r => r.terminal_growth))].sort((x, y) => x - y); sh.getRange(`A4:${colName(gs.length + 1)}4`).values = [["TOCC / g", ...gs]]; head(sh.getRange(`A4:${colName(gs.length + 1)}4`)); const matrix = toccs.map(t => [t, ...gs.map(g => source.find(r => Math.abs(r.tocc - t) < 1e-10 && Math.abs(r.terminal_growth - g) < 1e-10)?.value_per_share ?? null)]); sh.getRange(`A5:${colName(gs.length + 1)}${4 + toccs.length}`).values = matrix; body(sh.getRange(`A5:${colName(gs.length + 1)}${4 + toccs.length}`)); sh.getRange(`A5:A${4 + toccs.length}`).format.numberFormat = pct; sh.getRange(`B4:${colName(gs.length + 1)}4`).format.numberFormat = pct; sh.getRange(`B5:${colName(gs.length + 1)}${4 + toccs.length}`).format.numberFormat = perShare; sh.getRange(`B5:${colName(gs.length + 1)}${4 + toccs.length}`).conditionalFormats.add("colorScale", { colors: ["#F8696B", "#FFEB84", "#63BE7B"], thresholds: ["min", "50%", "max"] }); sh.getRange("A:H").format.columnWidth = 16;
}

// Model checks
{
  const sh = workbook.worksheets.getItem("Model Checks"); title(sh, "Model Checks", "Every check returns PASS, WARNING, or FAIL", "H"); sh.getRange("A4:G4").values = [["Category", "Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]]; const rows = model.checks.map(r => [r.category, r.name, String(r.actual ?? ""), String(r.expected ?? ""), String(r.difference ?? ""), String(r.tolerance ?? ""), r.status]); sh.getRange(`A6:G${5 + rows.length}`).values = rows; setupTable(sh, `A6:G${5 + rows.length}`, "A4:G4"); sh.getRange("A5:B5").values = [["Overall model status", null]]; sh.getRange("B5").values = [[s.overall_model_status]]; sh.getRange("A5:B5").format = { fill: C.navy, font: { color: C.white, bold: true } }; statusFormatting(sh.getRange("B5")); statusFormatting(sh.getRange(`G6:G${5 + rows.length}`)); sh.getRange("A:A").format.columnWidth = 22; sh.getRange("B:B").format.columnWidth = 48; sh.getRange("C:G").format.columnWidth = 17;
}

// Dashboard
{
  const sh = workbook.worksheets.getItem("Dashboard"); title(sh, `${model.ticker} Valuation Dashboard`, "Historical diagnosis, forecast trajectory, and valuation bridge", "P");
  sh.getRange("A4:D4").values = [["KPI", "Value", "KPI", "Value"]]; head(sh.getRange("A4:D4")); sh.getRange("A5:D9").values = [["Intrinsic value / share", s.intrinsic_value_per_share, "Market price", s.market_price], ["Premium / (discount)", s.premium_discount, "TOCC", s.tocc], ["APV enterprise value", s.apv_enterprise_value, "Equity value", s.equity_value], ["PV continuing value / APV", s.continuing_value_share, "Terminal RONIC", s.terminal_ronic], ["Overall status", s.overall_model_status, "Forecast years", f.length]]; body(sh.getRange("A5:D9")); sh.getRange("B5:D9").format.font = { bold: true }; sh.getRange("B5:D5").format.numberFormat = perShare; sh.getRange("B6:D6").format.numberFormat = pct; sh.getRange("B7:D7").format.numberFormat = money; sh.getRange("B8:D8").format.numberFormat = pct; statusFormatting(sh.getRange("B9"));
  const combined = [...h.map(r => ({ year: r.year, revenue: r.revenue, margin: r.ebit_margin, roic: r.roic, tocc: r.tocc, fcf: r.fcf })), ...f.map(r => ({ year: r.year, revenue: r.revenue, margin: r.ebit_margin, roic: r.roic, tocc: s.tocc, fcf: r.fcf }))];
  sh.getRange(`A12:F${12 + combined.length}`).values = [["Year", "Revenue", "EBIT margin", "ROIC", "TOCC", "FCF"], ...combined.map(r => [String(r.year), r.revenue, r.margin, r.roic, r.tocc, r.fcf])]; head(sh.getRange("A12:F12")); body(sh.getRange(`A13:F${12 + combined.length}`)); sh.getRange(`B13:B${12 + combined.length}`).format.numberFormat = money; sh.getRange(`C13:E${12 + combined.length}`).format.numberFormat = pct; sh.getRange(`F13:F${12 + combined.length}`).format.numberFormat = money;
  const c1 = sh.charts.add("line", sh.getRange(`A12:B${12 + combined.length}`)); c1.title = "Revenue ($mm)"; c1.hasLegend = false; c1.yAxis = { numberFormatCode: "$#,##0" }; c1.setPosition("F4", "K16");
  const lastChartRow = 12 + combined.length;
  const c2 = sh.charts.add("line", { chartType: "line", title: "EBIT margin", hasLegend: false }); const c2s = c2.series.add("EBIT margin"); c2s.categoryFormula = `'Dashboard'!$A$13:$A$${lastChartRow}`; c2s.formula = `'Dashboard'!$C$13:$C$${lastChartRow}`; c2.yAxis = { numberFormatCode: "0.0%" }; c2.setPosition("L4", "Q16");
  const c3 = sh.charts.add("line", { chartType: "line", title: "ROIC versus TOCC", hasLegend: true }); const c3a = c3.series.add("ROIC"); c3a.categoryFormula = `'Dashboard'!$A$13:$A$${lastChartRow}`; c3a.formula = `'Dashboard'!$D$13:$D$${lastChartRow}`; const c3b = c3.series.add("TOCC"); c3b.categoryFormula = `'Dashboard'!$A$13:$A$${lastChartRow}`; c3b.formula = `'Dashboard'!$E$13:$E$${lastChartRow}`; c3.yAxis = { numberFormatCode: "0.0%" }; c3.setPosition("F18", "K30");
  const c4 = sh.charts.add("line", { chartType: "line", title: "Unlevered FCF ($mm)", hasLegend: false }); const c4s = c4.series.add("FCF"); c4s.categoryFormula = `'Dashboard'!$A$13:$A$${lastChartRow}`; c4s.formula = `'Dashboard'!$F$13:$F$${lastChartRow}`; c4.yAxis = { numberFormatCode: "$#,##0" }; c4.setPosition("L18", "Q30");
  const bridgeRow = 15 + combined.length; sh.getRange(`A${bridgeRow}:B${bridgeRow + 4}`).values = [["Bridge item", "Value"], ["Operating EV", s.operating_enterprise_value], ["Financing effects", s.pv_financing_effects], ["Net debt / claims", -(s.gross_debt + s.other_financing_claims - s.excess_cash)], ["Equity value", s.equity_value]]; head(sh.getRange(`A${bridgeRow}:B${bridgeRow}`)); sh.getRange(`B${bridgeRow + 1}:B${bridgeRow + 4}`).format.numberFormat = money; const c5 = sh.charts.add("waterfall", sh.getRange(`A${bridgeRow}:B${bridgeRow + 4}`)); c5.title = "Valuation bridge ($mm)"; c5.hasLegend = false; c5.setPosition("F32", "Q47");
  sh.getRange("A:A").format.columnWidth = 24; sh.getRange("B:F").format.columnWidth = 16;
}

const previewDir = path.join(path.dirname(outputPath), `${model.ticker}_previews`);
await fs.mkdir(previewDir, { recursive: true });
for (const name of tabs) {
  const renderOptions = name === "Dashboard" ? { sheetName: name, range: "A1:Q47", scale: 0.8, format: "png" } : { sheetName: name, autoCrop: "all", scale: 0.75, format: "png" };
  const preview = await workbook.render(renderOptions);
  await fs.writeFile(path.join(previewDir, `${name.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log((await workbook.inspect({ kind: "table", sheetId: "APV", range: "A1:B13", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 4, maxChars: 5000 })).ndjson);
console.log((await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" })).ndjson);
console.log((await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 })).ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Saved ${outputPath}`);
