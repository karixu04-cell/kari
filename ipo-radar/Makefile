.PHONY: setup scan dashboard scheduler start stop test lint clean

# -------------------------------------------------------
# Setup
# -------------------------------------------------------

setup:  ## Install all dependencies
	pip install -e ".[dev]" 2>/dev/null || pip install -r requirements.txt 2>/dev/null || \
	pip install schedule python-dotenv requests pandas yfinance streamlit plotly

setup-ollama:  ## Pull the Qwen3-8B model for local sentiment analysis
	ollama pull qwen3:8b

# -------------------------------------------------------
# Run tasks
# -------------------------------------------------------

scan:  ## Run a single scan on the watchlist
	python -m src.scorer $(TICKERS)

scan-all:  ## Run all scheduled tasks once
	python -m src.scheduler --once

dashboard:  ## Start the Streamlit dashboard
	streamlit run src/dashboard/app.py

scheduler:  ## Start the background scheduler
	python -m src.scheduler

# -------------------------------------------------------
# Docker
# -------------------------------------------------------

start:  ## Start all services (dashboard + scheduler + ollama)
	docker compose up -d

stop:  ## Stop all services
	docker compose down

start-no-gpu:  ## Start without GPU (ollama uses CPU)
	docker compose up -d --scale ollama=0
	docker compose up -d ollama || true

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
