# Loan Portfolio Risk & Fraud Early-Warning Dashboard

Portfolio project for credit risk, fraud monitoring and data analytics. Built from Kaggle Lending Club accepted-loan records and PaySim synthetic transaction records. Python ETL loads chunked CSV data to SQLite `raw_*`, `clean_*`, and `rejected_*` tables; SQL files define analysis views/rules. Outputs: DQ reports, credit vintage/segment/delinquency analysis, time-based WoE scorecard review, fraud EDA and held-out rule metrics, RCA, Tableau extracts, Excel workbook and six-slide presentation.

## Run

Python 3.11+ and JDK 17+ with Maven required. Install Python packages with `python -m pip install -r requirements.txt`. Keep downloaded source files in `data/`; run all stages with `make all` (equivalent to `python pipeline.py all`). The reporting stage uses Apache POI via Maven to create a native Excel PivotTable. Model-only stage, after ETL created `warehouse.sqlite`: `make model` or `python pipeline.py model`. Re-run is idempotent: model tables and outputs are rebuilt. Credit model uses chronological issue-year train, validation and test windows; PaySim uses sorted unique steps with first 70% training and final 30% testing. No random split is used. SQLite is local; no cloud services.

## Data sources and download

- Lending Club accepted loans 2007–2018 Q4: Kaggle `wordsforthewise/lending-club`, file `accepted_2007_to_2018Q4.csv.gz`.
- PaySim synthetic financial transactions: Kaggle `ealaxi/paysim1`, file `PS_20174392719_1491204439457_log.csv`.

Download via authenticated Kaggle CLI: `kaggle datasets download -d wordsforthewise/lending-club -f accepted_2007_to_2018Q4.csv.gz -p data` and `kaggle datasets download -d ealaxi/paysim1 -f PS_20174392719_1491204439457_log.csv -p data`. The pipeline reads these compressed downloads directly. Source headers are inspected and selected columns adapted to fields actually present.

## Architecture

```text
Kaggle CSV/GZ/ZIP → chunked Python ETL + DQ → SQLite raw_* / clean_* / rejected_*
                                                   ↓ SQL in sql/*.sql
                             credit, fraud & model marts/views → CSV extracts + XLSX + PPTX + Markdown
```

## Design decisions

- `id` uniquely keys Lending Club rows. PaySim has no transaction ID, so duplicate check uses step, origin, destination, type and amount as a composite signature. Rejected rows persist in `rejected_*` with JSON record and reason; rows with nulls persist in `flagged_*` with column list and JSON record while remaining in clean tables. Date parsing and range checks use observed `issue_d` values.
- Credit default = Charged Off or Default, including policy-status Charged Off variant when present. Rates use only Fully Paid, Charged Off and Default resolved loans. Current and other unresolved statuses are excluded to reduce censoring bias; this also means rates can differ from eventual full-cohort outcomes.
- Vintage is issue-quarter default rate on resolved loans only. Available fields do not establish comparable months-on-book exposure, so no true months-on-book curve is claimed.
- RCA compares earliest and latest quartiles of available issue quarters. Marginal shift-share is computed independently for grade, term and purpose; effects overlap and do not sum to portfolio change. No causal interpretation.
- Fraud candidates are selected from EDA and tuned on training period only. Test period is final 30% of ordered distinct hourly steps. Alerts/day = test alerts divided by test hours / 24. Investigative score is fired-rule count plus alert amount divided by max test-alert amount.
- Credit model reads inspected application-time fields. WoE numeric bins, category mappings, IV and logistic fit use training vintages only. Grade, sub_grade and int_rate are excluded as Lending Club underwriting outputs; grade-only logistic regression is a same-test-window benchmark. High-null mths_since_last_delinq and mths_since_last_record are not used. Score points use 20 points per odds doubling, anchored at 600 points for 50:1 good-to-bad odds.
- Drift bins are fitted on training vintages; PSI above 0.10 is watch and above 0.25 is action. Calibration and cutoff trade-offs use the held-out test window. Rejected-applicant outcomes are absent, so reject inference is unavailable; cutoff sweep is descriptive and makes no causal recommendation.
- Excel `Data` contains first 20,000 cleaned rows as a manageable workbook extract; full data remains in SQLite. Excel includes actual VLOOKUP formulas and a generated native PivotTable. Field layout and refresh steps are documented in `INSTRUCTIONS.md` and the `INSTRUCTIONS` worksheet.

## Outputs

`warehouse.sqlite`, `dq_report_loans.csv`, `dq_report_paysim.csv`, `RCA.md`, `FRAUD_RULES.md`, `MODEL_REVIEW.md`, `scorecard.json`, `DASHBOARD_SPEC.md`, `tableau_extracts/`, `investigator_queue.csv`, `report.xlsx`, `summary.pptx`, `NUMBERS.md`.

## Limitations

- Lending Club is US marketplace lending data. It does not represent any target lender's portfolio, policy, product or customer behavior.
- Resolved-only default rates exclude unresolved/current loans, creating selection and censoring limitations.
- Scorecard is trained and evaluated only on resolved Lending Club loans, creating resolved-only selection bias. Rejected-applicant outcomes are unobserved; no reject inference or causal cutoff recommendation is supported.
- Issue-quarter vintage analysis is not exposure-aligned months-on-book analysis.
- PaySim is synthetic. Rule results are not evidence of production fraud detection quality or real loss prevention.
- Data contains no target institution's decision policy, real investigator outcomes or applicable regulator context. This is an analytical portfolio exercise, not policy or compliance advice.
