# Excel PivotTable instructions

`report.xlsx` contains a native PivotTable on `Grade_Pivot`, generated during the reporting stage from the `Data` worksheet.

## Existing PivotTable

- Name: `GradeRiskPivot`
- Source: `Data!A1:I20001` (the workbook's cleaned loan extract)
- Rows: `grade`
- Values: count of `default_flag` (resolved loan count); average of `default_flag` (resolved-loan default rate)
- Unresolved loan statuses have blank `default_flag` and are excluded from both values.
- The separate `grade_default_rate` column still uses `VLOOKUP` against `Segment_Lookup`.

The PivotTable cache is configured to refresh when Excel opens the workbook. To refresh it manually, open `report.xlsx` in Excel and select **Data > Refresh All**. The reporting code builds the regular formatted workbook with openpyxl, then uses Apache POI to write the native PivotTable; rerunning `make all` regenerates it.

## How it was added

The original workbook had no `pivotTable` or `pivotCache` package parts. `pivot_writer/src/main/java/PivotWriter.java` creates `Grade_Pivot`, points its cache at the `Data` extract, sets `grade` as the row field, and adds `COUNT(default_flag)` and `AVERAGE(default_flag)` data fields. The saved XLSX contains PivotTable, cache definition, cache records, and relationship parts.
