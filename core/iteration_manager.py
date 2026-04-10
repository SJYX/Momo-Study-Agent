import json
import time
import logging
from typing import List, Dict, Optional
from core.db_manager import (
    get_latest_progress, log_progress_snapshots, save_ai_word_note, 
    _get_conn, DB_PATH
)
from config import SCORE_PROMPT_FILE, REFINE_PROMPT_FILE, AI_PROVIDER
import sqlite3

class IterationManager:
    def __init__(self, ai_client, momo_api, logger=None):
        self.ai_client = ai_client
        self.momo = momo_api
        if logger:
            self.logger = logger
        else:
            # 如果没有传入logger，使用默认的
            from core.logger import get_logger
            self.logger = get_logger()

    def run_iteration(self, familiarity_threshold: float = 3.0):
        """主循环：筛选薄弱词并执行迭代逻辑。"""
        weak_words = self._get_weak_words_from_db(familiarity_threshold)
        if not weak_words:
            self.logger.info("🎉 没有发现需要迭代的薄弱单词。", module="iteration_manager", function="run_iteration")
            return

        self.logger.info(f"🔍 发现 {len(weak_words)} 个薄弱单词，准备进入智能迭代流程...", module="iteration_manager", function="run_iteration")
        
        for w in weak_words:
            voc_id = w["voc_id"]
            spell = w["spelling"]
            it_level = w.get("it_level", 0)
            
            self.logger.info(f"处理 [{spell}] (Level {it_level})...", module="iteration_manager", function="run_iteration")
            
            if it_level == 0:
                # Level 1: 选优同步
                self._handle_level_1_selection(w)
            else:
                # Level 2+: 强力重炼
                # 检查自上次同步以来是否有进步
                last_fam = self._get_last_recorded_fam(voc_id)
                current_fam = w["familiarity_short"]
                
                if current_fam <= last_fam + 0.1: # 几乎没进步或退步
                    self.logger.info(f"  [Re-generate] {spell} 熟悉度无明显提升 ({last_fam} -> {current_fam})，触发强力重炼", module="iteration_manager", function="run_iteration")
                    self._handle_level_2_refinement(w)
                else:
                    self.logger.info(f"  [Wait] {spell} 熟悉度有提升 ({last_fam} -> {current_fam})，保持观察", module="iteration_manager", function="run_iteration")

    def _get_weak_words_from_db(self, threshold: float) -> List[Dict]:
        """从数据库中筛选薄弱词（利用 json_extract）。"""
        conn = _get_conn(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 筛选逻辑：在 ai_word_notes 中且熟悉度 < threshold
        # 我们从最新快照中取熟悉度
        query = f"""
            SELECT n.*, h.familiarity_short 
            FROM ai_word_notes n
            JOIN (
                SELECT voc_id, familiarity_short 
                FROM word_progress_history 
                GROUP BY voc_id 
                HAVING MAX(created_at)
            ) h ON n.voc_id = h.voc_id
            WHERE h.familiarity_short < ?
        """
        cur.execute(query, (threshold,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def _get_last_recorded_fam(self, voc_id: str) -> float:
        """获取该单词在 it_level 变化时的熟悉度基准。"""
        # 简化版：从 history 中找最后一次 Level 变更的记录
        progress = get_latest_progress(voc_id)
        return progress["familiarity_short"] if progress else 0.0

    def _handle_level_1_selection(self, word: Dict):
        """Level 1: 从现有三种助记中选优。"""
        voc_id = word["voc_id"]
        spell = word["spelling"]
        memory_aid = word.get("memory_aid", "")
        
        if not memory_aid:
            self.logger.warning(f"  {spell} 没有原始助记内容，跳过。", module="iteration_manager", function="_handle_level_1_selection")
            return

        # 1. 调用 AI 打分
        with open(SCORE_PROMPT_FILE, "r", encoding="utf-8") as f:
            instr = f.read()
        
        prompt = f"Word: {spell}\nCandidates:\n{memory_aid}"
        text, metadata = self.ai_client.generate_with_instruction(prompt, instruction=instr)
        
        try:
            import json_repair
            res = json_repair.loads(text.strip())
            best_note = res.get("refined_content")
            score = res.get("score")
            self.logger.info(f"  AI 打分结果: {score}/10, 理由: {res.get('justification')}", module="iteration_manager", function="_handle_level_1_selection")
            
            if not best_note:
                raise ValueError("AI 返回中缺少 refined_content")

            # 2. 同步到墨墨助记
            sync_res = self.momo.create_note(voc_id, "1", best_note)
            if sync_res and sync_res.get("success"):
                self.logger.info(f"  ✅ {spell} 选优助记已同步至墨墨 (Score: {score})", module="iteration_manager", function="_handle_level_1_selection")
                self._update_it_state(voc_id, 1, f"AI Scored {score}: {res.get('justification')}")
        except Exception as e:
            self.logger.error(f"  [Level 1 Error] {spell}: {e} | Raw: {text[:100]}", module="iteration_manager", function="_handle_level_1_selection")

    def _handle_level_2_refinement(self, word: Dict):
        """Level 2: 强力重炼高强度助记。"""
        voc_id = word["voc_id"]
        spell = word["spelling"]
        
        # 1. 调用强力重炼 Prompt
        with open(REFINE_PROMPT_FILE, "r", encoding="utf-8") as f:
            instr = f.read()
        
        prompt = f"Word: {spell}\nPrevious Result: {word.get('memory_aid', 'None')}"
        text, metadata = self.ai_client.generate_with_instruction(prompt, instruction=instr)
        
        try:
            import json_repair
            new_data = json_repair.loads(text.strip())
            if isinstance(new_data, list) and len(new_data) > 0:
                new_note = new_data[0]["memory_aid"]
                
                # 2. 同步到墨墨助记
                sync_res = self.momo.create_note(voc_id, "1", new_note)
                if sync_res and sync_res.get("success"):
                    self.logger.info(f"  🔥 {spell} 强力重炼助记已同步 (Level 2)", module="iteration_manager", function="_handle_level_2_refinement")
                    self._update_it_state(voc_id, word["it_level"] + 1, "Power Refined", new_note, text)
            else:
                raise ValueError("重炼返回格式错误（需为数组）")
        except Exception as e:
            self.logger.error(f"  [Level 2 Error] {spell}: {str(e)[:120]} | Raw: {text[:100]}", module="iteration_manager", function="_handle_level_2_refinement")

    def _update_it_state(self, voc_id, level, reason, new_note=None, raw_text=None):
        """原子化更新迭代状态。"""
        conn = _get_conn(DB_PATH)
        cur = conn.cursor()
        
        history_item = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "reason": reason
        }
        
        # 获取旧 history
        cur.execute("SELECT it_history, memory_aid FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
        row = cur.fetchone()
        old_history = json.loads(row[0]) if row and row[0] else []
        old_history.append(history_item)
        
        if new_note:
            # 模式：将重炼结果置顶保存，保留历史
            combined_note = f"{new_note}\n\n--- 历史记录 ---\n{row[1]}" if row else new_note
            cur.execute("""
                UPDATE ai_word_notes 
                SET it_level = ?, it_history = ?, memory_aid = ?, raw_full_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE voc_id = ?
            """, (level, json.dumps(old_history, ensure_ascii=False), combined_note, raw_text or (row[2] if row else None), voc_id))
        else:
            cur.execute("""
                UPDATE ai_word_notes 
                SET it_level = ?, it_history = ?, updated_at = CURRENT_TIMESTAMP
                WHERE voc_id = ?
            """, (level, json.dumps(old_history, ensure_ascii=False), voc_id))
            
        conn.commit()
        conn.close()
