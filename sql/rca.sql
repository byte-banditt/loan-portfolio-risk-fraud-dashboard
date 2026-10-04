DROP TABLE IF EXISTS temp.rca_segment_rates;
CREATE TEMP TABLE rca_segment_rates AS
SELECT dimension,segment,period,COUNT(*) AS loans,AVG(default_flag) AS default_rate
FROM (
 SELECT w.period,c.default_flag,'grade' AS dimension,COALESCE(NULLIF(c.grade,''),'Unknown') AS segment
 FROM credit_resolved c JOIN rca_windows w ON strftime('%Y',c.issue_date)||'-Q'||((CAST(strftime('%m',c.issue_date) AS INTEGER)+2)/3)=w.issue_quarter
 UNION ALL
 SELECT w.period,c.default_flag,'term',COALESCE(NULLIF(c.term,''),'Unknown')
 FROM credit_resolved c JOIN rca_windows w ON strftime('%Y',c.issue_date)||'-Q'||((CAST(strftime('%m',c.issue_date) AS INTEGER)+2)/3)=w.issue_quarter
 UNION ALL
 SELECT w.period,c.default_flag,'purpose',COALESCE(NULLIF(c.purpose,''),'Unknown')
 FROM credit_resolved c JOIN rca_windows w ON strftime('%Y',c.issue_date)||'-Q'||((CAST(strftime('%m',c.issue_date) AS INTEGER)+2)/3)=w.issue_quarter
) GROUP BY dimension,segment,period;

DROP TABLE IF EXISTS temp.rca_decomposition;
CREATE TEMP TABLE rca_decomposition AS
WITH paired AS (
 SELECT dimension,segment,
  SUM(CASE WHEN period=0 THEN loans ELSE 0 END) AS early_n,
  SUM(CASE WHEN period=1 THEN loans ELSE 0 END) AS late_n,
  COALESCE(MAX(CASE WHEN period=0 THEN default_rate END),0.0) AS early_rate,
  COALESCE(MAX(CASE WHEN period=1 THEN default_rate END),0.0) AS late_rate
 FROM rca_segment_rates GROUP BY dimension,segment
), shares AS (
 SELECT *,1.0*early_n/SUM(early_n) OVER (PARTITION BY dimension) AS early_share,
  1.0*late_n/SUM(late_n) OVER (PARTITION BY dimension) AS late_share
 FROM paired
)
SELECT dimension,
 SUM(late_share*(late_rate-early_rate))*100.0 AS rate_effect_pp,
 SUM((late_share-early_share)*early_rate)*100.0 AS mix_effect_pp,
 SUM(late_share*(late_rate-early_rate)+(late_share-early_share)*early_rate)*100.0 AS total_change_pp
FROM shares GROUP BY dimension;

DROP TABLE IF EXISTS temp.rca_window_rates;
CREATE TEMP TABLE rca_window_rates AS
SELECT period,COUNT(*) AS loans,AVG(default_flag) AS default_rate
FROM (
 SELECT w.period,c.default_flag FROM credit_resolved c
 JOIN rca_windows w ON strftime('%Y',c.issue_date)||'-Q'||((CAST(strftime('%m',c.issue_date) AS INTEGER)+2)/3)=w.issue_quarter
) GROUP BY period;

DROP TABLE IF EXISTS temp.rca_worst_segment;
CREATE TEMP TABLE rca_worst_segment AS
SELECT dimension,segment,early_n,late_n,early_rate,late_rate,(late_rate-early_rate)*100.0 AS delta_pp
FROM (
 SELECT *,ROW_NUMBER() OVER (ORDER BY (late_rate-early_rate) DESC,dimension,segment) AS rank_no
 FROM (
  SELECT dimension,segment,SUM(CASE WHEN period=0 THEN loans ELSE 0 END) early_n,
   SUM(CASE WHEN period=1 THEN loans ELSE 0 END) late_n,
   COALESCE(MAX(CASE WHEN period=0 THEN default_rate END),0.0) early_rate,
   COALESCE(MAX(CASE WHEN period=1 THEN default_rate END),0.0) late_rate
  FROM rca_segment_rates GROUP BY dimension,segment
 ) WHERE early_n>=100 AND late_n>=100
) WHERE rank_no=1;

SELECT dimension,segment,early_n,late_n,early_rate,late_rate,(late_rate-early_rate)*100.0 AS delta_pp
FROM (
 SELECT *,ROW_NUMBER() OVER (ORDER BY (late_rate-early_rate) DESC,dimension,segment) AS rank_no
 FROM (
  SELECT dimension,segment,SUM(CASE WHEN period=0 THEN loans ELSE 0 END) early_n,
   SUM(CASE WHEN period=1 THEN loans ELSE 0 END) late_n,
   COALESCE(MAX(CASE WHEN period=0 THEN default_rate END),0.0) early_rate,
   COALESCE(MAX(CASE WHEN period=1 THEN default_rate END),0.0) late_rate
  FROM rca_segment_rates GROUP BY dimension,segment
 ) WHERE early_n>=100 AND late_n>=100
) WHERE rank_no=1;
