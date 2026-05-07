from __future__ import annotations
"""
database/sql_constants.py: 集中维护跨 repo 复用的 SQL 字符串与字段列表常量。

边界：
- 仅放被多处引用、或长度/复杂度足以构成维护负担的 SQL。
- 极简一次性 SQL（如 `SELECT 1 FROM ... WHERE voc_id=?`）继续在调用处就近书写。
- 修改这里的常量等同于改 schema 调用面 —— 必须配合下游测试。
"""


# ---------------------------------------------------------------------------
# ai_word_notes
# ---------------------------------------------------------------------------

#: 23 个字段的 upsert，由 build_note_upsert_args() 组装参数。
NOTE_UPSERT_SQL = (
    "INSERT OR REPLACE INTO ai_word_notes ("
    "voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, "
    "example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, "
    "total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, "
    "content_source_scope, sync_status, updated_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

#: 18 个字段，未同步笔记列表查询。与 UNSYNCED_NOTE_COLUMNS 一一对应。
UNSYNCED_NOTES_SELECT_SQL = (
    "SELECT voc_id, spelling, basic_meanings, ielts_focus, collocations, "
    "traps, synonyms, discrimination, example_sentences, memory_aid, "
    "word_ratings, raw_full_text, batch_id, original_meanings, "
    "maimemo_context, it_level, updated_at, content_origin "
    "FROM ai_word_notes "
    "WHERE sync_status = 0 "
    "AND (content_origin IS NULL OR content_origin = 'ai_generated') "
    "ORDER BY updated_at ASC"
)

UNSYNCED_NOTE_COLUMNS = [
    "voc_id", "spelling", "basic_meanings", "ielts_focus", "collocations",
    "traps", "synonyms", "discrimination", "example_sentences", "memory_aid",
    "word_ratings", "raw_full_text", "batch_id", "original_meanings",
    "maimemo_context", "it_level", "updated_at", "content_origin",
]


# ---------------------------------------------------------------------------
# ai_batches
# ---------------------------------------------------------------------------

AI_BATCH_INSERT_SQL = (
    "INSERT OR REPLACE INTO ai_batches ("
    "batch_id, request_id, ai_provider, model_name, prompt_version, "
    "batch_size, total_latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason, created_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


# ---------------------------------------------------------------------------
# ai_word_iterations
# ---------------------------------------------------------------------------

AI_WORD_ITERATION_INSERT_SQL = (
    "INSERT INTO ai_word_iterations ("
    "voc_id, spelling, stage, it_level, score, justification, tags, "
    "refined_content, candidate_notes, raw_response, maimemo_context, batch_id"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


# ---------------------------------------------------------------------------
# processed_words / word_progress_history
# ---------------------------------------------------------------------------

PROCESSED_UPSERT_SQL = (
    "INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)"
)

PROGRESS_INSERT_SQL = (
    "INSERT INTO word_progress_history "
    "(voc_id, familiarity_short, familiarity_long, review_count, it_level) "
    "VALUES (?, ?, ?, ?, ?)"
)


# ---------------------------------------------------------------------------
# system_config
# ---------------------------------------------------------------------------

SYSTEM_CONFIG_UPSERT_SQL = (
    "INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)"
)


# ---------------------------------------------------------------------------
# 跨库查找：(notes JOIN batches) 的 SELECT 模板
# ---------------------------------------------------------------------------

#: placeholders 由调用方按 IN 子句长度填入。
COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE = (
    "SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version "
    "FROM ai_word_notes n "
    "LEFT JOIN ai_batches b ON n.batch_id = b.batch_id "
    "WHERE n.voc_id IN ({placeholders})"
)
