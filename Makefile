.PHONY: all clean model
all:
	python pipeline.py all

model:
	python pipeline.py model

clean:
	rm -f warehouse.sqlite report.xlsx summary.pptx scorecard.json MODEL_REVIEW.md dq_report_*.csv
	rm -rf tableau_extracts
