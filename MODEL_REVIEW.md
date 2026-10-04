# Credit model review

## Validation memo

**Purpose.** Transparent Lending Club default risk scorecard prototype; not a lending policy recommendation.

**Data and target.** Source contains 2,260,701 rows. Resolved modeling cohort contains 1,346,109 loans after issue-date and existing DQ validation (2 resolved rows rejected by date or existing data-quality checks). Target: Charged Off, Default, and observed policy Charged Off variant versus Fully Paid. Current/unresolved outcomes excluded. Application-time feature candidates present and used: loan_amnt, annual_inc, dti, delinq_2yrs, fico_range_low, inq_last_6mths, open_acc, pub_rec, revol_util, total_acc, collections_12_mths_ex_med, acc_now_delinq, delinq_amnt, pub_rec_bankruptcies, tax_liens, term, emp_length, home_ownership, verification_status, purpose, addr_state, application_type. Train vintages 2007–2013; validation [2014, 2015]; test [2016, 2017, 2018]; splits use issue year, with no random split. WoE quantile boundaries and mappings fitted on training only; fixed seed 20261004.

**Leakage controls.** Excluded underwriting outputs grade, sub_grade and int_rate from model inputs; grade used only for same-period grade-only benchmark. Excluded observed post-origination fields: out_prncp, out_prncp_inv, total_pymnt, total_pymnt_inv, recoveries, collection_recovery_fee, last_pymnt_d, last_pymnt_amnt, last_credit_pull_d. No loan status or issue date is a predictor; issue date only assigns temporal partitions. Rows with unavailable fields use missing bins. Numeric IV top feature: **term**, 0.14506.

**Performance.** Validation scorecard AUC 0.69719, KS 0.28511, Gini 0.39438. Test scorecard AUC 0.67586, KS 0.25153, Gini 0.35171; grade-only test baseline AUC 0.67777, KS 0.26843, Gini 0.35555. Points use 20 points per odds doubling, with score 600 at 50:1 good-to-bad odds; these are display anchors.

**Calibration.** Test score deciles are ordered by points: decile 1 has lowest score/highest modeled risk; decile 10 has highest score/lowest modeled risk.

| Decile | Loans | Mean score | Observed default rate |
|---:|---:|---:|---:|
| 1 | 51,875 | 504.89 | 44.2217% |
| 2 | 51,874 | 520.59 | 34.1770% |
| 3 | 51,874 | 528.03 | 29.2883% |
| 4 | 51,874 | 533.51 | 25.4771% |
| 5 | 51,874 | 538.34 | 22.3850% |
| 6 | 51,874 | 543.05 | 19.5686% |
| 7 | 51,874 | 548.00 | 17.1030% |
| 8 | 51,874 | 553.65 | 14.4697% |
| 9 | 51,874 | 561.02 | 11.1655% |
| 10 | 51,875 | 575.84 | 6.3306% |

**Stability.** Largest feature PSI is application_type, issue year 2018, PSI 1.49484 (action). Across score and feature/year checks: 97 stable, 15 watch, 3 action. Thresholds: >0.10 watch; >0.25 action. Score PSI included separately in `tableau_extracts/psi_by_year.csv`.

**Limitations.** US Lending Club data does not represent a target lender or its policy. Resolved-only selection excludes unresolved loans and creates selection/censoring bias. Rejected-applicant outcomes are unobserved; reject inference is unavailable. Strategy sweep is descriptive, not causal, and makes no cutoff recommendation. No local underwriting policy, target population, regulator context or production outcome monitoring is available. Temporal cohorts and source practices may differ materially from current lending.
