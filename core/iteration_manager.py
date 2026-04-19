import json
import time
from typing import List, Dict
from config import DB_PATH
from database.connection import _get_read_conn, _row_to_dict, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
from database.momo_words import get_latest_progress, save_ai_word_iteration, update_ai_word_note_iteration_state
from database.utils import get_timestamp_with_tz
from core.constants import MAIMEMO_BRIEF_MEANING_MAX_LENGTH
from config import SCORE_PROMPT_FILE, REFINE_PROMPT_FILE
from core.weak_word_filter import WeakWordFilter

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

    def run_iteration(self):
        """主循环：筛选薄弱词并执行迭代逻辑。

        策略：
        1. 使用优化的筛选系统获取薄弱词列表
        2. 分级处理（Level 0: 选优, Level 1+: 重炼）
        3. 批量同步到云词本
        4. 完善错误处理和重试机制
        """
        import time
        self.notepad_additions = []

        # 使用优化的筛选系统
        filter = WeakWordFilter(self.logger)
        user_stats = filter._get_user_stats()
        dynamic_threshold = filter.get_dynamic_threshold(user_stats)

        self.logger.info(f"用户统计: {user_stats}", module="iteration_manager", function="run_iteration")
        self.logger.info(f"动态阈值: {dynamic_threshold}", module="iteration_manager", function="run_iteration")

        # 按分数获取薄弱词（推荐分数 >= 50）
        weak_words = filter.get_weak_words_by_score(min_score=50.0, limit=100)

        # 备选 1：如果按分数没抓到，尝试按类别抓取紧急和一般词
        if not weak_words:
            self.logger.info("  [Fallback] 高薄弱分筛选结果为空，尝试按分类筛选...", module="iteration_manager", function="run_iteration")
            categorized = filter.get_weak_words_by_category(dynamic_threshold)
            weak_words = categorized['urgent'] + categorized['normal']

        # 备选 2：如果还是没抓到，使用底层的直接数据库查询（忽略 review_count 门槛）
        if not weak_words:
            self.logger.info("  [Fallback] 分类筛选结果为空，尝试基础数据库扫描...", module="iteration_manager", function="run_iteration")
            weak_words = self._get_weak_words_from_db(dynamic_threshold)

        if not weak_words:
            self.logger.info("🎉 经过多级筛选，未发现符合条件的薄弱单词。", module="iteration_manager", function="run_iteration")
            return

        self.logger.info(f"🔍 发现 {len(weak_words)} 个薄弱单词，进入分级处理流程...", module="iteration_manager", function="run_iteration")

        # 统计信息
        stats = {
            'processed': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0
        }

        for w in weak_words:
            voc_id = w["voc_id"]
            spell = w["spelling"]
            it_level = w.get("it_level", 0)

            self.logger.info(f"处理 [{spell}] (Level {it_level})...", module="iteration_manager", function="run_iteration")

            try:
                if it_level == 0:
                    # Level 1: 选优同步
                    self._handle_level_1_selection(w)
                    stats['success'] += 1
                else:
                    # Level 2+: 强力重炼
                    # 检查自上次同步以来是否有进步
                    last_fam = self._get_last_recorded_fam(voc_id)
                    current_fam = w["familiarity_short"]

                    if current_fam <= last_fam + 0.1:  # 几乎没进步或退步
                        self.logger.info(f"  [Re-generate] {spell} 熟悉度无明显提升 ({last_fam} -> {current_fam})，触发强力重炼", module="iteration_manager", function="run_iteration")
                        self._handle_level_2_refinement(w)
                        stats['success'] += 1
                    else:
                        self.logger.info(f"  [Wait] {spell} 熟悉度有提升 ({last_fam} -> {current_fam})，保持观察", module="iteration_manager", function="run_iteration")
                        stats['skipped'] += 1

                stats['processed'] += 1

                # 添加延迟避免 API 频率限制
                if stats['processed'] % 5 == 0:
                    time.sleep(1)

            except Exception as e:
                self.logger.error(f"  ❌ 处理 [{spell}] 失败: {e}", module="iteration_manager", function="run_iteration")
                stats['failed'] += 1
                continue

        # 批量处理云词本弱词追加
        if getattr(self, 'notepad_additions', None):
            self._sync_weak_words_notepad()

        # 输出统计信息
        self.logger.info(f"📊 迭代完成: 处理 {stats['processed']} 个单词, 成功 {stats['success']}, 失败 {stats['failed']}, 跳过 {stats['skipped']}", module="iteration_manager", function="run_iteration")

    def _sync_weak_words_notepad(self):
        notepad_title = "MomoAgent: 薄弱词攻坚"
        res = self.momo.list_notepads(limit=100)
        target_notepad = None
        if res and res.get("notepads"):
            for np in res["notepads"]:
                if np.get("title") == notepad_title:
                    target_notepad = np
                    break
                    
        current_content = ""
        if target_notepad:
            detail = self.momo.get_notepad(target_notepad["id"])
            if detail and detail.get("notepad"):
                current_content = detail["notepad"].get("content", "")
        
        # 解析换行获取纯单词并追加
        existing_words = [w.strip() for w in current_content.split('\n') if w.strip()]
        new_words = [w for w in self.notepad_additions if w not in existing_words]
        
        if not new_words:
            self.logger.info("云词本包含所有薄弱词，无需追加。", module="iteration_manager", function="_sync_weak_words_notepad")
            return
            
        merged_content = "\n".join(existing_words + new_words)
        try:
            if target_notepad:
                self.momo.update_notepad(target_notepad["id"], notepad_title, merged_content, "反复遗忘的难点词隔离库", ["AI"], "UNPUBLISHED")
                self.logger.info(f"✅ 成功追加 {len(new_words)} 个薄弱词至云词本: {notepad_title}", module="iteration_manager", function="_sync_weak_words_notepad")
            else:
                self.momo.create_notepad(notepad_title, merged_content, "反复遗忘的难点词隔离库", ["AI"], "UNPUBLISHED")
                self.logger.info(f"✨ 新建云词本并导入 {len(new_words)} 个薄弱词: {notepad_title}", module="iteration_manager", function="_sync_weak_words_notepad")
        except Exception as e:
            self.logger.error(f"同步云词本发生异常: {e}", error=str(e), module="iteration_manager")

    def _get_weak_words_from_db(self, threshold: float) -> List[Dict]:
        """从数据库中筛选薄弱词，包括已有 AI 笔记和需要创建释义的单词。

        策略：
        1. 优先处理已有 AI 笔记但熟悉度低的单词（迭代优化）
        2. 处理没有 AI 笔记但熟悉度低的单词（首次助记生成）
        """
        conn = _get_read_conn(DB_PATH)
        conn_lock = _get_singleton_conn_op_lock(conn)
        weak_words = []
        cur = conn.cursor()
        try:
            # 1. 获取已有 AI 笔记的薄弱词（迭代优化）
            query1 = f"""
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
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute(query1, (threshold,))
                        rows1 = [_row_to_dict(cur, r) for r in cur.fetchall()]
                    finally:
                        cur.close()
                    conn.commit()
            else:
                try:
                    cur.execute(query1, (threshold,))
                    rows1 = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()
            weak_words.extend(rows1)

            # 2. 获取没有 AI 笔记但熟悉度低的单词（首次助记生成）
            # 排除已有 AI 笔记的单词
            cur = conn.cursor()
            query2 = f"""
                SELECT
                    h.voc_id,
                    h.familiarity_short,
                    p.spelling
                FROM word_progress_history h
                JOIN (
                    SELECT voc_id, MAX(created_at) as max_created_at
                    FROM word_progress_history
                    GROUP BY voc_id
                ) latest ON h.voc_id = latest.voc_id AND h.created_at = latest.max_created_at
                LEFT JOIN ai_word_notes n ON h.voc_id = n.voc_id
                JOIN processed_words p ON h.voc_id = p.voc_id
                WHERE h.familiarity_short < ? AND n.voc_id IS NULL
                GROUP BY h.voc_id
            """
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute(query2, (threshold,))
                        rows2 = [_row_to_dict(cur, r) for r in cur.fetchall()]
                    finally:
                        cur.close()
                    conn.commit()
            else:
                try:
                    cur.execute(query2, (threshold,))
                    rows2 = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()

            # 补全缺失的字段
            for row in rows2:
                row['it_level'] = 0
                row['it_history'] = '[]'
                row['memory_aid'] = ''
                row['raw_full_text'] = ''
                row['meanings'] = ''  # 没有释义信息
                weak_words.append(row)
        finally:
            if not _is_main_write_singleton_conn(conn):
                conn.close()

        # 去重（基于 voc_id）
        unique_words = {}
        for word in weak_words:
            voc_id = word['voc_id']
            if voc_id not in unique_words:
                unique_words[voc_id] = word

        return list(unique_words.values())

    def _get_last_recorded_fam(self, voc_id: str) -> float:
        """获取该单词在最后一次 it_level 变更时的熟悉度基准。"""
        conn = _get_read_conn(DB_PATH)
        conn_lock = _get_singleton_conn_op_lock(conn)
        cur = conn.cursor()
        try:
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute("SELECT it_history FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
                        row = cur.fetchone()
                    finally:
                        cur.close()
                    conn.commit()
            else:
                try:
                    cur.execute("SELECT it_history FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
                    row = cur.fetchone()
                finally:
                    cur.close()
                conn.commit()
        finally:
            if not _is_main_write_singleton_conn(conn):
                conn.close()
        if row and row[0]:
            history = json.loads(row[0])
            if history:
                # 取最后一条记录中的 baseline
                return history[-1].get("baseline_fam", 0.0)
        return 0.0

    def _handle_level_1_selection(self, word: Dict):
        """Level 1: 从现有三种助记中选优，并同步到墨墨释义。"""
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
            try:
                import importlib
                json_repair = importlib.import_module("json_repair")
            except ImportError:
                import json
                json_repair = json
            res = json_repair.loads(text.strip())
            best_note = res.get("refined_content")
            score = res.get("score")
            iteration_context = {
                "stage": "level_1_selection",
                "score": score,
                "justification": res.get("justification"),
                "tags": res.get("tags"),
                "refined_content": best_note,
                "raw_response": text,
                "candidate_notes": memory_aid,
                "spelling": spell,
                "voc_id": voc_id,
                "it_level": 1,
            }
            self.logger.info(f"  AI 打分结果: {score}/10, 理由: {res.get('justification')}", module="iteration_manager", function="_handle_level_1_selection")

            if not best_note:
                raise ValueError("AI 返回中缺少 refined_content")

            # 2. 同步到墨墨助记
            sync_res = self.momo.create_note(voc_id, "1", best_note, tags=res.get("tags"))
            if sync_res and sync_res.get("success"):
                self.logger.info(f"  ✅ {spell} 选优助记已同步至墨墨 (Score: {score})", module="iteration_manager", function="_handle_level_1_selection")

                # 3. 同步到墨墨释义（如果需要）
                # 提取简短释义用于同步
                brief_meaning = word.get("meanings", "")
                if brief_meaning:
                    if len(brief_meaning) > MAIMEMO_BRIEF_MEANING_MAX_LENGTH:
                        brief_meaning = brief_meaning[:MAIMEMO_BRIEF_MEANING_MAX_LENGTH] + "..."
                    sync_interpretation_res = self.momo.sync_interpretation(voc_id, brief_meaning, tags=["雅思", "考研"], spell=spell)
                    if sync_interpretation_res:
                        self.logger.info(f"  ✅ {spell} 释义已同步至墨墨", module="iteration_manager", function="_handle_level_1_selection")
                    else:
                        self.logger.warning(f"  ⚠️ {spell} 释义同步失败", module="iteration_manager", function="_handle_level_1_selection")

                self._update_it_state(voc_id, 1, f"AI Scored {score}: {res.get('justification')}", iteration_data=iteration_context)
        except Exception as e:
            self.logger.error(f"  [Level 1 Error] {spell}: {e} | Raw: {text[:100]}", module="iteration_manager", function="_handle_level_1_selection")

    def _handle_level_2_refinement(self, word: Dict):
        """Level 2: 强力重炼高强度助记，并处理 API 限制。"""
        voc_id = word["voc_id"]
        spell = word["spelling"]

        # 检查 API 限制
        if hasattr(self.momo, 'creation_limit_reached') and self.momo.creation_limit_reached:
            self.logger.warning(f"  ⚠️ {spell} - 已达到墨墨 API 创建限制，跳过释义同步", module="iteration_manager", function="_handle_level_2_refinement")
            # 仍然生成助记，但不同步释义

        # 1. 调用强力重炼 Prompt
        with open(REFINE_PROMPT_FILE, "r", encoding="utf-8") as f:
            instr = f.read()

        prompt = f"Word: {spell}\nPrevious Result: {word.get('memory_aid', 'None')}"
        text, metadata = self.ai_client.generate_with_instruction(prompt, instruction=instr)

        try:
            try:
                import importlib
                json_repair = importlib.import_module("json_repair")
            except ImportError:
                import json
                json_repair = json
            new_data = json_repair.loads(text.strip())
            if isinstance(new_data, list) and len(new_data) > 0:
                new_note = new_data[0]["memory_aid"]
                iteration_context = {
                    "stage": "level_2_refinement",
                    "score": None,
                    "justification": None,
                    "tags": new_data[0].get("tags"),
                    "refined_content": new_note,
                    "raw_response": text,
                    "candidate_notes": word.get('memory_aid', ''),
                    "spelling": spell,
                    "voc_id": voc_id,
                    "it_level": word["it_level"] + 1,
                }

                # 2. 同步到墨墨助记
                sync_res = self.momo.create_note(voc_id, "1", new_note, tags=new_data[0].get("tags"))
                if sync_res and sync_res.get("success"):
                    self.logger.info(f"  🔥 {spell} 强力重炼助记已同步 (Level 2)", module="iteration_manager", function="_handle_level_2_refinement")

                    # 3. 同步到墨墨释义（如果未达到限制）
                    if not (hasattr(self.momo, 'creation_limit_reached') and self.momo.creation_limit_reached):
                        brief_meaning = word.get("meanings", "")
                        if brief_meaning:
                            if len(brief_meaning) > MAIMEMO_BRIEF_MEANING_MAX_LENGTH:
                                brief_meaning = brief_meaning[:MAIMEMO_BRIEF_MEANING_MAX_LENGTH] + "..."
                            sync_interpretation_res = self.momo.sync_interpretation(voc_id, brief_meaning, tags=["雅思", "考研"], spell=spell)
                            if sync_interpretation_res:
                                self.logger.info(f"  ✅ {spell} 释义已同步至墨墨", module="iteration_manager", function="_handle_level_2_refinement")
                            else:
                                self.logger.warning(f"  ⚠️ {spell} 释义同步失败", module="iteration_manager", function="_handle_level_2_refinement")

                    self._update_it_state(voc_id, word["it_level"] + 1, "Power Refined", new_note, text, iteration_data=iteration_context)
                    if hasattr(self, 'notepad_additions'):
                        self.notepad_additions.append(spell)
            else:
                raise ValueError("重炼返回格式错误（需为数组）")
        except Exception as e:
            self.logger.error(f"  [Level 2 Error] {spell}: {str(e)[:120]} | Raw: {text[:100]}", module="iteration_manager", function="_handle_level_2_refinement")

    def _update_it_state(self, voc_id, level, reason, new_note=None, raw_text=None, iteration_data=None):
        """原子化更新迭代状态。"""
        # 读取当前快照用于构建新 history；写入统一走 db_manager 异步队列。
        current_progress = get_latest_progress(voc_id, db_path=DB_PATH)
        current_fam = current_progress.get("familiarity_short", 0.0) if current_progress else 0.0
        if current_fam is None:
            current_fam = 0.0

        history_item = {
            "time": get_timestamp_with_tz(),
            "level": level,
            "reason": reason,
            "baseline_fam": current_fam,
        }

        conn = _get_read_conn(DB_PATH)
        conn_lock = _get_singleton_conn_op_lock(conn)
        cur = conn.cursor()
        try:
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute("SELECT it_history, memory_aid FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
                        row = cur.fetchone()
                    finally:
                        cur.close()
                    conn.commit()
            else:
                try:
                    cur.execute("SELECT it_history, memory_aid FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
                    row = cur.fetchone()
                finally:
                    cur.close()
                conn.commit()
        finally:
            if not _is_main_write_singleton_conn(conn):
                conn.close()

        old_history = json.loads(row[0]) if row and row[0] else []
        old_memory_aid = row[1] if row and len(row) > 1 else ""
        old_history.append(history_item)
        history_json = json.dumps(old_history, ensure_ascii=False)

        if iteration_data:
            ok = save_ai_word_iteration(voc_id, iteration_data)
            if not ok:
                self.logger.warning(f"迭代历史入队失败: {voc_id}", module="iteration_manager", function="_update_it_state")

        if new_note:
            # 模式：将重炼结果置顶保存，保留历史
            combined_note = f"{new_note}\n\n--- 历史记录 ---\n{old_memory_aid}" if old_memory_aid else new_note
            ok = update_ai_word_note_iteration_state(voc_id, level, history_json, memory_aid=combined_note)
        else:
            ok = update_ai_word_note_iteration_state(voc_id, level, history_json)

        if not ok:
            self.logger.warning(f"迭代状态入队失败: {voc_id}", module="iteration_manager", function="_update_it_state")
