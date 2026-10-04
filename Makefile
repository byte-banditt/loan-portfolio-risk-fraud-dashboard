.PHONY: all clean
all:
	python pipeline.py all

clean:
	rm -f warehouse.sqlite report.xlsx summary.pptx dq_report_*.csv
	rm -rf tableau_extracts
