DROP TABLE IF EXISTS fraud_alerts;
CREATE TABLE fraud_alerts AS
WITH fanin AS (SELECT step,nameDest,dest_count FROM fraud_fanin), scored AS (
 SELECT p.rowid AS tx_id, CAST(p.step AS INTEGER) step, CAST(p.amount AS REAL) amount,
        CAST(p.isFraud AS INTEGER) actual, CAST(p.isFlaggedFraud AS INTEGER) baseline,
        p.type,p.nameOrig,p.nameDest,
        CASE WHEN p.type='TRANSFER' AND CAST(p.amount AS REAL)>=:large_threshold THEN 1 ELSE 0 END AS rule_large_transfer,
        CASE WHEN ABS(CAST(p.amount AS REAL)-CAST(p.oldbalanceOrg AS REAL))<0.01 AND ABS(CAST(p.newbalanceOrig AS REAL))<0.01 THEN 1 ELSE 0 END AS rule_account_drain,
        CASE WHEN f.dest_count>=:fanin_threshold THEN 1 ELSE 0 END AS rule_dest_fanin,
        CASE WHEN p.type IN ('TRANSFER','CASH_OUT') AND ABS(CAST(p.oldbalanceOrg AS REAL)-CAST(p.amount AS REAL)-CAST(p.newbalanceOrig AS REAL))>0.01 THEN 1 ELSE 0 END AS rule_balance_inconsistency
 FROM clean_paysim p JOIN fanin f ON p.step=f.step AND p.nameDest=f.nameDest
)
SELECT *, (rule_large_transfer+rule_account_drain+rule_dest_fanin+rule_balance_inconsistency) AS rule_count,
       CASE WHEN rule_large_transfer+rule_account_drain+rule_dest_fanin+rule_balance_inconsistency>0 THEN 1 ELSE 0 END AS combined_alert,
       CASE WHEN step>=:test_min THEN 1 ELSE 0 END AS is_test
FROM scored;
