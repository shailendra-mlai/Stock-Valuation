import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("Usage: build_sp500_workbook.mjs input.json output.xlsx preview_dir");
}

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const rows = payload.rows;
const summary = payload.summary;
const workbook = Workbook.create();
const sheetNames = ["Summary", "Sector Summary", "Assumptions", "Methodology", "Sources", "Checks"];
for (const name of sheetNames) workbook.worksheets.add(name);

const C = {
  navy: "#17365D", blue: "#1F4E78", cyan: "#D9EAF7", gray: "#E7E6E6",
  yellow: "#FFF2CC", red: "#FCE4D6", green: "#E2F0D9", white: "#FFFFFF",
  ink: "#1F1F1F", grid: "#D9E2F3", inputBlue: "#0000FF", linkGreen: "#008000",
};
const moneyFmt = "$#,##0;[Red]($#,##0);-";
const perShareFmt = "$0.00;[Red]($0.00);-";
const pctFmt = "0.0%;[Red](0.0%);-";
const countFmt = "#,##0.0;[Red](#,##0.0);-";

function title(sheet, text, subtitle, endCol = "P") {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${endCol}1`).merge();
  sheet.getRange("A1").values = [[text]];
  sheet.getRange(`A1:${endCol}1`).format = {
    fill: C.navy, font: { color: C.white, bold: true, size: 16 }, rowHeight: 28,
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${endCol}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endCol}2`).format = {
    fill: "#DCE6F1", font: { color: C.ink, italic: true, size: 10 },
    wrapText: true, rowHeight: 32, verticalAlignment: "center",
  };
}

function header(range) {
  range.format = {
    fill: C.blue, font: { color: C.white, bold: true }, wrapText: true,
    verticalAlignment: "center", borders: { preset: "inside", style: "thin", color: C.grid },
  };
  range.format.rowHeight = 42;
}

function body(range) {
  range.format = {
    font: { color: C.ink, size: 9 },
    borders: { insideHorizontal: { style: "thin", color: "#E7E6E6" } },
    verticalAlignment: "center",
  };
}

