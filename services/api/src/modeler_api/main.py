"""Modeler One API (v1): the app, its middleware and its routers.

The system routes (health, snapshot preview F-101, M15 validation F-401, run submission F-102) are in
``modeler_api.system_api``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modeler_api.brief_api import router as brief_router
from modeler_api.campaign_api import router as campaign_router
from modeler_api.client_api import router as client_router
from modeler_api.config import get_settings
from modeler_api.escalations import router as escalations_router
from modeler_api.evidence_api import router as evidence_router
from modeler_api.inputs_api import router as inputs_router
from modeler_api.plan_api import router as plan_router
from modeler_api.project_api import router as project_router
from modeler_api.read_api import router as read_router
from modeler_api.requirements_api import router as requirements_router
from modeler_api.results_api import router as results_router
from modeler_api.signatures_api import router as signatures_router
from modeler_api.system_api import router as system_router
from modeler_api.templates_api import router as templates_router
from modeler_api.write_api import router as write_router
from modeler_contracts.runtime import runtime_env


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # A production deployment (MODELER_DEPLOYMENT=production) refuses to start without its engine settings: no default
    # engine, no placeholder digest, an explicit object store (modeler_contracts.runtime).
    runtime_env().check_production()
    yield


app = FastAPI(title="Modeler One API", version="0.1.0", lifespan=_lifespan)

# The web app calls the API directly from the browser for client-side writes (a separate origin), so CORS is
# part of the single-node stack. Explicit origins in production; any localhost origin under dev auth. Read once, when
# uvicorn imports `modeler_api.main:app` (the one read outside a request; it goes through the same seam).
_cors = get_settings()
_origins = [o.strip() for o in _cors.cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
elif _cors.dev_auth:
    # dev only: any origin (localhost, 127.0.0.1, a LAN/Tailscale IP). Safe because auth is bearer-token, not
    # cookie-based, so allow_credentials stays false. Set MODELER_CORS_ORIGINS explicitly outside dev.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(escalations_router)
app.include_router(signatures_router)
app.include_router(campaign_router)
app.include_router(results_router)
app.include_router(read_router)
app.include_router(write_router)
app.include_router(templates_router)
app.include_router(project_router)
app.include_router(brief_router)
app.include_router(requirements_router)
app.include_router(evidence_router)
app.include_router(client_router)
app.include_router(inputs_router)
app.include_router(plan_router)
app.include_router(system_router)
