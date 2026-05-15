"""core/word_models.py: 标准化单词数据模型。

WordItem 是系统内"单词"的统一形态，吸收 3 类来源的字段歧义：

1. 云端 raw item（maimemo_api.get_today_items / query_study_records 返回）
   - `voc_id` | `id`
   - `voc_spelling` | `spelling`
   - `voc_meanings` | `meanings` | `voc_meaning`
   - `short_term_familiarity` | `familiarity_short`
2. DB 行（ai_word_notes / processed_words / word_progress_history 行字典）
3. 前端 payload（Web 请求体）

所有调用方不再手动处理字段歧义；只调 `from_cloud_raw` / `from_db_row`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class WordItem:
    """单一来源的单词数据载体。轻量 dataclass，不引入 pydantic。"""

    voc_id: str
    spelling: str
    meanings: str = ""
    review_count: int = 0
    short_term_familiarity: float = 0.0

    @classmethod
    def from_cloud_raw(cls, raw: Dict[str, Any]) -> Optional["WordItem"]:
        """从云端 raw item 构造。

        返回 None 表示 raw 缺关键字段（voc_id 或 spelling），调用方应跳过。
        统一替代散落在 study_workflow / study_flow / study router 的手工字段兼容。
        """
        if not raw or not isinstance(raw, dict):
            return None

        voc_id = str(raw.get("voc_id") or raw.get("id") or "").strip()
        spelling = str(raw.get("voc_spelling") or raw.get("spelling") or "").strip()
        if not voc_id or not spelling:
            return None

        meanings = str(
            raw.get("voc_meanings")
            or raw.get("meanings")
            or raw.get("voc_meaning")
            or ""
        )

        try:
            # 兼容性：优先从 review_count 读取，其次从 study_count (query_study_records 接口) 读取
            review_count = int(raw.get("review_count") or raw.get("study_count") or 0)
        except (TypeError, ValueError):
            review_count = 0


        try:
            stf = float(
                raw.get("short_term_familiarity")
                or raw.get("familiarity_short")
                or 0.0
            )
        except (TypeError, ValueError):
            stf = 0.0

        return cls(
            voc_id=voc_id,
            spelling=spelling,
            meanings=meanings,
            review_count=review_count,
            short_term_familiarity=stf,
        )

    @classmethod
    def from_cloud_raw_batch(cls, raw_items: Iterable[Dict[str, Any]]) -> List["WordItem"]:
        """批量便捷方法。自动跳过 from_cloud_raw 返回 None 的脏数据项。"""
        out: List[WordItem] = []
        for raw in raw_items or []:
            item = cls.from_cloud_raw(raw)
            if item is not None:
                out.append(item)
        return out

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "WordItem":
        """从 DB 行（dict 形式）构造。

        约定字段：voc_id / spelling / basic_meanings | meanings /
                  review_count / familiarity_short
        """
        if not row:
            return cls(voc_id="", spelling="")
        return cls(
            voc_id=str(row.get("voc_id") or ""),
            spelling=str(row.get("spelling") or ""),
            meanings=str(row.get("basic_meanings") or row.get("meanings") or ""),
            review_count=int(row.get("review_count") or 0),
            short_term_familiarity=float(row.get("familiarity_short") or 0.0),
        )

    def to_processed_tuple(self) -> Tuple[str, str]:
        """给 progress_repo.mark_processed_batch 用的 (voc_id, spelling) 入参形态。"""
        return (self.voc_id, self.spelling)

    def to_payload(self) -> Dict[str, Any]:
        """给 study_workflow.process_word_list 的 ai_results 配对用的字典形态。

        历史 process_word_list 内部直接 dict-indexing `w["voc_id"]` / `w["voc_spelling"]`，
        过渡期保持同 key 兼容。
        """
        return {
            "voc_id": self.voc_id,
            "voc_spelling": self.spelling,
            "voc_meanings": self.meanings,
            "review_count": self.review_count,
            "short_term_familiarity": self.short_term_familiarity,
        }


__all__ = ["WordItem"]
