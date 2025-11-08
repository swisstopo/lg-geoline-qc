# Variables
PLUGIN_DIR = GeoLinesQC
TESTS_DIR = tests
PYTHON = python3
RUFF = ruff
ISORT = isort

VERSION := $(shell python3 -c 'import setuptools_scm; print(setuptools_scm.get_version())')



# Default target
all: lint format

# Install dependencies
install:
	$(PYTHON) -m pip install -r requirements.txt

# Run tests
test:
	$(PYTHON) -m pytest $(TESTS_DIR)

# Format code with isort
format:
	$(ISORT) $(PLUGIN_DIR) $(TESTS_DIR)
	$(RUFF) format $(PLUGIN_DIR) $(TESTS_DIR)

# Lint code with ruff
lint:
	$(RUFF) check $(PLUGIN_DIR) $(TESTS_DIR)

# Fix linting errors with ruff
fix:
	$(RUFF) --fix $(PLUGIN_DIR) $(TESTS_DIR)

# Clean up temporary files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

# Run all checks (lint, format, test)
check: lint format test

plugin: clean
	python update_version.py "GeoLinesQC/metadata.txt" $(VERSION)
	zip -r GeoLinesQC.$(VERSION).zip GeoLinesQC/

.PHONY: all install test format lint fix clean check plugin
