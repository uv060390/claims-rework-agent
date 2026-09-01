FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY pipeline ./pipeline
COPY mocks ./mocks
COPY evals ./evals
RUN pip install --no-cache-dir .

COPY data/demo ./data/demo

# command supplied per-service in docker-compose.yml
