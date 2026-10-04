# Project numbers (computed from this run)

| Value | Result | Code path |
|---|---:|---|
| Total loans loaded | 2,260,701 | `pipeline.py:stage_etl`, `raw_loans` |
| Loans after cleaning | 2,260,666 | `pipeline.py:stage_etl`, `clean_loans` |
| Worst segment | purpose=major_purchase | `pipeline.py:stage_credit`, `RCA.md` |
| Percentage-point increase attributed to top driver | +7.922 pp (term within-segment rate effect) | `pipeline.py:stage_credit`, `RCA.md` |
| Dashboard KPI cards | 10 | `DASHBOARD_SPEC.md` |
| Fraud rules | 2 | `pipeline.py:stage_fraud`, `FRAUD_RULES.md` |
| PaySim transactions | 6,362,620 | `pipeline.py:stage_etl`, `clean_paysim` |
| Combined test precision | 0.736730 | `pipeline.py:stage_fraud`, test window |
| Combined test recall | 0.998759 | `pipeline.py:stage_fraud`, test window |
| Alerts per day | 354.378378 | `pipeline.py:stage_fraud`, 24 steps/day |
| Scorecard validation AUC | 0.697190 | `model_review.py:run`, `validation` years [2014, 2015] |
| Scorecard validation KS | 0.285111 | `model_review.py:run`, `validation` years [2014, 2015] |
| Scorecard validation GINI | 0.394380 | `model_review.py:run`, `validation` years [2014, 2015] |
| Scorecard test AUC | 0.675856 | `model_review.py:run`, `test` years [2016, 2017, 2018] |
| Scorecard test KS | 0.251534 | `model_review.py:run`, `test` years [2016, 2017, 2018] |
| Scorecard test GINI | 0.351713 | `model_review.py:run`, `test` years [2016, 2017, 2018] |
| Grade-only test AUC | 0.677773 | `model_review.py:run`, grade-only baseline |
| Grade-only test KS | 0.268430 | `model_review.py:run`, grade-only baseline |
| Grade-only test GINI | 0.355546 | `model_review.py:run`, grade-only baseline |
| Model loans loaded (resolved) | 1,346,109 | `model_review.py:_load_features`, `model_input_loans` |
| Model feature count | 22 | `model_review.py:FEATURE_CANDIDATES` present in observed source |
| Maximum feature PSI | 1.494840 (application_type) | `model_review.py:run`, `tableau_extracts/psi_by_year.csv` |
| Reject inference effect | NOT AVAILABLE — rejected-applicant outcomes are absent | `MODEL_REVIEW.md`, strategy sweep limitations |
