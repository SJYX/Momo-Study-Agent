# database Package Architecture

This package splits the old `db_manager.py` into clear layers while preserving runtime behavior and improving safety in Embedded Replica mode.

## Why This Refactor

The previous single-file design mixed:

- connection infrastructure
- migration/schema code
- hub user business logic
- word/note business logic
- utility helpers

This made it easy to accidentally re-introduce unsafe connection patterns and hard to reason about WAL behavior.

## Module Boundaries

### 1) `database/connection.py`

Responsibilities:

- Connection lifecycle and context resolution
- Embedded Replica connect/retry logic
- Main DB and Hub DB singleton write connections
- Writer queue and background writer thread
- Background sync daemon
- Managed connection execution helpers
- Hub read helpers (`_hub_fetch_one_dict`, `_hub_fetch_all_dicts`)

Non-responsibilities:

- No business rules about users/words
- No schema DDL ownership (only callback registration/dispatch)

### 2) `database/utils.py`

Responsibilities:

- Secret encryption/decryption
- Text cleaning helpers (`clean_for_maimemo`)
- Error classification helpers
- Hash/fingerprint helpers
- Prompt hash/archive helpers
- Cloud target discovery/caching helpers
- Generic throttled logging helper utilities

### 3) `database/schema.py`

Responsibilities:

- Main schema creation and migration (`_create_tables`)
- Hub schema creation (`_init_hub_schema`)
- Initialization entrypoints (`init_db`, `init_users_hub_tables`)
- Table-existence and init-marker caching logic
- Hub init state persistence/cache

Notes:

- `schema.py` registers schema initializer callbacks into `connection.py`.
- This keeps dependency direction one-way (schema -> connection), avoiding circular imports.

### 4) `database/hub_users.py`

Responsibilities:

- Hub user profile CRUD-like operations
- Hub credential save/read (encrypted fields)
- Session/statistics updates
- Admin action logging and listing
- Hub user status operations

Dependencies:

- Reads/writes via `connection.py`
- Crypto/time helpers via `utils.py`

### 5) `database/momo_words.py`

Responsibilities:

- Main DB word/note business operations
- Processed status operations
- Progress snapshot operations
- Unsynced note retrieval/recovery paths
- Community batch lookup helpers
- Config read/write wrappers
- Sync wrapper functions (`sync_databases`, `sync_hub_databases`)

Dependencies:

- DB access via `connection.py`
- Utility helpers via `utils.py`
- Schema callbacks/helpers where needed

## Critical Safety Rule: Embedded Replica Single Connection Rule

This rule is mandatory.

In Embedded Replica mode, for the same replica file:

- Do NOT open extra libsql connections for read paths.
- Do NOT keep thread-local read connections.
- Do NOT create any additional `libsql.connect(local_replica_path)` handles alongside the active syncing singleton.

### Required Behavior

- Main DB reads and writes must reuse the process singleton:
  - `_get_main_write_conn_singleton(...)`
- Hub DB reads and writes must reuse the process singleton:
  - `_get_hub_write_conn_singleton(...)`
- `_get_read_conn_impl(...)` must return main singleton in Embedded Replica mode.
- Hub fetch helpers must read through hub singleton.

### Forbidden Patterns

- ThreadLocal read connection caches for libsql replicas
- `_get_libsql_local_read_conn(...)` style APIs for primary replica files
- Any code path that opens a second live connection to the same syncing replica file

## WalConflict Root Cause Summary

`WalConflict` appears when multiple libsql connection instances compete on the same replica file while one is actively syncing WAL frames. The Rust core enforces strict file-level synchronization assumptions that are violated by multi-instance access.

The fix is architectural, not just retry-based:

- one replica file
- one live libsql connection singleton
- all operations serialized via connection-level locks and/or queueing

## Dependency Direction (No Circular Imports)

Recommended import direction:

- `utils` -> independent
- `connection` -> may import from `utils`
- `schema` -> imports `connection` + `utils`
- `hub_users` -> imports `connection` + `utils` (+ `schema` entrypoint where needed)
- `momo_words` -> imports `connection` + `utils` (+ `schema` helpers where needed)

Avoid reverse imports (e.g. `connection` importing `hub_users` or `momo_words`).

## Operational Notes

- Writer queue serializes write operations to reduce lock contention.
- Sync daemon performs debounce-style background sync for main DB singleton.
- Local corruption recovery keeps WAL sidecar files untouched to avoid unsafe deletion behavior.

## Migration Checklist for Future Changes

Before merging DB-related changes, verify:

- No new ThreadLocal read connection logic exists for Embedded Replicas.
- No helper opens extra libsql local connections to active replica files.
- `_get_read_conn_impl` still funnels to main singleton in cloud mode.
- Hub reads still use hub singleton.
- New business modules only depend on `connection/utils/schema` and do not redefine connection logic.
