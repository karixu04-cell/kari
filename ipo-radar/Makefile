.PHONY: setup setup-ollama scan scan-all dashboard scheduler \
       start start-gpu start-cpu stop logs build \
       test lint clean help

# -------------------------------------------------------
# Local Setup
# -------------------------------------------------------

setup:  ## Install all dependencies (local)
	pip install -e ".[dev]" 2>/dev/null || pip install -e . 2>/dev/null || \
	pip install schedule python-dotenv requests pandas yfinance streamlit plotly

setup-ollama:  ## Pull the Qwen3-8B model for sentiment analysis
	ollama pull qwen3:8b

# -------------------------------------------------------
# Local Run
# -------------------------------------------------------

scan:  ## Run a single scan on the watchlist
	python -m src.scorer $(TICKERS)

scan-all:  ## Run all scheduled tasks once
	python -m src.scheduler --once

dashboard:  ## Start the Streamlit dashboard (local)
	streamlit run src/dashboard/app.py

scheduler:  ## Start the background scheduler (local)
	python -m src.scheduler

# -------------------------------------------------------
# Docker
# -------------------------------------------------------

build:  ## Build Docker image
	docker compose build

start:  ## Start core services (dashboard + scheduler)
	docker compose up -d

start-gpu:  ## Start all services including Ollama with GPU
	docker compose --profile gpu up -d

start-cpu:  ## Start all services including Ollama on CPU
	docker compose --profile cpu up -d

stop:  ## Stop all services
	docker compose --profile gpu --profile cpu down

logs:  ## Tail logs for all services
	docker compose logs -f

# -------------------------------------------------------
# Development
# -------------------------------------------------------

test:  ## Run tests
	python -m pytest tests/ -v

lint:  ## Run linter
	ruff check src/ tests/

clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info

# -------------------------------------------------------
# Help
# -------------------------------------------------------

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
