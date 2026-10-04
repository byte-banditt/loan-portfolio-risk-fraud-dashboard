# Loan Portfolio Risk & Fraud Early-Warning Dashboard

Portfolio project for credit risk, fraud monitoring and data analytics. Built from Kaggle Lending Club accepted-loan records and PaySim synthetic transaction records. Python ETL loads chunked CSV data to SQLite `raw_*`, `clean_*`, and `rejected_*` tables; SQL files define analysis views/rules. Outputs: DQ reports, credit vintage/segment/delinquency analysis, fraud EDA and held-out rule metrics, RCA, Tableau extracts, Excel workbook and six-slide presentation.

## Run

Python 3.11+ required. Install packages with `python -m pip install -r requirements.txt`. Keep downloaded source files in `data/`; run all stages with `make all` (equivalent to `python pipeline.py all`). Re-run is idempotent: warehouse and generated outputs are rebuilt. Fixed split is by sorted unique PaySim step with first 70% training and final 30% testing; no random sampling is used. SQLite is local; no cloud services.

## Data sources and download

- Lending Club accepted loans 2007–2018 Q4: Kaggle `wordsforthewise/lending-club`, file `accepted_2007_to_2018Q4.csv.gz`.
- PaySim synthetic financial transactions: Kaggle `ealaxi/paysim1`, file `PS_20174392719_1491204439457_log.csv`.

Download via authenticated Kaggle CLI: `kaggle datasets download -d wordsforthewise/lending-club -f accepted_2007_to_2018Q4.csv.gz -p data` and `kaggle datasets download -d ealaxi/paysim1 -f PS_20174392719_1491204439457_log.csv -p data`. The pipeline reads these compressed downloads directly. Source headers are inspected and selected columns adapted to fields actually present.

## Architecture

```text
Kaggle CSV/GZ/ZIP → chunked Python ETL + DQ → SQLite raw_* / clean_* / rejected_*
                                                   ↓ SQL in sql/*.sql
                             credit & fraud marts/views → CSV extracts + XLSX + PPTX + Markdown
```

## Design decisions

- `id` uniquely keys Lending Club rows. PaySim has no transaction ID, so duplicate check uses step, origin, destination, type and amount as a composite signature. Rejected rows persist in `rejected_*` with JSON record and reason; rows with nulls persist in `flagged_*` with column list and JSON record while remaining in clean tables. Date parsing and range checks use observed `issue_d` values.
- Credit default = Charged Off or Default, including policy-status Charged Off variant when present. Rates use only Fully Paid, Charged Off and Default resolved loans. Current and other unresolved statuses are excluded to reduce censoring bias; this also means rates can differ from eventual full-cohort outcomes.
- Vintage is issue-quarter default rate on resolved loans only. Available fields do not establish comparable months-on-book exposure, so no true months-on-book curve is claimed.
- RCA compares earliest and latest quartiles of available issue quarters. Marginal shift-share is computed independently for grade, term and purpose; effects overlap and do not sum to portfolio change. No causal interpretation.
- Fraud candidates are selected from EDA and tuned on training period only. Test period is final 30% of ordered distinct hourly steps. Alerts/day = test alerts divided by test hours / 24. Investigative score is fired-rule count plus alert amount divided by max test-alert amount.
- Excel `Data` contains first 20,000 cleaned rows as a manageable workbook extract; full data remains in SQLite. Excel includes actual VLOOKUP formulas. Native PivotTables must be inserted manually as described in `INSTRUCTIONS`.

## Outputs

`warehouse.sqlite`, `dq_report_loans.csv`, `dq_report_paysim.csv`, `RCA.md`, `FRAUD_RULES.md`, `DASHBOARD_SPEC.md`, `tableau_extracts/`, `investigator_queue.csv`, `report.xlsx`, `summary.pptx`, `NUMBERS.md`.

## Limitations

- Lending Club is US marketplace lending data. It does not represent any target lender's portfolio, policy, product or customer behavior.
- Resolved-only default rates exclude unresolved/current loans, creating selection and censoring limitations.
- Issue-quarter vintage analysis is not exposure-aligned months-on-book analysis.
- PaySim is synthetic. Rule results are not evidence of production fraud detection quality or real loss prevention.
- Data contains no target institution's decision policy, real investigator outcomes or applicable regulator context. This is an analytical portfolio exercise, not policy or compliance advice.
