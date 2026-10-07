"""Modeler One storage (L2, docs/ARCHITECTURE_BOUNDARIES.md): the persistence the API and the orchestrator share.

The Postgres audit trail (`audit`), the file-backed campaign read model (`filestore`) and the database repositories
(`db`, `tenancy`). Imports only `pbpk_domain` and SQLAlchemy: never the API or the orchestrator.
"""
