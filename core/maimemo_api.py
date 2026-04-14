# -*- coding: utf-8 -*-
"""
墨墨背单词 OpenAPI 封装调用库
基于官方文档: https://open.maimemo.com/document#/
"""

import requests
import time
import threading
from collections import deque
from typing import List, Dict, Optional, Union
from core.constants import MAIMEMO_NOTE_TAG_OPTIONS, MAIMEMO_NOTE_TAG_FALLBACK
try:
    from core.logger import get_logger
except ImportError:
    import logging
    def get_logger(): return logging.getLogger(__name__)

class MaiMemoAPI:
    def __init__(self, access_token: str):
        self.base_url = "https://open.maimemo.com/open/api/v1"
        self._session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.creation_limit_reached = False  # 标记是否已达到创建限制
        # 释义查询短缓存：避免同一 voc_id 在短时间内重复 GET
        self._interpretations_cache: Dict[str, Dict] = {}
        self._interpretations_cache_ts: Dict[str, float] = {}
        self._interpretations_cache_ttl = 180  # 秒
        # 自适应限速：按官方窗口进行请求节流（10s/20次, 60s/40次）
        self._req_ts_10s = deque()
        self._req_ts_60s = deque()
        # 最小间隔用于平滑突发，避免短时尖峰导致 429
        self._min_interval_sec = 0.12
        self._last_request_ts = 0.0
        self._rate_limit_lock = threading.Lock()

    def close(self):
        """释放底层 HTTP 连接，避免退出时资源告警。"""
        try:
            self._session.close()
        except Exception:
            pass

    def _apply_rate_limit(self):
        """根据墨墨频控窗口进行自适应节流，尽量减少 429 重试等待。"""
        with self._rate_limit_lock:
            now = time.time()

            # 清理窗口外时间戳
            while self._req_ts_10s and now - self._req_ts_10s[0] >= 10:
                self._req_ts_10s.popleft()
            while self._req_ts_60s and now - self._req_ts_60s[0] >= 60:
                self._req_ts_60s.popleft()

            wait_candidates = []
            if self._req_ts_10s and len(self._req_ts_10s) >= 20:
                wait_candidates.append(10 - (now - self._req_ts_10s[0]))
            if self._req_ts_60s and len(self._req_ts_60s) >= 40:
                wait_candidates.append(60 - (now - self._req_ts_60s[0]))

            # 平滑间隔，减少突发请求导致的额外限流
            gap = now - self._last_request_ts
            if gap < self._min_interval_sec:
                wait_candidates.append(self._min_interval_sec - gap)

            wait_time = max(wait_candidates) if wait_candidates else 0
            if wait_time > 0:
                time.sleep(wait_time)

            req_ts = time.time()
            self._req_ts_10s.append(req_ts)
            self._req_ts_60s.append(req_ts)
            self._last_request_ts = req_ts

    @staticmethod
    def _is_transient_status(status_code: int) -> bool:
        """判断是否属于可短暂重试的服务端错误。"""
        return status_code in {500, 502, 503, 504}

    @staticmethod
    def _normalize_note_tags(tags: Optional[List[str]]) -> List[str]:
        allowed = set(MAIMEMO_NOTE_TAG_OPTIONS)
        if not tags:
            return list(MAIMEMO_NOTE_TAG_FALLBACK)

        if isinstance(tags, str):
            tags = [tags]

        normalized: List[str] = []
        for tag in tags:
            text = str(tag).strip()
            if text in allowed and text not in normalized:
                normalized.append(text)

        return normalized or list(MAIMEMO_NOTE_TAG_FALLBACK)

    def _request(self, method: str, endpoint: str, **kwargs):
        """统一请求处理及限流"""
        url = f"{self.base_url}{endpoint}"

        # 单测通常会 patch `requests.request`；生产环境仍优先走 session 复用连接。
        request_impl = requests.request if requests.request.__class__.__module__ == "unittest.mock" else self._session.request

        # 添加重试逻辑（处理 429 错误）
        for attempt in range(3):  # MAX_RETRIES = 3
            try:
                self._apply_rate_limit()
                response = request_impl(method, url, headers=self.headers, **kwargs)

                if 200 <= response.status_code < 300:
                    return response.json()
                elif response.status_code == 429:
                    # 处理频率限制错误
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        wait_times = [10, 25, 60]
                        wait_time = wait_times[attempt] if attempt < len(wait_times) else 60

                    get_logger().warning(f"请求频率限制，{wait_time} 秒后重试... (尝试 {attempt + 1}/3)", module="maimemo_api")
                    time.sleep(wait_time)
                    continue
                elif self._is_transient_status(response.status_code):
                    wait_times = [2, 5, 10]
                    wait_time = wait_times[attempt] if attempt < len(wait_times) else 10
                    get_logger().warning(
                        f"服务端临时错误 {response.status_code}，{wait_time} 秒后重试... (尝试 {attempt + 1}/3)",
                        module="maimemo_api",
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误，记录并返回
                    get_logger().error(f"[API Error] {method} {endpoint} -> {response.status_code}: {response.text}", module="maimemo_api", function="_request")
                    return None
            except Exception as e:
                get_logger().error(f"请求异常: {e}", module="maimemo_api")
                if attempt < 2:  # MAX_RETRIES - 1
                    wait_times = [10, 25, 60]
                    time.sleep(wait_times[attempt])
                    continue
                return None

        # 重试次数用尽后，记录错误并返回
        get_logger().error(f"[API Error] {method} {endpoint} -> 重试次数用尽，请求失败", module="maimemo_api", function="_request")
        return None

    # ==========================
    # 1. 单词查询 (Vocabulary)
    # ==========================
    def get_vocabulary(self, spelling: str) -> Optional[Dict]:
        """获取单个单词 (通常用来查 voc_id)"""
        return self._request("GET", "/vocabulary", params={"spelling": spelling})

    def list_vocabulary(self, spellings: List[str] = None, ids: List[str] = None) -> Optional[Dict]:
        """批量查询单词"""
        payload = {}
        if spellings: payload["spellings"] = spellings
        if ids: payload["ids"] = ids
        return self._request("POST", "/vocabulary/query", json=payload)

    # ==========================
    # 2. 释义管理 (Interpretations)
    # ==========================
    def list_interpretations(self, voc_id: str) -> Optional[Dict]:
        """获取自己在此单词下创建的释义列表"""
        now = time.time()
        ts = self._interpretations_cache_ts.get(voc_id)
        if ts and (now - ts) <= self._interpretations_cache_ttl:
            return self._interpretations_cache.get(voc_id)

        res = self._request("GET", "/interpretations", params={"voc_id": voc_id})
        if res is not None:
            self._interpretations_cache[voc_id] = res
            self._interpretations_cache_ts[voc_id] = now
        return res

    def create_interpretation(self, voc_id: str, interpretation: str, tags: List[str] = None, status: str = "PUBLISHED") -> Optional[Dict]:
        """创建释义"""
        if not tags:
            tags = ["雅思", "考研"]
        payload = {
            "interpretation": {
                "voc_id": voc_id,
                "interpretation": interpretation,
                "tags": tags,
                "status": status
            }
        }
        res = self._request("POST", "/interpretations", json=payload)
        # 创建后清理缓存，避免读到过期“空列表”
        self._interpretations_cache.pop(voc_id, None)
        self._interpretations_cache_ts.pop(voc_id, None)
        return res

    def update_interpretation(self, interpretation_id: str, interpretation: str, tags: List[str] = None, status: str = "PUBLISHED") -> Optional[Dict]:
        """更新释义"""
        if not tags:
            tags = ["雅思", "考研"]
        payload = {
            "interpretation": {
                "interpretation": interpretation,
                "tags": tags,
                "status": status
            }
        }
        return self._request("POST", f"/interpretations/{interpretation_id}", json=payload)

    def delete_interpretation(self, interpretation_id: str) -> Optional[Dict]:
        """删除释义"""
        return self._request("DELETE", f"/interpretations/{interpretation_id}")

    def sync_interpretation(self, voc_id: str, interpretation: str, tags: List[str] = None, spell: str = None, force_create: bool = True) -> bool:
        """智能同步：检查用户释义，仅在无释义时创建

        Args:
            voc_id: 单词ID
            interpretation: 释义内容
            tags: 标签列表
            spell: 单词拼写（用于日志显示）
        """
        # 生成友好的单词标识
        word标识 = spell if spell else f"voc_id:{voc_id}"

        # 如果已达到创建限制，直接跳过
        if self.creation_limit_reached:
            get_logger().warning(f"[*] {word标识} - 已达到创建释义限制，跳过创建", module="maimemo_api")
            return True

        if not force_create:
            # 1. 检查是否存在已有释义（用户创建的）
            res = self.list_interpretations(voc_id)
            if not res:
                get_logger().error(f"[*] {word标识} - 查询释义失败：API 返回空响应", module="maimemo_api")
                return False

            if res.get("success"):
                intps = res.get("data", {}).get("interpretations", [])
                if intps:
                    # 已存在用户创建的释义，跳过
                    get_logger().info(f"[*] {word标识} - 已有用户释义，跳过创建", module="maimemo_api")
                    return True  # 视为成功，避免重复处理
            else:
                # 查询失败，可能是 API 错误
                errors = res.get("errors", [])
                if errors:
                    error_msg = errors[0].get("msg", "未知错误")
                    get_logger().error(f"[*] {word标识} - 查询释义失败：{error_msg}", module="maimemo_api")
                return False

        # 2. 不存在用户释义，执行创建
        # 使用默认标签：雅思、考研
        if not tags:
            tags = ["雅思", "考研"]

        # 再次检查创建限制（避免在批量处理中重复尝试）
        if self.creation_limit_reached:
            get_logger().warning(f"[*] {word标识} - 已达到创建释义限制，跳过创建", module="maimemo_api")
            return True

        get_logger().info(f"[*] {word标识} - 未发现用户释义，正在创建 (标签: {tags})", module="maimemo_api")
        create_res = self.create_interpretation(voc_id, interpretation, tags)

        # 3. 处理创建失败的情况
        if not create_res:
            get_logger().error(f"[*] {word标识} - 创建释义失败：API 返回空响应", module="maimemo_api")
            return False

        if not create_res.get("success"):
            errors = create_res.get("errors", [])
            if errors:
                error_code = errors[0].get("code", "")
                error_msg = errors[0].get("msg", "未知错误")

                if error_code == "interpretation_exists" or "存在" in str(error_msg):
                    get_logger().info(f"[*] {word标识} - 释义已存在，视为同步成功", module="maimemo_api")
                    return True

                # 如果是超出限制的错误，标记状态并记录警告
                if error_code == "interpretation_create_limitation":
                    self.creation_limit_reached = True
                    get_logger().warning(f"[*] {word标识} - 创建释义失败：{error_msg}（已超出最大创建数量限制）", module="maimemo_api")
                    return True  # 视为成功，避免重复尝试

                get_logger().error(f"[*] {word标识} - 创建释义失败：{error_msg}", module="maimemo_api")
            else:
                get_logger().error(f"[*] {word标识} - 创建释义失败：未知错误", module="maimemo_api")
            return False

        return True

    # ==========================
    # 3. 助记管理 (Notes)
    # ==========================
    def list_notes(self, voc_id: str) -> Optional[Dict]:
        """获取助记"""
        return self._request("GET", "/notes", params={"voc_id": voc_id})

    def create_note(self, voc_id: str, note_type: str, note: str, tags: List[str] = None) -> Optional[Dict]:
        """创建助记"""
        payload = {
            "note": {
                "voc_id": voc_id,
                "note_type": note_type,
                "note": note,
                "tags": self._normalize_note_tags(tags)
            }
        }
        return self._request("POST", "/notes", json=payload)

    def update_note(self, note_id: str, note_type: str, note: str, tags: List[str] = None) -> Optional[Dict]:
        """更新助记"""
        payload = {
            "note": {
                "note_type": note_type,
                "note": note,
                "tags": self._normalize_note_tags(tags)
            }
        }
        return self._request("POST", f"/notes/{note_id}", json=payload)

    def delete_note(self, note_id: str) -> Optional[Dict]:
        """删除助记"""
        return self._request("DELETE", f"/notes/{note_id}")

    # ==========================
    # 4. 例句管理 (Phrases)
    # ==========================
    def list_phrases(self, voc_id: str) -> Optional[Dict]:
        """获取例句"""
        return self._request("GET", "/phrases", params={"voc_id": voc_id})

    def create_phrase(self, voc_id: str, phrase: str, interpretation: str, tags: List[str] = None, origin: str = "API导入") -> Optional[Dict]:
        """创建例句"""
        payload = {
            "phrase": {
                "voc_id": voc_id,
                "phrase": phrase,
                "interpretation": interpretation,
                "tags": tags or ["API导入"],
                "origin": origin
            }
        }
        return self._request("POST", "/phrases", json=payload)

    def update_phrase(self, phrase_id: str, phrase: str, interpretation: str, tags: List[str] = None, origin: str = "API导入") -> Optional[Dict]:
        """更新例句"""
        payload = {
            "phrase": {
                "phrase": phrase,
                "interpretation": interpretation,
                "tags": tags or ["API导入"],
                "origin": origin
            }
        }
        return self._request("POST", f"/phrases/{phrase_id}", json=payload)

    def delete_phrase(self, phrase_id: str) -> Optional[Dict]:
        """删除例句"""
        return self._request("DELETE", f"/phrases/{phrase_id}")

    # ==========================
    # 5. 云词本管理 (Notepads)
    # ==========================
    def list_notepads(self, limit: int = 10, offset: int = 0, ids: List[str] = None) -> Optional[Dict]:
        """查询云词本"""
        params = {"limit": limit, "offset": offset}
        if ids: params["ids"] = ",".join(ids)
        return self._request("GET", "/notepads", params=params)

    def get_notepad(self, notepad_id: str) -> Optional[Dict]:
        """获取单个云词本详情"""
        return self._request("GET", f"/notepads/{notepad_id}")

    def create_notepad(self, title: str, content: str, brief: str = "", tags: List[str] = None, status: str = "UNPUBLISHED") -> Optional[Dict]:
        """创建云词本"""
        payload = {
            "notepad": {
                "title": title,
                "content": content,
                "brief": brief,
                "tags": tags or [],
                "status": status
            }
        }
        return self._request("POST", "/notepads", json=payload)

    def update_notepad(self, notepad_id: str, title: str, content: str, brief: str = "", tags: List[str] = None, status: str = "UNPUBLISHED") -> Optional[Dict]:
        """修改云词本"""
        payload = {
            "notepad": {
                "title": title,
                "content": content,
                "brief": brief,
                "tags": tags or [],
                "status": status
            }
        }
        return self._request("POST", f"/notepads/{notepad_id}", json=payload)

    # ==========================
    # 6. 学习数据(公测) (Study)
    # ==========================
    def get_study_progress(self) -> Optional[Dict]:
        """获取今日学习进度"""
        return self._request("POST", "/study/get_study_progress")
        
    def get_today_items(self, limit: int = 500) -> Optional[Dict]:
        """获取今日待学习/待复习的单词列表（公测新接口）"""
        # 官方默认每次只返回50个，我们通过传入更大的 limit 一次性拉满
        return self._request("POST", "/study/get_today_items", json={"limit": limit})

        
    def add_words_to_study(self, voc_ids: List[str], advance: bool = False) -> Optional[Dict]:
        """添加单词到复习/学习规划"""
        payload = {
            "words": [{"id": vid} for vid in voc_ids],
            "advance": advance
        }
        return self._request("POST", "/study/add_words", json=payload)

    def query_study_records(self, start_date: str, end_date: str, limit: int = 1000) -> Optional[Dict]:
        """按计划日期查询学习记录 (公测新接口)"""
        payload = {
            "next_study_date": {
                "start": start_date,
                "end": end_date
            },
            "limit": limit
        }
        return self._request("POST", "/study/query_study_records", json=payload)

# ================= 用法示例 =================
if __name__ == "__main__":
    from config import MOMO_TOKEN
    momo = MaiMemoAPI(MOMO_TOKEN)
    
    # 测试查询一个单词
    # print(momo.get_vocabulary("apple"))
