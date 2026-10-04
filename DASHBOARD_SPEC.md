# Tableau dashboard specification

## KPI cards (7)

1. Total loans loaded — `loan_quality.csv`
2. Loans retained after quality checks — `loan_quality.csv`
3. Resolved-loan default rate — `vintage_default_rate.csv` (weighted across rows)
4. PaySim transaction count — `fraud_transaction_summary.csv`
5. Combined-rule precision — `fraud_rule_performance.csv`
6. Combined-rule recall — `fraud_rule_performance.csv`
7. Combined alerts per day — `alerts_per_day.csv`

## Charts, filters and extracts

- Issue-quarter line chart: `vintage_default_rate.csv`; filter issue quarter.
- Segment bar chart: `segment_default_rate.csv`; filter dimension and minimum resolved count.
- Active-book delinquency distribution: `delinquency_buckets.csv`; filter bucket.
- Fraud rule comparison bars for precision, recall, F1: `fraud_rule_performance.csv`; filter rule and test window.
- Operational alert volume by rule: `alerts_per_day.csv`; filter rule.
- Suggested global filters: issue quarter, segment dimension, segment, fraud rule. Fraud evaluates only the held-out final time window.
