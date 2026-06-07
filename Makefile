.PHONY: all test bundle submit

all: test bundle

test:
	@echo "Running local benchmark..."
	cd src && python3 benchmark.py

bundle:
	@echo "Bundling submission.tar.gz..."
	tar -czf submission.tar.gz main.py
	@echo "Bundle created. Ready for upload."

submit: bundle
	@echo "Submitting to Kaggle..."
	kaggle competitions submit maze-crawler -f submission.tar.gz -m "Professional Strategic Agent v1"
