-- Part 11 records as the platform names them (production readiness P2, 2026-10-15; docs/plans/2026-10-15-part11-records-postgres.md).
-- Signed records are named by the platform (a MAP id, "<campaign>-<stage>" for an escalation), not by UUIDs, and a
-- sign-in token may carry no email. Earlier migrations are never edited: this one fits their tables.

ALTER TABLE signatures ALTER COLUMN record_id TYPE text;
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
