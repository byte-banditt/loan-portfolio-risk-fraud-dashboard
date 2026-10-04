WITH base AS MATERIALIZED (
 SELECT step,actual,baseline,rule_large_transfer,rule_account_drain,rule_dest_fanin,
        rule_balance_inconsistency,combined_alert
 FROM fraud_test_alerts
), counts AS (
 SELECT 'Large TRANSFER' AS rule,SUM(rule_large_transfer) alerts,
  SUM(CASE WHEN rule_large_transfer=1 AND actual=1 THEN 1 ELSE 0 END) tp,
  SUM(CASE WHEN rule_large_transfer=1 AND actual=0 THEN 1 ELSE 0 END) fp,
  SUM(CASE WHEN rule_large_transfer=0 AND actual=1 THEN 1 ELSE 0 END) fn FROM base
 UNION ALL SELECT 'Account drain',SUM(rule_account_drain),
  SUM(CASE WHEN rule_account_drain=1 AND actual=1 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_account_drain=1 AND actual=0 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_account_drain=0 AND actual=1 THEN 1 ELSE 0 END) FROM base
 UNION ALL SELECT 'Destination fan-in',SUM(rule_dest_fanin),
  SUM(CASE WHEN rule_dest_fanin=1 AND actual=1 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_dest_fanin=1 AND actual=0 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_dest_fanin=0 AND actual=1 THEN 1 ELSE 0 END) FROM base
 UNION ALL SELECT 'Origin balance inconsistency',SUM(rule_balance_inconsistency),
  SUM(CASE WHEN rule_balance_inconsistency=1 AND actual=1 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_balance_inconsistency=1 AND actual=0 THEN 1 ELSE 0 END),SUM(CASE WHEN rule_balance_inconsistency=0 AND actual=1 THEN 1 ELSE 0 END) FROM base
 UNION ALL SELECT 'Combined rule set',SUM(combined_alert),
  SUM(CASE WHEN combined_alert=1 AND actual=1 THEN 1 ELSE 0 END),SUM(CASE WHEN combined_alert=1 AND actual=0 THEN 1 ELSE 0 END),SUM(CASE WHEN combined_alert=0 AND actual=1 THEN 1 ELSE 0 END) FROM base
 UNION ALL SELECT 'Dataset isFlaggedFraud baseline',SUM(baseline),
  SUM(CASE WHEN baseline=1 AND actual=1 THEN 1 ELSE 0 END),SUM(CASE WHEN baseline=1 AND actual=0 THEN 1 ELSE 0 END),SUM(CASE WHEN baseline=0 AND actual=1 THEN 1 ELSE 0 END) FROM base
)
SELECT rule,alerts,tp,fp,fn,
 CASE WHEN tp+fp=0 THEN 0.0 ELSE 1.0*tp/(tp+fp) END AS precision,
 CASE WHEN tp+fn=0 THEN 0.0 ELSE 1.0*tp/(tp+fn) END AS recall,
 CASE WHEN 2*tp+fp+fn=0 THEN 0.0 ELSE 2.0*tp/(2*tp+fp+fn) END AS f1,
 (SELECT COUNT(DISTINCT step) FROM base) AS test_steps
FROM counts;
