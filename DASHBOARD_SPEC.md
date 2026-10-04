# Tableau dashboard specification

## KPI cards (10)

1. Total loans loaded — `loan_quality.csv`
2. Loans retained after quality checks — `loan_quality.csv`
3. Resolved-loan default rate — `vintage_default_rate.csv` (weighted across rows)
4. PaySim transaction count — `fraud_transaction_summary.csv`
5. Combined-rule precision — `fraud_rule_performance.csv`
6. Combined-rule recall — `fraud_rule_performance.csv`
7. Combined alerts per day — `alerts_per_day.csv`
8. Scorecard test AUC — `model_performance.csv`, model=`WoE logistic scorecard`, window=`test`
9. Grade-only baseline test AUC — `model_performance.csv`, model=`grade-only logistic baseline`, window=`test`
10. Maximum feature PSI — `psi_by_year.csv`, excluding the `score` row; show issue year and status

## Charts, filters and extracts

- Issue-quarter line chart: `vintage_default_rate.csv`; filter issue quarter.
- Segment bar chart: `segment_default_rate.csv`; filter dimension and minimum resolved count.
- Active-book delinquency distribution: `delinquency_buckets.csv`; filter bucket.
- Fraud rule comparison bars for precision, recall, F1: `fraud_rule_performance.csv`; filter rule and test window.
- Operational alert volume by rule: `alerts_per_day.csv`; filter rule.
- Score calibration by test score decile: `score_calibration.csv`; show mean score and observed default rate.
- Stability heatmap: `psi_by_year.csv`; rows=feature/score, columns=issue year, color by PSI; reference 0.10 watch and 0.25 action.
- Approval/bad-rate trade-off: `strategy_sweep.csv`; plot approval rate against bad rate among approved and declined; no cutoff recommendation.
- Feature information value bars: `feature_information_value.csv`; filter feature type; IV is train-window only.
- Suggested global filters: issue quarter, segment dimension, segment, fraud rule. Fraud evaluates only the held-out final time window.

## Model review extracts

- `model_performance.csv`: validation and test scorecard AUC/KS/Gini plus same-test-set grade-only baseline.
- `score_calibration.csv`: test score decile, loan count, mean points score and observed default rate.
- `psi_by_year.csv`: training-window population stability index for score and each feature by later issue year, with stable/watch/action status.
- `strategy_sweep.csv`: test-window score cutoffs, approval rate, approved and declined observed bad rates, and loan counts.
- `feature_information_value.csv`: feature-level IV fitted from training vintages.

All model extracts use resolved loans and chronological issue-year splits. Rejected-applicant outcomes are unobserved; strategy trade-offs are descriptive.
