# Part 11 records in PostgreSQL (production readiness P2, 2026-10-15)

Status: **built** (2026-10-15, branch `part11-postgres`). The owner approved the plan, including the changes to locked files, on 2026-10-15. Builds on
P1 (`deploy/server/postgres.sh`, #63).

## Why
A production deployment signs Part 11 records with the Keycloak step-up (K1–K3). Today its audit trail and signatures
live only in files that the server account can edit: the hash chain in `<read_root>/<tenant>/audit.jsonl`, and
signatures inside the records they sign. The chain shows a tampered line, but nothing stops a whole rewritten chain.
PostgreSQL (P1) holds rows the API's own login cannot change or remove: the `reject_mutation` triggers, and no
UPDATE/DELETE/TRUNCATE grant.

## What is decided
1. **The database holds a copy of every audit event, written synchronously.**
   - `AuditLog.append` (`modeler_project/audit.py`) calls an injected mirror inside its file lock, *before* the line
     is written. If the database refuses, nothing is written and the action fails. No event exists only in the file.
   - **Gaps are filled from the file chain first.** If the database is behind (the first event after the switch, or a
     past outage), the mirror copies the missing records in order before the new one. The pilot's history then reaches
     the database intact, with its original hashes.
   - The file chain stays the application's read model. The database is the copy the API cannot alter.
2. **The hashes are the file chain's, unchanged.** A row stores the file record's `prev_hash` and `row_hash`, and is
   verified against the event with the tenant's *name*. The file chain hashes `tenant_id = "dev"`, not a UUID.
   - Tenant names map to the schema's UUID keys through `tenants.slug`, created on first use (`onprem-single`).
   - `modeler_storage.audit.append_audit_event`, which hashes the UUID, stays for the distributed path. It is not
     used here.
3. **Every signature is a row.**
   - The three sign points in use are `signatures_api`, `plan_api` approve and the local escalation resolve. Each
     writes the `Signature` right after `sign_after_step_up`, before the decision is applied. That is the order the
     code already keeps, because every refusal is checked before the signature is taken.
   - The signer is upserted into `users` by token subject, with the printed name.
   - The Temporal-path routes (`sign_record` with a password verifier) are not deployed and are not changed.
4. **Migration `0004_part11_records.sql`** (a new file; applied migrations are never edited). It fits the schema to
   the records as they are:
   - `signatures.record_id` becomes text, because records are named like `camp-x-S2` and `map-1`;
   - `users.email` becomes nullable, because a sign-in token may carry none.
5. **Production needs it.** `MODELER_PART11_STORE=postgres` with `MODELER_DATABASE_URL`, both printed by
   `postgres.sh env`. A production deployment refuses to start without them (`modeler_api.config`). Pilot and
   development keep the files only.
6. **Verification:** `python -m modeler_api.part11 verify` checks each tenant. Every file record must be in the
   database with the same hashes, and the database chain must recompute. A rewritten file chain then shows up against
   the database copy. The nightly backup runs it (`postgres.sh`).

## Locked files changed (each named in the CHANGELOG, hashes refreshed)
- `packages/project-model/src/modeler_project/audit.py` and `store.py`: the injected mirror;
- `services/api/migrations/0004_part11_records.sql`: new;
- `services/api/src/modeler_api/compliance/signatures.py`: untouched; the sign points call the recorder.

## Tests
- **The mirror** (against PostgreSQL 16, run as an ordinary account):
  - events reach the database with identical hashes;
  - a gap is backfilled in order;
  - a database refusal leaves the file untouched;
  - a tampered file line is reported by `verify`;
  - the API's login cannot rewrite a row.
- **The sign points:** a signature row per signed decision, MAP approval and signature request.
- **The API:** production refuses to start without the Part 11 store, and pilot does not need it.
