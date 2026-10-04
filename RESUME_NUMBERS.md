# Resume numbers (computed from this run)

| Value | Result | Code path |
|---|---:|---|
| Total loans loaded | 2,260,701 | `pipeline.py:stage_etl`, `raw_loans` |
| Loans after cleaning | 2,260,666 | `pipeline.py:stage_etl`, `clean_loans` |
| Worst segment | purpose=major_purchase | `pipeline.py:stage_credit`, `RCA.md` |
| Percentage-point increase attributed to top driver | +7.922 pp (term within-segment rate effect) | `pipeline.py:stage_credit`, `RCA.md` |
| Dashboard KPI cards | 7 | `DASHBOARD_SPEC.md` |
| Fraud rules | 2 | `pipeline.py:stage_fraud`, `FRAUD_RULES.md` |
| PaySim transactions | 6,362,620 | `pipeline.py:stage_etl`, `clean_paysim` |
| Combined test precision | 0.736730 | `pipeline.py:stage_fraud`, test window |
| Combined test recall | 0.998759 | `pipeline.py:stage_fraud`, test window |
| Alerts per day | 354.378378 | `pipeline.py:stage_fraud`, 24 steps/day |
