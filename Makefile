# Variables
PLUGIN_DIR = GeoLinesQC
TESTS_DIR = tests
PYTHON = python3
RUFF = ruff
ISORT = isort

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

.PHONY: all install test format lint fix clean check