# Migration State Machine Design (Pre-Connect Only)

**Date:** 2026-05-20

## Goal
Guarantee that database format migration runs only before opening the database connection, never via legacy apply paths, and that failures are surfaced in a controlled, observable way with a health gate rather than silent continuation.

## Scope
- Affects pre-connect migration flow for pyturso and legacy V007 apply behavior.
- Introduces an explicit migration state machine and health gate.
- Adds migration serialization to avoid concurrent file mutation.

Out of scope:
- Data recovery workflows beyond existing backup and rebuild.
- Changes to libsql embedded replica behavior.

## Current Problem
- Legacy V007 apply can run after a database connection is opened, causing unsafe file operations.
- Migration failures can leave databases in partial states or continue startup without strong visibility.
- Concurrent access can cause delete/copy races and leave sidecars inconsistent.

## Design Overview
### 1) Explicit Migration State Machine
Define a migration result object with explicit states:
- `format`: `no_file` | `turso_sync` | `libsql_embedded_replica` | `unknown`
- `action`: `migrated` | `skipped` | `failed`
- `error`: optional string
- `db_path`: absolute path

This result is returned from `pre_connect_migrate()` and logged with structured fields.

### 2) Pre-Connect Only Enforcement (pyturso only)
- `database/backends/_pyturso.py` must always call `pre_connect_migrate()` before any connect.
- Migration executes only when the active backend is `pyturso` and the local database is detected as `libsql_embedded_replica`.
- `database/backends/_libsql.py` must not run any migration logic; libsql uses its own replica format.
- Any legacy `V007.apply()` must be a no-op with a warning log (no file mutation).

### 3) Health Gate
- If `pre_connect_migrate()` returns `failed`, the backend does not proceed with normal operation.
- The system should enter a controlled degraded state (e.g., API returns a specific error code) until migration succeeds or manual recovery occurs.

### 4) Migration Serialization
- Use a file lock or process-level mutex around migration operations to prevent simultaneous delete/rename of `.db` and sidecars.
- Lock should cover backup, sidecar cleanup, and pre-init schema steps.

### 5) Logging and Observability
Every migration attempt logs:
- db_path, format, action
- error message if action is `failed`
- timing metadata

Logs must be clear enough to trace exactly which branch executed.

## Data Flow
1. `start_web.py` -> `UserContextManager._warmup_sync()` -> `database.connection` -> `backend.connect()`
2. `backend.connect()` calls `pre_connect_migrate()`
3. `pre_connect_migrate()` returns explicit state result
4. Health gate enforces behavior based on result
5. Only after success does connection proceed

## Failure Handling
- Migration failure does not crash the process; it transitions to degraded state.
- Degraded state should be explicit: error responses with an actionable message.
- No write operations proceed until migration status is resolved.

## ER Format Detection Risk
Current ER format detection is vulnerable to sidecar naming mismatches (e.g., `.db-info` vs `-info`).
The migration state machine must normalize and check both forms to avoid false negatives that
misroute `libsql_embedded_replica` databases into the wrong branch.

## Testing Strategy
- Case A: `.db` exists + `.db-info` exists -> format detected as `libsql_embedded_replica` -> migration runs -> action `migrated`
- Case B: `.db` missing + sidecar exists -> format detected `no_file` or `unknown` -> action `skipped` (or `migrated` with backup), no exception
- Case C: Migration step raises exception -> action `failed`, health gate engaged, no connection open
- Case D: Legacy `V007.apply()` called -> log warning, no mutation
- Case E: Concurrent migration attempts -> serialized by lock

## Risks
- Health gate changes startup behavior: service may start in a degraded mode instead of running normally.
- Requires coordination with ops monitoring to recognize degraded state.

## Rollout Plan
1. Add migration state machine and logging.
2. Enforce pre-connect only and disable legacy apply.
3. Add health gate behavior.
4. Add tests for the above behaviors.

## Open Questions
- Where to surface the degraded state for web UI? (health endpoint or dedicated error endpoint)
- Should degraded mode allow read-only operations?
