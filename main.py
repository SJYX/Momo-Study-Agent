import argparse
import os
import signal
import uuid
from datetime import datetime, timedelta

from config import (
    ACTIVE_USER,
    AI_PROVIDER,
    BATCH_SIZE,
    DRY_RUN,
    GEMINI_API_KEY,
    MIMO_API_KEY,
    MOMO_TOKEN,
)
from core.db_manager import (
    clean_for_maimemo,
    cleanup_concurrent_system,
    get_local_word_note,
    get_processed_ids_in_batch,
    get_unsynced_notes,
    init_concurrent_system,
    init_db,
    is_processed,
    log_progress_snapshots,
    mark_processed,
    save_ai_batch,
    save_ai_word_note,
)
from core.iteration_manager import IterationManager
from core.log_config import get_full_config
from core.logger import setup_logger
from core.maimemo_api import MaiMemoAPI
from core.mimo_client import MimoClient
from core.study_workflow import StudyWorkflow
from core.ui_manager import CLIUIManager


def _disable_signal_wakeup_fd() -> None:
    try:
        if hasattr(signal, "set_wakeup_fd"):
            signal.set_wakeup_fd(-1)
    except Exception:
        pass


def _build_ai_client():
    if AI_PROVIDER == "mimo":
        if not MIMO_API_KEY:
            raise ValueError("MIMO_API_KEY required")
        return MimoClient(MIMO_API_KEY)
    from core.gemini_client import GeminiClient

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY required")
    return GeminiClient(GEMINI_API_KEY)


