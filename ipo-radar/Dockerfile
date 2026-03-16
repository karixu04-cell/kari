FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Python deps (install from pyproject.toml)
COPY pyproject.toml ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main || true

# Extra runtime deps not in pyproject.toml
RUN pip install --no-cache-dir plotly

# Copy source
COPY . .

ENV PYTHONPATH=/app
EXPOSE 8501
