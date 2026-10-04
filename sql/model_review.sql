DROP VIEW IF EXISTS model_review_resolved;
CREATE VIEW model_review_resolved AS
SELECT * FROM model_input_loans
WHERE default_flag IN (0,1) AND issue_date IS NOT NULL;

DROP VIEW IF EXISTS model_review_year_counts;
CREATE VIEW model_review_year_counts AS
SELECT CAST(substr(issue_date,1,4) AS INTEGER) AS issue_year,
       COUNT(*) AS resolved_loans,
       SUM(default_flag) AS defaults
FROM model_review_resolved
GROUP BY issue_year
ORDER BY issue_year;
