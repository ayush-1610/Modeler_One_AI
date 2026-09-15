# syntax=docker/dockerfile:1.7
# Build from the repository root: docker build -f services/api/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY packages/pbpk-domain packages/pbpk-domain
COPY packages/run-contracts packages/run-contracts
COPY services/api services/api
RUN uv pip install --system ./packages/pbpk-domain ./packages/run-contracts ./services/api

USER 10001
EXPOSE 8000
CMD ["uvicorn", "modeler_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
