# Credit portfolio root-cause analysis

## Finding
Worst matched segment deterioration (minimum 100 resolved loans in each window): **purpose=major_purchase**, default rate moved from 13.5922% to 22.2108% (+8.62 percentage points; n=309 earliest, 10,684 latest) between issue-quarter windows 2007-Q2–2009-Q4 and 2016-Q2–2018-Q4.

## Evidence
Overall resolved-loan rate moved from 19.6154% (n=7,020) to 22.9847% (n=406,809). SQL shift-share by grade, term and purpose: grade: total +3.369 pp = within-segment rate +2.795 pp + mix +0.574 pp; purpose: total +3.369 pp = within-segment rate +4.566 pp + mix -1.197 pp; term: total +3.369 pp = within-segment rate +7.922 pp + mix -4.552 pp. Largest positive within-segment effect: **term within-segment rate effect**, +7.922 pp.

## Caveats
Windows are earliest/latest quartiles of available issue quarters; default uses resolved loans only, excluding current/unresolved loans. Each dimension independently decomposes the same overall change, so grade, term and purpose results are alternative explanations and must not be summed across dimensions. Effects are associations, not causal attributions. Worst segment requires at least 100 resolved loans per window. No month-on-book fields establish comparable exposure, so this is issue-quarter analysis, not a months-on-book curve.
