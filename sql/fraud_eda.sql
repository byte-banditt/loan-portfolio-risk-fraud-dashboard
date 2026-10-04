SELECT type, COUNT(*) n, SUM(isFraud) frauds, 1.0*SUM(isFraud)/COUNT(*) fraud_rate,
 AVG(amount) avg_amount, MIN(amount) min_amount, MAX(amount) max_amount
FROM clean_paysim GROUP BY type ORDER BY type;
SELECT isFraud, COUNT(*) n, AVG(CAST(amount AS REAL)) avg_amount,
 MIN(CAST(amount AS REAL)) min_amount, MAX(CAST(amount AS REAL)) max_amount,
 AVG(oldbalanceOrg) avg_old_origin, AVG(newbalanceOrig) avg_new_origin,
 AVG(oldbalanceDest) avg_old_dest, AVG(newbalanceDest) avg_new_dest
FROM clean_paysim GROUP BY isFraud;
