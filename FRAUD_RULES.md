# Fraud rule analysis

PaySim is synthetic. Dataset has 6,362,620 cleaned transactions. EDA ran before rule selection.

## EDA: fraud by transaction type

| Type | Transactions | Fraud | Fraud rate | Mean amount |
|---|---:|---:|---:|---:|
| CASH_IN | 1,399,284 | 0 | 0.00000% | 168920.24 |
| CASH_OUT | 2,237,500 | 4,116 | 0.18396% | 176273.96 |
| DEBIT | 41,432 | 0 | 0.00000% | 5483.67 |
| PAYMENT | 2,151,495 | 0 | 0.00000% | 13057.60 |
| TRANSFER | 532,909 | 4,097 | 0.76880% | 910647.01 |

## Balance and amount patterns

| isFraud | Transactions | Mean amount | Min amount | Max amount | Mean old origin balance | Mean new origin balance | Mean old destination balance | Mean new destination balance |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 6,354,407 | 178197.04 | 0.01 | 92445516.64 | 832828.71 | 855970.23 | 1101420.87 | 1224925.68 |
| 1 | 8,213 | 1467967.30 | 0.00 | 10000000.00 | 1649667.61 | 192392.63 | 544249.62 | 1279707.62 |

## Split and tuning

Ordered distinct steps: 743. Training ended at step 521; test began at step 522. Split by distinct step, first 70% train, last 30% test. All thresholds selected using training only. Test window has 222 hourly steps (9.25 days). Candidate rules retained only when training F1 exceeded the dataset-flagged baseline F1 (0.00207); this criterion was fixed before held-out evaluation.

### Large TRANSFER

- Rule: `type='TRANSFER' AND CAST(amount AS REAL)>=2690019.7329999986`
- Train F1: 0.03014; train precision: 0.01852; train recall: 0.08093.
- Tuning: maximize training F1 over exact training TRANSFER amount quantiles 75%, 85%, 90%, 95%, and 99%.
- Test result: {'rule': 'Large TRANSFER', 'alerts': 1047, 'alerts_per_day': 113.1891891891892, 'precision': 0.17574021012416427, 'recall': 0.076095947063689, 'f1': 0.1062049062049062, 'tp': 184, 'fp': 863, 'fn': 2234}
- Limit: PaySim is synthetic; same-hour fan-in is batch-scoped and may not represent online availability.

### Account drain

- Rule: `ABS(CAST(amount AS REAL)-CAST(oldbalanceOrg AS REAL))<0.01 AND ABS(CAST(newbalanceOrig AS REAL))<0.01`
- Train F1: 0.98910; train precision: 1.00000; train recall: 0.97843.
- Tuning: exact amount=old origin balance and new origin balance=0, with 0.01 balance tolerance.
- Test result: {'rule': 'Account drain', 'alerts': 2354, 'alerts_per_day': 254.48648648648648, 'precision': 1.0, 'recall': 0.9735318444995864, 'f1': 0.9865884325230512, 'tp': 2354, 'fp': 0, 'fn': 64}
- Limit: PaySim is synthetic; same-hour fan-in is batch-scoped and may not represent online availability.

## Rules dropped

- Destination fan-in: training F1 0.00075 did not exceed flagged-baseline F1 0.00207; training precision 0.00038, recall 0.03693.
- Origin balance inconsistency: training F1 0.00003 did not exceed flagged-baseline F1 0.00207; training precision 0.00001, recall 0.00604.

Combined test precision 0.73673, recall 0.99876, F1 0.84796, alerts/day 354.378. Baseline included in `tableau_extracts/fraud_rule_performance.csv`. Performance on synthetic PaySim is not evidence of production fraud control performance.
