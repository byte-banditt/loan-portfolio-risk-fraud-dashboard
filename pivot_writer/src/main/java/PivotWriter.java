import java.io.FileInputStream;
import java.io.FileOutputStream;
import org.apache.poi.ss.SpreadsheetVersion;
import org.apache.poi.ss.util.AreaReference;
import org.apache.poi.ss.util.CellReference;
import org.apache.poi.xssf.usermodel.XSSFPivotTable;
import org.apache.poi.xssf.usermodel.XSSFSheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.ss.usermodel.DataConsolidateFunction;

public class PivotWriter {
  public static void main(String[] args) throws Exception {
    String file=args[0];
    try (FileInputStream in=new FileInputStream(file); XSSFWorkbook wb=new XSSFWorkbook(in)) {
      XSSFSheet data=wb.getSheet("Data");
      if (data==null) throw new IllegalStateException("Data sheet missing");
      XSSFSheet pivot=wb.getSheet("Grade_Pivot");
      if (pivot!=null) {
        for (XSSFPivotTable existing : pivot.getPivotTables()) {
          if ("GradeRiskPivot".equals(existing.getCTPivotTableDefinition().getName())) return;
        }
        wb.removeSheetAt(wb.getSheetIndex(pivot));
      }
      pivot=wb.createSheet("Grade_Pivot");
      AreaReference source=new AreaReference("Data!A1:I"+(data.getLastRowNum()+1), SpreadsheetVersion.EXCEL2007);
      XSSFPivotTable table=pivot.createPivotTable(source,new CellReference("A3"),data);
      table.getCTPivotTableDefinition().setName("GradeRiskPivot");
      table.getPivotCacheDefinition().getCTPivotCacheDefinition().setRefreshOnLoad(true);
      table.getPivotCacheDefinition().getCTPivotCacheDefinition().setSaveData(false);
      table.getPivotCacheDefinition().getCTPivotCacheDefinition().setRecordCount(0);
      table.addRowLabel(3);
      // Cache is refresh-on-open; omit 20,000 placeholder items that POI
      // otherwise writes before Excel has populated the cache.
      table.getCTPivotTableDefinition().getPivotFields().getPivotFieldArray(3).unsetItems();
      table.addColumnLabel(DataConsolidateFunction.COUNT,8,"Resolved Loan Count");
      table.addColumnLabel(DataConsolidateFunction.AVERAGE,8,"Average Default Rate");
      try (FileOutputStream out=new FileOutputStream(file)) { wb.write(out); }
    }
  }
}
