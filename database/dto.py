from __future__ import annotations
"""
database/dto.py: repo 层 TypedDict 类型，降低字典魔法字段维护成本。

边界：
- 仅描述 repo 之间或 repo→上层经常传递的字典形状。
- TypedDict total=False，因为多数字段在不同写入路径下可缺省。
- 不强制运行时校验；这是文档/IDE 友好的注解层。
"""

from typing import Any, Dict, List, Optional, TypedDict, Union


class NotePayload(TypedDict, total=False):
    """build_note_upsert_args() 的 payload 入参。"""
    spelling: str
    basic_meanings: str
    ielts_focus: str
    collocations: str
    traps: str
    synonyms: str
    discrimination: str
    example_sentences: str
    memory_aid: str
    word_ratings: str
    raw_full_text: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    original_meanings: Optional[str]
    content_origin: Optional[str]
    content_source_db: Optional[str]
    content_source_scope: Optional[str]


class NoteMetadata(TypedDict, total=False):
    """build_note_upsert_args() 的 metadata 入参。"""
    batch_id: Optional[str]
    maimemo_context: Optional[Dict[str, Any]]
    original_meanings: Optional[str]
    content_origin: Optional[str]
    content_source_db: Optional[str]
    content_source_scope: Optional[str]


class BatchNoteEntry(TypedDict, total=False):
    """save_ai_word_notes_batch() 的列表元素形状。"""
    voc_id: Union[str, int]
    payload: NotePayload
    metadata: NoteMetadata


class IterationPayload(TypedDict, total=False):
    """save_ai_word_iteration() 的 payload 入参。"""
    spelling: Optional[str]
    stage: Optional[str]
    it_level: Optional[int]
    score: Optional[float]
    justification: Optional[str]
    tags: Optional[List[str]]
    refined_content: Optional[str]
    candidate_notes: Optional[str]
    raw_response: Optional[str]
    raw_full_text: Optional[str]


class AIBatchData(TypedDict, total=False):
    """save_ai_batch() 的入参。"""
    batch_id: str
    request_id: Optional[str]
    ai_provider: Optional[str]
    model_name: Optional[str]
    prompt_version: Optional[str]
    batch_size: int
    total_latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: Optional[str]


class ProgressSnapshot(TypedDict, total=False):
    """log_progress_snapshots() 的列表元素形状。"""
    voc_id: Union[str, int]
    short_term_familiarity: float
    long_term_familiarity: float
    voc_familiarity: float
    review_count: int


class SyncStats(TypedDict, total=False):
    """sync_databases() / sync_hub_databases() 的返回值。"""
    upload: int
    download: int
    status: str          # ok / skipped / error
    reason: str
    frames_synced: int
    duration_ms: int
