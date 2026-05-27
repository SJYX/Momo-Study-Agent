# Conflict Reconciliation — sync_status=2 Diagnostic & Auto-fix

**Date:** 2026-05-27
**Status:** Draft (pending user review)

## Goal

For all records where `sync_status=2` (CONFLICT), determine whether the conflict is real or a false positive:
- If local content matches cloud content → auto-fix to `sync_status=1` (SYNCED)
- If content genuinely differs → leave as `sync_status=2`, log details for visibility

## Approach: Hybrid (Two Phases)

### Phase 1 — Local-only check (zero API cost)

Query all `sync_status=2` records from `ai_word_notes`. For each:
- If `last_synced_content` exists AND equals `basic_meanings` (normalized) → update to `sync_status=1`
- These are "stuck" conflicts where sync actually succeeded but the status was never updated

**Why this works:** `last_synced_content` is written at sync time with the text that was pushed to Maimemo. If it matches `basic_meanings` now, nothing has changed locally — the cloud should be in sync too.

### Phase 2 — Maimemo API comparison (for remaining conflicts)

For records still at `sync_status=2` after Phase 1:
1. Call `MaimemoAPI.list_interpretations(voc_id)` to fetch cloud interpretations
2. Use existing `_classify_interpretation_list()` to compare cloud text vs `basic_meanings`
3. If matched (similarity >= 0.95) → update to `sync_status=1`
4. If mismatch → leave at `sync_status=2`, log the diff

**Reuses existing code:** `_classify_interpretation_list` already has the normalization + similarity logic built in.

## Architecture

### New file: `tools/reconcile_conflicts.py`

A standalone CLI script. No changes to production code paths.

```
tools/reconcile_conflicts.py
├── main()              — entry point, arg parsing, orchestrates both phases
├── phase1_local_fix()  — SQL query + local comparison + write updates
├── phase2_api_check()  — API calls + similarity comparison + write updates
└── helpers             — DB access, Maimemo client init, logging
```

### Data flow

```
ai_word_notes (sync_status=2)
    │
    ├─ Phase 1: local check
    │   ├─ last_synced_content == basic_meanings? → SET sync_status=1
    │   └─ otherwise → keep sync_status=2, pass to Phase 2
    │
    └─ Phase 2: Maimemo API
        ├─ list_interpretations(voc_id) → cloud interpretations
        ├─ _classify_interpretation_list(cloud, basic_meanings)
        │   ├─ matched/similar (>=0.95) → SET sync_status=1
        │   └─ mismatch → keep sync_status=2, log diff
        └─ Rate limiting: 0.3s between API calls
```

### DB update mechanism

Use `database.notes_repo.set_note_sync_status()` — this is the existing function that updates `sync_status`, `match_confidence`, and `match_reason` through the write queue (dispatch_write).

**Important:** The script runs outside the normal app process, so we need to either:
- (A) Initialize the DB connection directly (simple, for one-off scripts)
- (B) Use the standard write queue (requires init_db + concurrent system init)

**Choice: (A) Direct connection** — this is a one-off diagnostic tool, not a production feature. Using `sqlite3.connect` directly avoids the overhead of initializing the full concurrent system. We write to both local and cloud if dual-mode is configured.

### CLI interface

```bash
# Dry run — show what would change, no writes
python -m tools.reconcile_conflicts --user <username> --dry-run

# Execute — Phase 1 only (fast, no API calls)
python -m tools.reconcile_conflicts --user <username> --phase1-only

# Execute — both phases
python -m tools.reconcile_conflicts --user <username>

# Verbose output
python -m tools.reconcile_conflicts --user <username> -v
```

### Output format

```
=== Conflict Reconciliation ===
User: <username>
DB: data/history-<username>.db

--- Phase 1: Local comparison ---
Found 42 conflict records
  [FIXED] voc_id=12345 "abandon" — last_synced_content matches basic_meanings
  [FIXED] voc_id=67890 "zeal" — last_synced_content matches basic_meanings
  [SKIP]  voc_id=11111 "hello" — last_synced_content missing
Phase 1 result: 2 fixed, 40 need API check

--- Phase 2: Maimemo API comparison ---
  [SYNCED] voc_id=11111 "hello" — cloud matches (confidence=1.0000)
  [CONFLICT] voc_id=22222 "world" — cloud differs (confidence=0.3200)
  ...
Phase 2 result: 35 auto-fixed, 5 remain in conflict

=== Summary ===
Total conflicts: 42
Fixed (Phase 1): 2
Fixed (Phase 2): 35
Still conflicting: 5
```

## Files to create/modify

| File | Action | Notes |
|------|--------|-------|
| `tools/reconcile_conflicts.py` | **CREATE** | Main script (~150 lines) |

No existing production code changes needed.

## Edge cases

1. **No Maimemo token** — Phase 2 is skipped with a warning; Phase 1 still runs
2. **Rate limiting** — 0.3s delay between API calls; `MaimemoAPI` already has rate limiting built in
3. **Network errors** — log and skip individual records; don't abort the whole run
4. **Empty `basic_meanings`** — skip (these should be `sync_status=5` anyway)
5. **Large conflict sets** — print progress every 50 records

## Testing

Manual verification with `--dry-run` first, then execute against a single user's test DB before running on production data.

## Out of scope

- Web UI button (user chose CLI only)
- Automatic retry of remaining conflicts (that's the existing `/api/sync/retry` endpoint)
- Schema changes or new states