class StudyFlowManager:
    """Backward-compatible facade that delegates work to modular managers."""

    def __init__(self, environment=None, config_file=None):
        self.environment = environment or os.getenv("MOMO_ENV", "development")
        self.config_file = config_file or os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")

        get_full_config(self.environment, self.config_file)
        self.logger = setup_logger(ACTIVE_USER, environment=self.environment, config_file=self.config_file)
        self.session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=self.session_id)

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.ai_client = _build_ai_client()
        # Legacy alias retained for tests/scripts that still use manager.gemini.
        self.gemini = self.ai_client

        self.ui = CLIUIManager(self.logger)

        init_concurrent_system()
        init_db()
        self.workflow = StudyWorkflow(
            logger=self.logger,
            ai_client=self.ai_client,
            momo_api=self.momo,
            ui_manager=self.ui,
        )

        unsynced = get_unsynced_notes()
        for note in unsynced:
            self.workflow.sync_manager.queue_maimemo_sync(
                note["voc_id"],
                note.get("spelling", ""),
                clean_for_maimemo(note.get("basic_meanings", "")),
                ["雅思"],
                force_sync=True,
            )

    def _wait_for_choice(self, valid_choices):
        return self.ui.wait_for_choice(valid_choices)

    def _process_results(self, batch_words, ai_results, current_start, total, batch_id):
        from core.db_manager import save_ai_word_notes_batch

        ai_map = {item.get("spelling", "").lower(): item for item in (ai_results or [])}
        notes_to_save = []
        pending_sync_items = []

        for idx, word in enumerate(batch_words):
            num = current_start + idx + 1
            spell = str(word.get("voc_spelling", "")).lower()
            voc_id = str(word.get("voc_id", ""))
            payload = ai_map.get(spell)
            if not payload:
                self.logger.warning(f"{spell} 结果缺失")
                continue

            notes_to_save.append(
                {
                    "voc_id": voc_id,
                    "payload": payload,
                    "metadata": {
                        "batch_id": batch_id,
                        "original_meanings": word.get("voc_meanings") or word.get("voc_meaning") or word.get("meanings"),
                        "content_origin": "ai_generated",
                        "content_source_db": None,
                        "content_source_scope": None,
                    },
                }
            )

            if DRY_RUN:
                mark_processed(voc_id, spell)
            else:
                pending_sync_items.append(
                    {
                        "num": num,
                        "total": total,
                        "voc_id": voc_id,
                        "spell": spell,
                        "brief": clean_for_maimemo(payload.get("basic_meanings", "")),
                        "tags": ["雅思"],
                    }
                )

        if notes_to_save:
            save_ai_word_notes_batch(notes_to_save)

        for item in pending_sync_items:
            self.logger.info(f"[{item['num']}/{item['total']}] ✅ {item['spell']} 已加入收尾同步队列")
            self.workflow.sync_manager.queue_maimemo_sync(
                item["voc_id"],
                item["spell"],
                item["brief"],
                item["tags"],
                force_sync=True,
            )

    def _process_word_list(self, word_list, name):
        task_name = name or "任务"
        if not word_list:
            self.logger.info(f"{task_name} 当前无可处理单词", module="main")
            return

        normalized_words = [item for item in word_list if item.get("voc_spelling")]
        if not normalized_words:
            self.logger.warning(f"{task_name} 拉取结果中无有效拼写字段", module="main")
            return

        batch_size = max(1, int(BATCH_SIZE or 1))
        total_words = len(normalized_words)
        total_batches = (total_words + batch_size - 1) // batch_size

        self.logger.info(
            f"{task_name} 开始处理：{total_words} 词，批次大小 {batch_size}，共 {total_batches} 批",
            module="main",
        )

        processed_offset = 0
        for batch_index in range(total_batches):
            start = batch_index * batch_size
            end = min(start + batch_size, total_words)
            batch_words = normalized_words[start:end]
            batch_spells = [str(item.get("voc_spelling", "")) for item in batch_words]

            self.logger.info(
                f"[AI] {task_name} 批次 {batch_index + 1}/{total_batches} 请求中... ({len(batch_spells)} 词)",
                module="main",
            )

            results, metadata = self.gemini.generate_mnemonics(batch_spells)
            if not results:
                self.logger.warning(
                    f"[AI] {task_name} 批次 {batch_index + 1}/{total_batches} 返回空结果，跳过",
                    module="main",
                )
                processed_offset += len(batch_words)
                continue

            batch_id = str(uuid.uuid4())
            save_ai_batch(
                {
                    "batch_id": batch_id,
                    "request_id": (metadata or {}).get("request_id"),
                    "ai_provider": AI_PROVIDER,
                    "model_name": getattr(self.gemini, "model_name", ""),
                    "prompt_version": getattr(self.gemini, "prompt_version", ""),
                    "batch_size": len(batch_spells),
                    "total_latency_ms": (metadata or {}).get("total_latency_ms", 0),
                    "total_tokens": (metadata or {}).get("total_tokens", 0),
                    "finish_reason": (metadata or {}).get("finish_reason"),
                }
            )
            self._process_results(batch_words, results, processed_offset, total_words, batch_id)
            processed_offset += len(batch_words)

    def run(self):
        while True:
            # 每轮菜单前动态拉取今日/未来任务数量，避免界面固定显示 0。
            self.logger.info("[菜单] 正在刷新今日/未来任务数量...", module="main")
            today_items = []
            future_items = []
            try:
                today_res = self.momo.get_today_items(limit=500)
                today_items = (today_res or {}).get("data", {}).get("today_items", [])
            except Exception as e:
                self.logger.warning(f"今日任务拉取失败: {e}", module="main")

            try:
                start_dt = datetime.now()
                end_dt = start_dt + timedelta(days=7)
                future_res = self.momo.query_study_records(
                    start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                    end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
                )
                future_items = (future_res or {}).get("data", {}).get("records", [])
            except Exception as e:
                self.logger.warning(f"未来任务拉取失败: {e}", module="main")

            self.logger.info(
                f"[菜单] 刷新完成：今日 {len(today_items)}，未来 {len(future_items)}",
                module="main",
            )

            self.ui.render_main_menu(
                today_count=len(today_items),
                future_count=len(future_items),
                status_line=self.ui.consume_menu_status_line(),
            )
            choice = self._wait_for_choice(["1", "2", "3", "4"])

            if choice == "1":
                self.workflow.process_word_list(today_items, "今日任务")
            elif choice == "2":
                self.ui.ui_print("[INFO] 未来计划流程占位：请接入原任务拉取逻辑")
            elif choice == "3":
                manager = IterationManager(ai_client=self.ai_client, momo_api=self.momo, logger=self.logger)
                manager.run_iteration()
            else:
                break

    def shutdown(self):
        try:
            if getattr(self, "workflow", None):
                self.workflow.shutdown()
            if hasattr(self.momo, "close"):
                self.momo.close()
            if hasattr(self.ai_client, "close"):
                self.ai_client.close()
        finally:
            cleanup_concurrent_system()


def run(environment=None, config_file=None):
    manager = None
    try:
        manager = StudyFlowManager(environment=environment, config_file=config_file)
        manager.run()
    except KeyboardInterrupt:
        if manager and getattr(manager, "logger", None):
            manager.logger.info("用户手动退出", module="main")
    except Exception as e:
        if manager and getattr(manager, "logger", None):
            manager.logger.error(f"意外崩溃: {e}", exc_info=True, module="main")
        raise
    finally:
        if manager:
            manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="墨墨背单词AI助记系统（模块化入口）")
    parser.add_argument(
        "--env",
        "--environment",
        choices=["development", "staging", "production"],
        default=os.getenv("MOMO_ENV", "development"),
    )
    parser.add_argument("--config", "--config-file", default=os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml"))
    args = parser.parse_args()

    _disable_signal_wakeup_fd()
    run(environment=args.env, config_file=args.config)
