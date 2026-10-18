# Build from the repository root: docker build -f services/api/Dockerfile .
#
# The API imports pbpk_domain, modeler_contracts, modeler_intake, modeler_project and modeler_agents, and the
# orchestrator lazily (campaign launch, escalation decisions), so the image installs the whole locked workspace,
# exactly as the server does (`uv sync --all-packages`, deploy/dev/deploy_to_server.sh). uv is pinned to CI's version.
#
# Nothing here is pulled from Docker Hub (its outages and pull limits stopped CI on 2026-10-09): the builtin
# Dockerfile frontend replaces `# syntax=docker/dockerfile:1.7` (no feature of 1.7 is used), and the base is the
# Docker official python image as Google's mirror serves it. AWS ECR Public, used before, answered "429 Data limit
# exceeded" to GitHub's runners four times on 2026-10-18; both mirrors serve the same image digest for this tag
# (sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 on that day).
FROM mirror.gcr.io/library/python:3.12-slim

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
