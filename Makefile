# Incident and Ticket Enrichment Copilot
#
# Every target here works without an LLM API key. `make check` is what CI runs.

PYTHON ?= python
VENV   ?= .venv

ifeq ($(OS),Windows_NT)
	BIN := $(VENV)/Scripts
else
	BIN := $(VENV)/bin
endif

PY   := $(BIN)/python
PIP  := $(PY) -m pip

.DEFAULT_GOAL := help
.PHONY: help venv install install-llm fmt lint typecheck test test-unit test-integration \
        test-e2e coverage check ingest run-alarm-api run-ticketing-api run-mcp run-backend \
        run-gui up down logs clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Environment -----------------------------------------------------------
venv: ## Create the virtual environment
	$(PYTHON) -m venv $(VENV)

install: venv ## Install the project and its dev dependencies (editable)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install-llm: ## Install the optional real-LLM provider SDKs
	$(PIP) install -e ".[llm]"

# --- Quality ---------------------------------------------------------------
fmt: ## Auto-fix formatting and import order
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

lint: ## Static analysis
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

typecheck: ## Type checking
	$(PY) -m mypy services connectors mcp-servers apps rag

# --- Tests -----------------------------------------------------------------
test: ## Run the whole suite
	$(PY) -m pytest

test-unit: ## Unit tests only
	$(PY) -m pytest -m unit

test-integration: ## Integration tests (includes the Postman chaining replay)
	$(PY) -m pytest -m integration

test-e2e: ## End-to-end MCP + RAG scenario
	$(PY) -m pytest -m e2e

coverage: ## Test suite with a coverage report
	$(PY) -m pytest --cov --cov-report=term-missing --cov-report=html --cov-report=xml

check: lint test ## What CI runs

# --- RAG -------------------------------------------------------------------
ingest: ## Build the retrieval index from rag/documents
	$(PY) -m rag.ingestion.cli --rebuild

# --- Run services locally (each in its own shell) --------------------------
run-alarm-api: ## Alarm Management API simulator on :8000
	$(PY) -m uvicorn alarm_api.main:app --host 0.0.0.0 --port 8000 --reload

run-ticketing-api: ## Mock ticketing API on :8100
	$(PY) -m uvicorn ticketing_api.main:app --host 0.0.0.0 --port 8100 --reload

run-mcp: ## MCP server on :9000 (also runnable over stdio)
	$(PY) -m alarm_mcp

run-backend: ## Copilot backend on :8080
	$(PY) -m uvicorn copilot.api.app:app --host 0.0.0.0 --port 8080 --reload

run-gui: ## Streamlit GUI on :8501
	$(BIN)/streamlit run apps/frontend/gui/app.py

# --- Docker ----------------------------------------------------------------
up: ## Build and start the whole stack
	docker compose up --build

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Tail all service logs
	docker compose logs -f

# --- Housekeeping ----------------------------------------------------------
clean: ## Remove caches, build artefacts and the retrieval index
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	rm -rf build dist *.egg-info .index
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
