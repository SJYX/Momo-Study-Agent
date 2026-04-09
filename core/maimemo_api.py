# -*- coding: utf-8 -*-
"""
墨墨背单词 OpenAPI 封装调用库
基于官方文档: https://open.maimemo.com/document#/
"""

import requests
import time
from typing import List, Dict, Optional, Union

class MaiMemoAPI:
    def __init__(self, access_token: str):
        self.base_url = "https://open.maimemo.com/open/api/v1"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
    def _request(self, method: str, endpoint: str, **kwargs):
        """统一请求处理及限流"""
        # 官方频控: 10秒20次, 60秒40次, 5小时2000次
        time.sleep(0.5) 
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        if 200 <= response.status_code < 300:
            return response.json()
        else:
            print(f"[API Error] {method} {endpoint} -> {response.status_code}: {response.text}")
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
        return self._request("GET", "/interpretations", params={"voc_id": voc_id})

    def create_interpretation(self, voc_id: str, interpretation: str, tags: List[str] = None, status: str = "PUBLISHED") -> Optional[Dict]:
        """创建释义"""
        payload = {
            "interpretation": {
                "voc_id": voc_id,
                "interpretation": interpretation,
                "tags": tags or ["API导入"],
                "status": status
            }
        }
        return self._request("POST", "/interpretations", json=payload)

    def update_interpretation(self, interpretation_id: str, interpretation: str, tags: List[str] = None, status: str = "PUBLISHED") -> Optional[Dict]:
        """更新释义"""
        payload = {
            "interpretation": {
                "interpretation": interpretation,
                "tags": tags or ["API导入"],
                "status": status
            }
        }
        return self._request("POST", f"/interpretations/{interpretation_id}", json=payload)

    def delete_interpretation(self, interpretation_id: str) -> Optional[Dict]:
        """删除释义"""
        return self._request("DELETE", f"/interpretations/{interpretation_id}")

    def sync_interpretation(self, voc_id: str, interpretation: str, tags: List[str] = None) -> bool:
        """智能同步：存在则更新，不存在则创建"""
        # 1. 检查是否存在已有释义
        res = self.list_interpretations(voc_id)
        if res and res.get("success"):
            intps = res.get("data", {}).get("interpretations", [])
            if intps:
                # 已存在，执行更新 (取第一个)
                intp_id = intps[0].get("id")
                print(f"    [*] 发现已有释义 ({intp_id})，正在执行覆盖更新...")
                update_res = self.update_interpretation(intp_id, interpretation, tags)
                return update_res and update_res.get("success")
        
        # 2. 不存在，执行创建
        print(f"    [*] 未发现已有释义，正在执行创建...")
        create_res = self.create_interpretation(voc_id, interpretation, tags)
        return create_res and create_res.get("success")

    # ==========================
    # 3. 助记管理 (Notes)
    # ==========================
    def list_notes(self, voc_id: str) -> Optional[Dict]:
        """获取助记"""
        return self._request("GET", "/notes", params={"voc_id": voc_id})

    def create_note(self, voc_id: str, note_type: str, note: str) -> Optional[Dict]:
        """创建助记"""
        payload = {
            "note": {
                "voc_id": voc_id,
                "note_type": note_type,
                "note": note
            }
        }
        return self._request("POST", "/notes", json=payload)

    def update_note(self, note_id: str, note_type: str, note: str) -> Optional[Dict]:
        """更新助记"""
        payload = {
            "note": {
                "note_type": note_type,
                "note": note
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

    #... 云词本的 create, update, delete 也类似，这里可以按需补全

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
