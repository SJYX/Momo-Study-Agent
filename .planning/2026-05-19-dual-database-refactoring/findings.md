# Findings — Dual-Database Refactoring

## Codebase Analysis (2026-05-19)

### Current AI Processing Flow
- `study_workflow.py` processes words in **batches**: `_run_ai_batch` calls `ai_client.generate_mnemonics(batch_spells)` for an entire batch at once
- After AI returns, `_process_results` iterates batch results and calls `save_ai_word_notes_batch` to persist
- There is **no per-word lookup** in the current flow — all words go straight to AI

### notes_repo.py Structure
- **No `update_memory_aid` function exists** — will create new
- `build_note_upsert_args` assembles 25-tuple for `NOTE_UPSERT_SQL`
- `NOTE_UPSERT_SQL` has 25 columns, no `is_customized`
- Schema in `schema.py` `ai_word_notes` table also lacks `is_customized`

### Migration System
- Existing migrations: V001 through V004 (runner auto-discovers files)
- Runner uses `system_config` table for version tracking (SSoT)
- Pattern: `V{NNN}_{descriptive_name}.py` with `apply(cur)` function
- Each migration wraps DDL in `BEGIN IMMEDIATE` / `commit`
- New migrations: **V005_is_customized** and **V006_seed_global_cache**

### Feature Flags
- `core/feature_flags.py`: `_KNOWN_FLAGS` set, `is_enabled()` reads from Settings
- `core/settings.py`: `Settings(BaseSettings)` model with pydantic-settings
- New flag: `GLOBAL_CACHE_ENABLED` (default `False`)

### Test Patterns
- `tests/conftest.py` has `autouse` fixture to isolate cloud config
- Unit tests use in-memory SQLite (`sqlite3.connect(":memory:")`) or MagicMock
- Migration tests use `_fresh_db()` + `_setup_skeleton()` helpers
- Tests run with `pytest tests/ -v --tb=short -m "not slow"`

### Key Files to Modify
| File | Change |
|------|--------|
| `core/word_lookup.py` | NEW — 3-level lookup orchestrator |
| `database/cache_client.py` | NEW — HTTP client for Global_Cache_DB |
| `database/migrations/V005_is_customized.py` | NEW — add `is_customized` column |
| `database/migrations/V006_seed_global_cache.py` | NEW — seed ai_cache table |
| `tests/unit/database/test_cache_client.py` | NEW — unit tests for cache client |
| `tests/unit/core/test_word_lookup.py` | NEW — unit tests for lookup orchestrator |
| `core/study_workflow.py` | MODIFY — add per-word lookup in batch |
| `database/notes_repo.py` | MODIFY — add `update_memory_aid` |
| `database/sql_constants.py` | MODIFY — add is_customized to SQL |
| `core/feature_flags.py` | MODIFY — register GLOBAL_CACHE_ENABLED |
| `core/settings.py` | MODIFY — add settings fields |
| `config.py` | MODIFY — add cache env vars |

### User Decisions
1. **Migration numbering**: Semantic naming (V005, V006)
2. **Integration granularity**: Batch-level, per-word lookup within batch; CacheNetworkError triggers batch-level circuit breaker
3. **is_customized marking**: Create new `update_memory_aid` function
