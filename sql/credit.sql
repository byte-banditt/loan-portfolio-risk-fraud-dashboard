DROP VIEW IF EXISTS credit_resolved;
CREATE VIEW credit_resolved AS
SELECT *, CASE WHEN lower(trim(loan_status)) IN
 ('charged off','default','does not meet the credit policy. status:charged off') THEN 1 ELSE 0 END AS default_flag
FROM clean_loans
WHERE lower(trim(loan_status)) IN
 ('fully paid','charged off','default','does not meet the credit policy. status:charged off');

DROP VIEW IF EXISTS credit_delinquency;
CREATE VIEW credit_delinquency AS
SELECT CASE
 WHEN lower(trim(loan_status))='current' THEN 'Current'
 WHEN lower(trim(loan_status))='in grace period' THEN 'In Grace Period'
 WHEN lower(trim(loan_status)) LIKE 'late (16%' THEN 'Late (16-30)'
 WHEN lower(trim(loan_status)) LIKE 'late (31%' THEN 'Late (31-120)'
 WHEN lower(trim(loan_status)) IN ('charged off','default','does not meet the credit policy. status:charged off') THEN 'Charged Off/Default'
 ELSE 'Other active/status'
 END AS delinquency_bucket, COUNT(*) AS loan_count
FROM clean_loans
WHERE lower(trim(loan_status)) IN ('current','in grace period','late (16-30 days)','late (31-120 days)','charged off','default','does not meet the credit policy. status:charged off')
GROUP BY 1;

DROP VIEW IF EXISTS credit_vintage;
CREATE VIEW credit_vintage AS
SELECT strftime('%Y',issue_date) || '-Q' || ((CAST(strftime('%m',issue_date) AS INTEGER)+2)/3) AS issue_quarter,
 COUNT(*) AS resolved_loans, SUM(default_flag) AS defaults,
 1.0*SUM(default_flag)/COUNT(*) AS default_rate
FROM credit_resolved WHERE issue_date IS NOT NULL GROUP BY 1 ORDER BY 1;

DROP VIEW IF EXISTS credit_segments;
CREATE VIEW credit_segments AS
SELECT dimension, segment, COUNT(*) AS resolved_loans, SUM(default_flag) AS defaults,
 1.0*SUM(default_flag)/COUNT(*) AS default_rate
FROM (
 SELECT default_flag,'grade' dimension,COALESCE(NULLIF(grade,''),'Unknown') segment FROM credit_resolved UNION ALL
 SELECT default_flag,'sub_grade',COALESCE(NULLIF(sub_grade,''),'Unknown') FROM credit_resolved UNION ALL
 SELECT default_flag,'term',COALESCE(NULLIF(term,''),'Unknown') FROM credit_resolved UNION ALL
 SELECT default_flag,'purpose',COALESCE(NULLIF(purpose,''),'Unknown') FROM credit_resolved UNION ALL
 SELECT default_flag,'home_ownership',COALESCE(NULLIF(home_ownership,''),'Unknown') FROM credit_resolved UNION ALL
 SELECT default_flag,'state',COALESCE(NULLIF(addr_state,''),'Unknown') FROM credit_resolved
) GROUP BY dimension,segment;

-- Active book buckets only; fully paid and issuance-only rows are excluded.

SELECT COUNT(*) AS total_loans, (SELECT COUNT(*) FROM credit_resolved) AS resolved_loans,
 (SELECT SUM(default_flag)*1.0/COUNT(*) FROM credit_resolved) AS resolved_default_rate
FROM clean_loans;
