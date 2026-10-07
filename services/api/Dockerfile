# syntax=docker/dockerfile:1.7
# Build from the repository root: docker build -f services/api/Dockerfile .
#
# The API imports pbpk_domain, modeler_contracts, modeler_intake, modeler_project and modeler_agents, and the
# orchestrator lazily (campaign launch, escalation decisions), so the image installs the whole locked workspace,
# exactly as the server does (`uv sync --all-packages`, deploy/dev/deploy_to_server.sh). uv is pinned to CI's version.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --all-packages --no-editable

USER 10001
EXPOSE 8000
CMD ["uvicorn", "modeler_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