const summarySheet = workbook.worksheets.getItem("Summary");
title(
  summarySheet,
  "S&P 500 Standardized APV Valuation Summary",
  `As of ${summary.as_of} | ${summary.constituent_count} index share classes | USD millions except per-share data | Financials are intentionally not valued under the operating-company framework`,
  "AC",
);
const headers = [
  "Ticker", "Company", "GICS Sector", "Status", "Unlevered TOCC", "Terminal growth",
  "PV explicit FCF ($mm)", "PV continuing value ($mm)", "Operating enterprise value ($mm)",
  "PV financing effects ($mm)", "APV enterprise value ($mm)", "Equity value ($mm)",
  "Intrinsic value / share", "Market price", "Premium / (discount)", "PV continuing value / APV EV",
  "Notes", "Latest revenue ($mm)", "Latest EBIT ($mm)", "Operating invested capital ($mm)",
  "Excess cash ($mm)", "Gross debt ($mm)", "Other financing claims ($mm)", "Diluted shares (mm)",
  "Terminal RONIC", "Forecast start growth", "Terminal EBIT margin", "Financial statement period", "Market source date",
];
summarySheet.getRange("A4:AC4").values = [headers];
header(summarySheet.getRange("A4:AC4"));
const firstRow = 5;
const lastRow = firstRow + rows.length - 1;
const values = rows.map((r) => [
  r.ticker, r.company, r.sector, r.status, r.unlevered_tocc, r.terminal_growth,
  r.pv_explicit_fcf, r.pv_continuing_value, null, r.pv_financing_effects, null, null,
  null, r.market_price, null, null, r.notes, r.latest_revenue, r.latest_ebit,
  r.latest_operating_invested_capital, r.excess_cash, r.gross_debt, r.other_financing_claims,
  r.diluted_shares, r.terminal_ronic, r.forecast_start_growth, r.terminal_ebit_margin,
  r.source_period, r.market_source_date,
]);
summarySheet.getRange(`A${firstRow}:AC${lastRow}`).values = values;
const formulas = rows.map((r, i) => {
  const n = firstRow + i;
  return [
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),G${n}+H${n},"")`,
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),I${n}+J${n},"")`,
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),K${n}-V${n}-W${n}+U${n},"")`,
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),L${n}/X${n},"")`,
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),M${n}/N${n}-1,"")`,
    `=IF(OR(D${n}="PASS",D${n}="WARNING"),H${n}/K${n},"")`,
  ];
});
for (let i = 0; i < rows.length; i++) {
  const n = firstRow + i;
  summarySheet.getRange(`I${n}`).formulas = [[formulas[i][0]]];
  summarySheet.getRange(`K${n}:M${n}`).formulas = [[formulas[i][1], formulas[i][2], formulas[i][3]]];
  summarySheet.getRange(`O${n}:P${n}`).formulas = [[formulas[i][4], formulas[i][5]]];
}
body(summarySheet.getRange(`A${firstRow}:AC${lastRow}`));
summarySheet.getRange(`E${firstRow}:F${lastRow}`).format.numberFormat = pctFmt;
summarySheet.getRange(`G${firstRow}:L${lastRow}`).format.numberFormat = moneyFmt;
summarySheet.getRange(`M${firstRow}:N${lastRow}`).format.numberFormat = perShareFmt;
summarySheet.getRange(`O${firstRow}:P${lastRow}`).format.numberFormat = pctFmt;
summarySheet.getRange(`R${firstRow}:W${lastRow}`).format.numberFormat = moneyFmt;
summarySheet.getRange(`X${firstRow}:X${lastRow}`).format.numberFormat = countFmt;
summarySheet.getRange(`Y${firstRow}:AA${lastRow}`).format.numberFormat = pctFmt;
summarySheet.getRange(`A${firstRow}:H${lastRow}`).format.font = { color: C.linkGreen, size: 9 };
summarySheet.getRange(`J${firstRow}:J${lastRow}`).format.font = { color: C.linkGreen, size: 9 };
summarySheet.getRange(`N${firstRow}:AC${lastRow}`).format.font = { color: C.linkGreen, size: 9 };
summarySheet.getRange(`I${firstRow}:I${lastRow}`).format.font = { color: "#000000", size: 9 };
summarySheet.getRange(`K${firstRow}:M${lastRow}`).format.font = { color: "#000000", size: 9 };
summarySheet.getRange(`O${firstRow}:P${lastRow}`).format.font = { color: "#000000", size: 9 };
summarySheet.getRange(`D${firstRow}:D${lastRow}`).conditionalFormats.add("containsText", { text: "PASS", format: { fill: C.green, font: { color: "#006100", bold: true } } });
summarySheet.getRange(`D${firstRow}:D${lastRow}`).conditionalFormats.add("containsText", { text: "WARNING", format: { fill: C.yellow, font: { color: "#9C6500", bold: true } } });
summarySheet.getRange(`D${firstRow}:D${lastRow}`).conditionalFormats.add("containsText", { text: "FAIL", format: { fill: C.red, font: { color: "#9C0006", bold: true } } });
summarySheet.getRange(`D${firstRow}:D${lastRow}`).conditionalFormats.add("containsText", { text: "FINANCIAL", format: { fill: C.gray, font: { color: "#666666", italic: true } } });
summarySheet.getRange(`O${firstRow}:O${lastRow}`).conditionalFormats.add("colorScale", { colors: ["#F8696B", "#FFEB84", "#63BE7B"], thresholds: ["min", "50%", "max"] });
summarySheet.freezePanes.freezeRows(4);
summarySheet.freezePanes.freezeColumns(2);
summarySheet.getRange("A:A").format.columnWidth = 11;
summarySheet.getRange("B:B").format.columnWidth = 28;
summarySheet.getRange("C:C").format.columnWidth = 22;
summarySheet.getRange("D:D").format.columnWidth = 19;
summarySheet.getRange("E:P").format.columnWidth = 16;
summarySheet.getRange("Q:Q").format.columnWidth = 48;
summarySheet.getRange("R:AC").format.columnWidth = 16;
summarySheet.getRange(`Q${firstRow}:Q${lastRow}`).format.wrapText = true;
const summaryTable = summarySheet.tables.add(`A4:AC${lastRow}`, true, "SP500ValuationSummary");
summaryTable.style = "TableStyleMedium2";
summaryTable.showFilterButton = true;

const sectorSheet = workbook.worksheets.getItem("Sector Summary");
title(sectorSheet, "Sector Summary", "Coverage and median valuation outputs by GICS sector", "J");
const sectors = [...new Set(rows.map((r) => r.sector))].sort();
const sectorHeaders = ["Sector", "Constituents", "Valued", "PASS", "WARNING", "Not valued / failed", "Median TOCC", "Median premium / (discount)", "Median CV / APV EV"];
sectorSheet.getRange("A4:I4").values = [sectorHeaders];
header(sectorSheet.getRange("A4:I4"));
const sectorRows = sectors.map((sector) => {
  const group = rows.filter((r) => r.sector === sector);
  const valued = group.filter((r) => ["PASS", "WARNING"].includes(r.status));
  const med = (key) => {
    const vals = valued.map((r) => r[key]).filter((v) => typeof v === "number" && Number.isFinite(v)).sort((a, b) => a - b);
    if (!vals.length) return null;
    const m = Math.floor(vals.length / 2);
    return vals.length % 2 ? vals[m] : (vals[m - 1] + vals[m]) / 2;
  };
  return [
    sector, group.length, valued.length, group.filter((r) => r.status === "PASS").length,
    group.filter((r) => r.status === "WARNING").length, group.length - valued.length,
    med("unlevered_tocc"), med("premium_discount"), med("pv_continuing_value_to_apv_ev"),
  ];
});
sectorSheet.getRange(`A5:I${4 + sectorRows.length}`).values = sectorRows;
body(sectorSheet.getRange(`A5:I${4 + sectorRows.length}`));
sectorSheet.getRange(`G5:I${4 + sectorRows.length}`).format.numberFormat = pctFmt;
sectorSheet.getRange("A:A").format.columnWidth = 25;
sectorSheet.getRange("B:F").format.columnWidth = 15;
sectorSheet.getRange("G:I").format.columnWidth = 19;
sectorSheet.freezePanes.freezeRows(4);
const coverageChart = sectorSheet.charts.add("bar", sectorSheet.getRange(`A4:C${4 + sectorRows.length}`));
coverageChart.title = "S&P 500 valuation coverage by sector";
coverageChart.hasLegend = true;
coverageChart.xAxis = { axisType: "textAxis" };
coverageChart.yAxis = { numberFormatCode: "#,##0" };
coverageChart.setPosition("K4", "S22");

const assumptionsSheet = workbook.worksheets.getItem("Assumptions");
title(assumptionsSheet, "Standardized Screening Assumptions", "Editable hypotheses used consistently across the batch; issuer-specific underwriting should replace them for investment decisions", "G");
assumptionsSheet.getRange("A4:D4").values = [["Input", "Value", "Units", "Rationale / source"]];
header(assumptionsSheet.getRange("A4:D4"));
const assumptionRows = [
  ["Risk-free rate", summary.risk_free_rate, "%", "USD long-duration risk-free rate; Damodaran July 2026 input"],
  ["Market risk premium", summary.market_risk_premium, "%", "Implied U.S. ERP; Damodaran July 2026"],
  ["Forecast years", summary.forecast_years, "years", "Explicit convergence period"],
  ["Operating cash", 0.02, "% of revenue", "Minimum operating liquidity convention"],
  ["Interest deductibility limit", 0.30, "% of EBIT-like ATI", "Simplified U.S. Section 163(j) convention"],
];
assumptionsSheet.getRange("A5:D9").values = assumptionRows;
assumptionsSheet.getRange("A11:D11").values = [["GICS Sector", "Unlevered beta", "Terminal RONIC", "Terminal growth"]];
header(assumptionsSheet.getRange("A11:D11"));
const sectorAssumptions = Object.keys(payload.sector_beta).sort().map((sector) => [
  sector, payload.sector_beta[sector], payload.sector_ronic[sector],
  ["Energy", "Materials", "Real Estate", "Utilities"].includes(sector) ? 0.02 : 0.025,
]);
assumptionsSheet.getRange(`A12:D${11 + sectorAssumptions.length}`).values = sectorAssumptions;
body(assumptionsSheet.getRange("A5:D9"));
body(assumptionsSheet.getRange(`A12:D${11 + sectorAssumptions.length}`));
assumptionsSheet.getRange("B5:B9").format = { fill: C.yellow, font: { color: C.inputBlue } };
assumptionsSheet.getRange(`B12:D${11 + sectorAssumptions.length}`).format = { fill: C.yellow, font: { color: C.inputBlue } };
assumptionsSheet.getRange("B5:B6").format.numberFormat = pctFmt;
assumptionsSheet.getRange("B8:B9").format.numberFormat = pctFmt;
assumptionsSheet.getRange(`B12:B${11 + sectorAssumptions.length}`).format.numberFormat = "0.00x";
assumptionsSheet.getRange(`C12:D${11 + sectorAssumptions.length}`).format.numberFormat = pctFmt;
assumptionsSheet.getRange("A:A").format.columnWidth = 30;
assumptionsSheet.getRange("B:C").format.columnWidth = 18;
assumptionsSheet.getRange("D:D").format.columnWidth = 64;
assumptionsSheet.freezePanes.freezeRows(4);

const methodSheet = workbook.worksheets.getItem("Methodology");
title(methodSheet, "APV Screening Methodology", "Economic logic, calculation sequence, and limitations", "F");
methodSheet.getRange("A4:C4").values = [["Step", "Calculation", "Implementation"]];
header(methodSheet.getRange("A4:C4"));
const methodology = [
  ["1. Scope", "Nonfinancial S&P 500 operating companies", "Financials are excluded rather than forced into an inappropriate invested-capital framework."],
  ["2. Historical diagnosis", "Revenue growth, EBIT margin, and operating invested capital", "Four annual Nasdaq periods; no TTM/fiscal-year mixing."],
  ["3. Operating capital", "Operating current assets − operating current liabilities + long operating assets", "Cash, marketable securities, and debt are excluded from operating capital."],
  ["4. Forecast", "Driver-based revenue, EBIT margin, and capital turnover convergence", "Ten years; historical company evidence converges toward sector medians."],
  ["5. NOPAT", "EBIT × (1 − normalized tax rate)", "Negative EBIT is not tax-affected until explicit NOL evidence exists."],
  ["6. Unlevered FCF", "NOPAT − net new operating investment", "Equivalent invested-capital formulation avoids treating EBITDA as cash flow."],
  ["7. TOCC", "Risk-free rate + sector unlevered beta × implied ERP", "Operating-risk hurdle; independent of the company funding rate."],
  ["8. Continuing value", "NOPAT(N+1) × (1 − g/RONIC) ÷ (TOCC − g)", "Requires positive terminal NOPAT, g < TOCC, and reinvestment rate between 0% and 100%."],
  ["9. Financing effects", "PV of usable interest tax shields", "Interest is capped at 30% of EBIT-like ATI; no unsupported continuing tax shield."],
  ["10. Equity bridge", "APV EV − debt − minority claims + excess cash", "Operating cash equal to 2% of revenue is retained in enterprise value."],
  ["11. Market comparison", "Intrinsic value / market price − 1", "Price is compared only after intrinsic value is calculated."],
  ["12. Interpretation", "Screen, not investment recommendation", "Company-specific disclosures, segments, leases, pensions, options, and tax attributes require deeper underwriting."],
];
methodSheet.getRange(`A5:C${4 + methodology.length}`).values = methodology;
body(methodSheet.getRange(`A5:C${4 + methodology.length}`));
methodSheet.getRange(`A5:C${4 + methodology.length}`).format.wrapText = true;
methodSheet.getRange("A:A").format.columnWidth = 24;
methodSheet.getRange("B:B").format.columnWidth = 42;
methodSheet.getRange("C:C").format.columnWidth = 82;
methodSheet.getRange(`A5:C${4 + methodology.length}`).format.rowHeight = 42;
methodSheet.freezePanes.freezeRows(4);

const sourcesSheet = workbook.worksheets.getItem("Sources");
title(sourcesSheet, "Sources and Provenance", "Public source hierarchy and retrieval conventions", "H");
sourcesSheet.getRange("A4:H4").values = [["Variable", "Source", "Source date", "Retrieval method", "Original unit", "Normalized unit", "Confidence", "Notes"]];
header(sourcesSheet.getRange("A4:H4"));
const sourceRows = [
  ["S&P 500 constituents", summary.constituent_source, summary.as_of, "HTML constituent table", "Ticker / text", "Ticker / text", "High", "503 share classes; multiple share classes can represent one issuer."],
  ["Annual financial statements", summary.financial_source, summary.as_of, "Nasdaq JSON API", "USD thousands", "USD millions", "Medium", "Four annual periods. Issuer-specific filing review is required for final underwriting."],
  ["Market price and capitalization", summary.market_source, summary.as_of, "Nasdaq JSON API", "USD/share and USD", "USD/share and USD millions", "Medium", "Previous-close convention; retrieved on the listed date."],
  ["Risk-free rate and implied ERP", summary.risk_source, "2026-07-01", "Published valuation dataset", "%", "%", "High", "4.45% risk-free rate and 4.18% implied U.S. ERP."],
  ["Sector unlevered beta", "Standardized screening assumption", summary.as_of, "GICS sector mapping", "Beta", "Beta", "Low", "Replace with reviewed comparable-company asset betas for company-specific valuation."],
  ["Terminal growth / RONIC", "Standardized screening assumption", summary.as_of, "Sector mapping", "%", "%", "Low", "Economic hypotheses, not market observations."],
];
sourcesSheet.getRange(`A5:H${4 + sourceRows.length}`).values = sourceRows;
body(sourcesSheet.getRange(`A5:H${4 + sourceRows.length}`));
sourcesSheet.getRange(`A5:H${4 + sourceRows.length}`).format.wrapText = true;
sourcesSheet.getRange("A:A").format.columnWidth = 30;
sourcesSheet.getRange("B:B").format.columnWidth = 72;
sourcesSheet.getRange("C:G").format.columnWidth = 18;
sourcesSheet.getRange("H:H").format.columnWidth = 72;
sourcesSheet.getRange(`A5:H${4 + sourceRows.length}`).format.rowHeight = 48;
sourcesSheet.freezePanes.freezeRows(4);

const checksSheet = workbook.worksheets.getItem("Checks");
title(checksSheet, "Batch Model Checks", "Coverage, valuation logic, and reconciliation controls", "H");
checksSheet.getRange("A4:G4").values = [["Category", "Check", "Actual", "Expected", "Difference", "Status", "Notes"]];
header(checksSheet.getRange("A4:G4"));
const valuedRows = rows.filter((r) => ["PASS", "WARNING"].includes(r.status));
const countBadTerminal = valuedRows.filter((r) => !(r.terminal_growth < r.unlevered_tocc)).length;
const countBadReinvest = valuedRows.filter((r) => !(r.terminal_growth / r.terminal_ronic >= 0 && r.terminal_growth / r.terminal_ronic <= 1)).length;
const countBadBridge = valuedRows.filter((r) => Math.abs((r.apv_enterprise_value - r.gross_debt - (r.other_financing_claims || 0) + r.excess_cash) - r.equity_value) > 0.01).length;
const countBadApv = valuedRows.filter((r) => Math.abs((r.operating_enterprise_value + r.pv_financing_effects) - r.apv_enterprise_value) > 0.01).length;
const checks = [
  ["Data", "Constituent rows loaded", rows.length, summary.constituent_count, rows.length - summary.constituent_count, rows.length === summary.constituent_count ? "PASS" : "FAIL", "Index can contain more than 500 share classes."],
  ["Data", "Companies successfully valued", valuedRows.length, "> 0", "", valuedRows.length > 0 ? "PASS" : "FAIL", "Financials are excluded by design."],
  ["Data", "Provider collection failures", payload.collection_failures.length, 0, payload.collection_failures.length, payload.collection_failures.length === 0 ? "PASS" : "WARNING", "Failed rows remain visible; no value was fabricated."],
  ["Continuing value", "Terminal growth below TOCC", countBadTerminal, 0, countBadTerminal, countBadTerminal === 0 ? "PASS" : "FAIL", "Required for every valued company."],
  ["Continuing value", "Terminal reinvestment rate between 0% and 100%", countBadReinvest, 0, countBadReinvest, countBadReinvest === 0 ? "PASS" : "FAIL", "g / RONIC constraint."],
  ["APV", "APV enterprise value reconciliation failures", countBadApv, 0, countBadApv, countBadApv === 0 ? "PASS" : "FAIL", "Operating EV + financing effects = APV EV."],
  ["Equity bridge", "Equity bridge reconciliation failures", countBadBridge, 0, countBadBridge, countBadBridge === 0 ? "PASS" : "FAIL", "APV EV − claims + excess cash = equity value."],
  ["Sector", "Financial companies valued under standard framework", rows.filter((r) => r.sector === "Financials" && ["PASS", "WARNING"].includes(r.status)).length, 0, 0, rows.some((r) => r.sector === "Financials" && ["PASS", "WARNING"].includes(r.status)) ? "FAIL" : "PASS", "Financial institutions require a sector-specific framework."],
];
checksSheet.getRange(`A5:G${4 + checks.length}`).values = checks;
body(checksSheet.getRange(`A5:G${4 + checks.length}`));
checksSheet.getRange(`F5:F${4 + checks.length}`).conditionalFormats.add("containsText", { text: "PASS", format: { fill: C.green, font: { color: "#006100", bold: true } } });
checksSheet.getRange(`F5:F${4 + checks.length}`).conditionalFormats.add("containsText", { text: "WARNING", format: { fill: C.yellow, font: { color: "#9C6500", bold: true } } });
checksSheet.getRange(`F5:F${4 + checks.length}`).conditionalFormats.add("containsText", { text: "FAIL", format: { fill: C.red, font: { color: "#9C0006", bold: true } } });
checksSheet.getRange("A:A").format.columnWidth = 22;
checksSheet.getRange("B:B").format.columnWidth = 46;
checksSheet.getRange("C:F").format.columnWidth = 16;
checksSheet.getRange("G:G").format.columnWidth = 64;
checksSheet.getRange(`G5:G${4 + checks.length}`).format.wrapText = true;
checksSheet.freezePanes.freezeRows(4);

await fs.mkdir(previewDir, { recursive: true });
for (const name of sheetNames) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: name === "Summary" ? 0.55 : 1, format: "png" });
  await fs.writeFile(`${previewDir}/${name.replaceAll(" ", "_")}.png`, new Uint8Array(await preview.arrayBuffer()));
}

const inspectSummary = await workbook.inspect({ kind: "table", sheetId: "Summary", range: "A1:P14", include: "values,formulas", tableMaxRows: 14, tableMaxCols: 16, maxChars: 6000 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 3000 });
console.log(inspectSummary.ndjson);
console.log(errors.ndjson);
console.log(sheets.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Saved ${outputPath}`);
