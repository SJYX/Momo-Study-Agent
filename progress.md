# Progress — Embedded Replica Cleanup (Protocol Abstraction)

## Session 2026-05-20 — Initial Planning

### What we did
1. User requested cleanup of embedded replica (libsql) architecture code, now that pyturso is working
2. Explored the codebase: `connection.py` (1255 lines), `execution_engine.py` (503 lines), `sync_service.py` (245 lines)
3. Identified key differences between libsql and pyturso backends:
   - Connection creation: `_connect_embedded_replica()` vs `_connect_turso_sync()`
   - Sync API: `conn.sync()` vs `push()→pull()→checkpoint()`
   - Scattered `hasattr(conn, "pull")` dispatch in 5+ locations
4. Proposed 3 approaches:
   - A: Minimal extraction (no abstraction)
   - B: Protocol abstraction layer (recommended)
   - C: Middle-ground with centralized dispatch
5. User chose **方案 B** (Protocol abstraction)
6. Created planning files: `findings.md`, `task_plan.md`, `progress.md`

### Key constraints identified
- libsql CANNOT be removed (pyturso Windows compilation too complex)
- V007 migration MUST be kept (only "asher" migrated; other users auto-migrate on first connect)
- pyturso is preferred default when available
- Target: reduce `connection.py` from 1255 → ~400 lines

### Next steps
- Task 1: Create `database/backends/` package with Protocol
- Task 2: Implement LibsqlBackend
- Task 3: Implement PytursoBackend
- Task 4–6: Refactor consumers (connection.py, sync_service.py, execution_engine.py)
- Task 7–8: Update legacy.py + write tests
- Task 9: Full regression

### Session 2026-05-20 — Implementation (continued)

#### Task 4 (connection.py) Review
- Spec compliance: ✅ Pass (with 1 test fix needed)
- Code quality: Thread-unsafe `_get_backend()` fixed with `threading.Lock`
- Test fix: `test_robustness.py` updated to patch `HAS_PYTURSO=False` + reset `_backend` singleton

#### Task 5: Refactor sync_service.py
- Implementer: Replaced 2 hasattr dispatch blocks with `get_active_backend().do_sync_on(conn)`
- Cached `get_active_backend()` in local variable to avoid double-call
- Spec review: ✅ Pass
- Code quality: ✅ Pass

#### Task 6: Refactor execution_engine.py
- Implementer: Removed pre-sync guard, replaced 2 hasattr dispatch blocks with `get_active_backend().do_sync_on(conn)`
- Spec review: ✅ Pass
- Code quality: ✅ Pass

#### Task 7: Update legacy.py
- Added `from .backends import get_active_backend, TursoBackend` re-export

#### Task 8: Unit tests for Protocol
- Created `tests/unit/database/backends/test_protocol.py` with 6 tests
- All 6 pass: protocol check, is_supported, duck-type safety, preference, no circular import

#### Task 9: Full regression
- 484 passed, 24 failed (all pre-existing), 3 skipped, 1 xpassed

#### Line Counts
| File | Before | After | Change |
|------|--------|-------|--------|
| connection.py | 1255 | 918 | -337 |
| execution_engine.py | 503 | 492 | -11 |
| sync_service.py | 245 | 236 | -9 |
| **New files** | | **495** | backends/ (288+169+24+14) |
| Total | 2003 | 1685 | -318 net |

### Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Task 4 test: `db_connection.libsql` missing | 1 | Patch `HAS_PYTURSO=False` + reset `_backend` singleton |
| Thread-unsafe `_get_backend()` singleton | 1 | Added `threading.Lock` double-checked locking |
