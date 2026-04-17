import sys
import io
import time
import uuid
import msvcrt
import os
import json
import argparse
import threading
import queue
import socket
import getpass
import signal
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from core.maimemo_api import MaiMemoAPI
from core.mimo_client import MimoClient
from core.iteration_manager import IterationManager
from core.db_manager import (
    # 核心数据库操作
    init_db, is_processed, mark_processed,
    save_ai_word_note, save_ai_batch, clean_for_maimemo,
    get_file_hash, archive_prompt_file, log_progress_snapshots, sync_databases,
    get_processed_ids_in_batch, get_unsynced_notes, get_local_word_note, get_word_note, mark_note_synced, set_note_sync_status,

    # 用户会话管理
    save_user_session, save_user_info_to_hub, save_user_credentials_to_hub, update_user_login_time,

    # 用户认证和权限
    # Hub 管理功能（保留供将来使用）
    update_user_stats, get_user_from_hub, list_hub_users, list_admin_logs,
    set_user_status,

    # 其他
    log_admin_action, sync_hub_databases, generate_user_id,
    is_hub_configured
)
from config import (
    MOMO_TOKEN, GEMINI_API_KEY, MIMO_API_KEY, BATCH_SIZE, DRY_RUN,
    AI_PROVIDER, ACTIVE_USER, PROMPT_FILE, SCORE_PROMPT_FILE, REFINE_PROMPT_FILE,
    FORCE_CLOUD_MODE, PROFILES_DIR, TURSO_DB_URL, TURSO_AUTH_TOKEN
)
from core.logger import setup_logger
from core.log_config import get_full_config
from core.log_archiver import auto_archive_logs


def _disable_signal_wakeup_fd() -> None:
    """关闭 wakeup fd，避免 Windows Ctrl+C 退出时打印信号唤醒噪音。"""
    try:
        if hasattr(signal, "set_wakeup_fd"):
            signal.set_wakeup_fd(-1)
    except Exception:
        pass

class StudyFlowManager:
    """墨墨背单词 AI 助记主流程管理器。"""

    def __init__(self, environment=None, config_file=None):
        # 获取环境配置
        self.environment = environment or os.getenv('MOMO_ENV', 'development')
        self.config_file = config_file or os.getenv('MOMO_CONFIG_FILE', 'config/logging.yaml')

        # 获取日志配置
        log_config = get_full_config(self.environment, self.config_file)

        # 设置日志器
        self.logger = setup_logger(
            ACTIVE_USER,
            environment=self.environment,
            config_file=self.config_file
        )

        # 设置会话ID和用户ID
        session_id = str(uuid.uuid4())
        # 生成一致的用户ID（由 db_manager 统一管理）
        user_id = generate_user_id(ACTIVE_USER)
        
        self.session_id = session_id
        self.user_id = user_id
        self.logger.set_context(session_id=session_id)

        self._menu_ui_lock = threading.Lock()
        self._menu_active = False
        self._menu_status_line = ""

        self.logger.info(
            f"启动墨墨背单词AI助记系统",
            environment=self.environment,
            session_id=session_id,
            module="main",
            function="__init__"
        )

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.sync_queue = queue.Queue()
        self.conflict_sync_queue = queue.Queue()
        self._post_sync_thread = None
        self._post_sync_result = None
        self._startup_sync_thread = None
        # 方案3：短期判重缓存（session + TTL）
        self._session_processed_ids = set()
        self._processed_cache = {}
        self._processed_cache_ttl_seconds = int(os.getenv("PROCESSED_CACHE_TTL_SECONDS", "900"))
        self._processed_cache_max_entries = int(os.getenv("PROCESSED_CACHE_MAX_ENTRIES", "50000"))
        self._sync_duration_history = {
            "用户数据库": [],
            "中央 Hub 数据库": [],
        }
        self._sync_duration_history_limit = int(os.getenv("SYNC_DURATION_HISTORY_LIMIT", "12"))
        self.sync_worker_thread = None
        self._sync_worker_stopped = False

        init_db()

        # 断点续传（通过数据库状态恢复同步队列）
        unsynced = get_unsynced_notes()
        if unsynced:
            self.logger.info(f"💾 [Resumption] 发现 {len(unsynced)} 条遗留待同步笔记，正在载入队列...")
            preview = [
                {
                    "voc_id": str(note.get("voc_id", "")),
                    "spelling": note.get("spelling", ""),
                    "content_origin": note.get("content_origin", ""),
                    "sync_status": 0,
                    "updated_at": note.get("updated_at", ""),
                }
                for note in unsynced[:10]
            ]
            self.logger.debug(
                f"[Resumption] 待读取快照预览(最多10条): {json.dumps(preview, ensure_ascii=False)}",
                module="main",
            )
            for note in unsynced:
                self.logger.debug(
                    f"[Resumption] 入队 voc_id={note.get('voc_id')} spelling={note.get('spelling')} origin={note.get('content_origin')} status=0",
                    module="main",
                )
                self._queue_maimemo_sync(
                    note['voc_id'], 
                    note['spelling'], 
                    clean_for_maimemo(note['basic_meanings']), 
                    ["雅思"] # 遗留同步默认打标为雅思
                )
        else:
            self.logger.debug("[Resumption] 当前没有遗留待同步笔记", module="main")

        self.sync_worker_thread = threading.Thread(target=self._maimemo_sync_worker, daemon=True)
        self.sync_worker_thread.start()

        # 确保 Hub 逻辑有序初始化，防止 FOREIGN KEY 约束失败
        try:
            # 交互式处理 Hub 配置缺失
            current_force_cloud = FORCE_CLOUD_MODE
            if current_force_cloud and not is_hub_configured():
                self._ui_notice(
                    "配置缺失",
                    "强制云端模式已开启，但未发现中央 Hub 数据库凭据。\n"
                    "通常是 .env 缺少 TURSO_HUB_DB_URL 和 TURSO_HUB_AUTH_TOKEN。\n\n"
                    "1) 立即输入 Hub 配置 (仅本会话)\n"
                    "2) 本次会话临时降级为本地模式\n"
                    "3) 退出并查看修复清单",
                    border_style="red",
                )

                h_choice = self._ask_text("请选择处理方式 (1-3)", default="1")
                if h_choice == "1":
                    hub_url = self._ask_text("请输入 TURSO_HUB_DB_URL")
                    hub_token = self._ask_secret("请输入 TURSO_HUB_AUTH_TOKEN")
                    if hub_url and hub_token:
                        os.environ['TURSO_HUB_DB_URL'] = hub_url
                        os.environ['TURSO_HUB_AUTH_TOKEN'] = hub_token
                        self._ui_print("✅ 已应用临时配置。", style="green")
                        
                        save_ch = self._ask_text("是否将此配置永久保存到 .env？(Y/N, 默认 N)", default="N").lower()
                        if save_ch == 'y':
                            from core.config_wizard import ConfigWizard
                            wiz = ConfigWizard(PROFILES_DIR)
                            wiz._save_hub_config_to_global_env(hub_url, hub_token)
                            self._ui_print("✅ 配置已写入 .env 文件。", style="green")
                    else:
                        self._ui_notice(
                            "配置不完整",
                            "Hub 配置不完整，程序退出。\n\n"
                            "修复建议:\n"
                            "1) 在 .env 中补全 TURSO_HUB_DB_URL 与 TURSO_HUB_AUTH_TOKEN\n"
                            "2) 或临时选择选项 2 以本地模式运行",
                            border_style="red",
                        )
                        raise SystemExit(1)
                elif h_choice == "2":
                    os.environ['FORCE_CLOUD_MODE'] = 'False'
                    self._ui_print("✅ 已临时关闭强制模式（仅当前进程生效）。", style="green")
                    
                    save_ch = self._ask_text("是否永久关闭强制模式（即默认本地运行）？(Y/N, 默认 N)", default="N").lower()
                    if save_ch == 'y':
                        try:
                            # 导入基本路径以寻找 .env
                            from config import BASE_DIR
                            env_path = os.path.join(BASE_DIR, ".env")
                            lines = []
                            if os.path.exists(env_path):
                                with open(env_path, 'r', encoding='utf-8') as f:
                                    for line in f:
                                        if not line.strip().startswith('FORCE_CLOUD_MODE'):
                                            lines.append(line.rstrip())
                            lines.append('FORCE_CLOUD_MODE="False"')
                            with open(env_path, 'w', encoding='utf-8') as f:
                                f.write('\n'.join(lines) + '\n')
                            self._ui_print("✅ 已将 FORCE_CLOUD_MODE=False 写入 .env 文件。", style="green")
                        except Exception as ex:
                            self._ui_print(f"❌ 保存失败: {ex}", style="red")
                else:
                    self._ui_notice(
                        "已退出",
                        "修复清单:\n"
                        "- 在全局 .env 中配置 TURSO_HUB_DB_URL\n"
                        "- 在全局 .env 中配置 TURSO_HUB_AUTH_TOKEN\n"
                        f"- 运行体检: python tools/preflight_check.py --user {ACTIVE_USER}",
                        border_style="yellow",
                    )
                    raise SystemExit(1)

            # 复用数据库连接以提高性能，并顺手读取当前用户角色，避免重复握手
            from core.db_manager import _get_hub_conn, _row_to_dict
            hub_conn = _get_hub_conn()

            hub_cur = hub_conn.cursor()
            hub_cur.execute('SELECT * FROM users WHERE lower(username) = ?', (ACTIVE_USER.strip().lower(),))
            existing_hub_row = hub_cur.fetchone()
            self.hub_user = _row_to_dict(hub_cur, existing_hub_row) if existing_hub_row else None
            existing_role = (self.hub_user or {}).get('role', '')
            self.is_admin = ACTIVE_USER.strip().lower() == 'asher' or existing_role.lower() == 'admin'

            # 1. 优先确保用户信息存在（users 表是 parent）
            save_user_info_to_hub(
                user_id,
                ACTIVE_USER,
                f"{ACTIVE_USER}@local",
                user_notes="自动登录记录",
                role="admin" if self.is_admin else "user",
                conn=hub_conn
            )

            # 同步当前用户的敏感配置到 Hub（加密存储，需 ENCRYPTION_KEY）
            save_user_credentials_to_hub(
                user_id,
                {
                    "turso_db_url": TURSO_DB_URL,
                    "turso_auth_token": TURSO_AUTH_TOKEN,
                    "momo_token": MOMO_TOKEN,
                    "mimo_api_key": MIMO_API_KEY,
                    "gemini_api_key": GEMINI_API_KEY,
                },
                conn=hub_conn,
            )

            update_user_login_time(user_id, conn=hub_conn)

            # 2. 只有用户信息成功记录后，才记录会话（user_sessions 表是 child）
            client_info = json.dumps({
                "os": sys.platform,
                "python_version": sys.version.split()[0],
                "ai_provider": AI_PROVIDER
            })
            ip_address = self._get_client_ip()
            save_user_session(user_id, session_id, client_info, ip_address, conn=hub_conn)
            self.logger.info(f"用户会话已记录到 Hub: {user_id}", session_id=session_id)

            # 如果是管理员，记录登录日志（在连接关闭前）
            if self.is_admin:
                log_admin_action(
                    "admin_login",
                    f"管理员 {ACTIVE_USER} 登录",
                    ACTIVE_USER,
                    target_user_id=user_id,
                    conn=hub_conn
                )

            # 提交并关闭连接
            hub_conn.commit()
            hub_conn.close()
        except Exception as e:
            self.logger.warning(f"会话记录失败（非关键）：{e}")
        
        # 如果启用了自动归档，执行一次归档
        if log_config.get("enable_compression", False):
            try:
                self.logger.info("执行自动日志归档", module="main", function="__init__")
                archived, removed = auto_archive_logs(
                    log_config["log_dir"],
                    log_config
                )
                self.logger.info(
                    f"自动归档完成: 归档{len(archived)}个文件, 清理{len(removed)}个文件",
                    archived_count=len(archived),
                    removed_count=len(removed),
                    module="main",
                    function="__init__"
                )
            except Exception as e:
                self.logger.warning(
                    f"自动归档失败: {e}",
                    error=str(e),
                    module="main",
                    function="__init__"
                )
        
        # 移除强制启动同步，改为主循环中互动式检查
        
        # A. 提示词多版本归档
        prompts = [
            (PROMPT_FILE, "main"),
            (SCORE_PROMPT_FILE, "score"),
            (REFINE_PROMPT_FILE, "refine")
        ]
        self.prompt_hashes = {}
        for p_path, p_type in prompts:
            h = get_file_hash(p_path)
            self.prompt_hashes[p_type] = h
            archive_prompt_file(p_path, h, p_type)
            self.logger.info(f"📝 [Prompt] {p_type.capitalize()} 版本: {h}", module="main", function="__init__")
        
        self.prompt_version = self.prompt_hashes["main"]

        # B. 初始化 AI 客户端
        if AI_PROVIDER == "mimo":
            if not MIMO_API_KEY: raise ValueError("MIMO_API_KEY required")
            self.ai_client = MimoClient(MIMO_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (小米 Mimo)")
        else:
            from core.gemini_client import GeminiClient
            if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY required")
            self.ai_client = GeminiClient(GEMINI_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (Google Gemini)")

        # Backward compatibility for legacy tests/scripts that still access "gemini".
        self.gemini = self.ai_client

    @staticmethod
    def _get_client_ip() -> str:
        """获取本机出口 IP，失败时回退 localhost。"""
        # 使用 UDP 套接字探测本机对外路由地址（不会真正发包）
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip:
                    return ip
            finally:
                s.close()
        except Exception:
            pass

        # 回退：主机名解析
        try:
            host_ip = socket.gethostbyname(socket.gethostname())
            if host_ip and host_ip != "127.0.0.1":
                return host_ip
        except Exception:
            pass

        return "127.0.0.1"

    def _prune_processed_cache(self):
        if len(self._processed_cache) <= self._processed_cache_max_entries:
            return
        # 淘汰最旧的一批键，避免缓存无限增长
        overflow = len(self._processed_cache) - self._processed_cache_max_entries
        keys = sorted(self._processed_cache.items(), key=lambda kv: kv[1].get("ts", 0.0))
        for k, _ in keys[:overflow]:
            self._processed_cache.pop(k, None)

    def _get_processed_ids_cached(self, voc_ids):
        now = time.time()
        processed_ids = set()
        to_query = []

        for vid in voc_ids:
            v = str(vid)
            if v in self._session_processed_ids:
                processed_ids.add(v)
                continue

            cached = self._processed_cache.get(v)
            if cached and (now - cached.get("ts", 0.0) <= self._processed_cache_ttl_seconds):
                if cached.get("processed"):
                    processed_ids.add(v)
                continue

            to_query.append(v)

        if to_query:
            fresh_processed = set(get_processed_ids_in_batch(to_query))
            for v in to_query:
                is_processed = v in fresh_processed
                self._processed_cache[v] = {"processed": is_processed, "ts": now}
                if is_processed:
                    self._session_processed_ids.add(v)
            processed_ids.update(fresh_processed)
            self._prune_processed_cache()

        return processed_ids

    def _mark_processed_with_cache(self, voc_id, spelling):
        v = str(voc_id)
        mark_processed(v, spelling)
        now = time.time()
        self._session_processed_ids.add(v)
        self._processed_cache[v] = {"processed": True, "ts": now}

    def _invalidate_processed_cache(self, only_negative=True):
        if only_negative:
            stale_keys = [k for k, v in self._processed_cache.items() if not v.get("processed")]
            for k in stale_keys:
                self._processed_cache.pop(k, None)
        else:
            self._processed_cache.clear()
            self._session_processed_ids.clear()

    def _canonical_sync_label(self, label: str) -> str:
        text = str(label or "")
        if "用户数据库" in text:
            return "用户数据库"
        if "中央 Hub" in text:
            return "中央 Hub 数据库"
        return ""

    def _record_sync_duration(self, label: str, duration_ms: int, status: str = "ok") -> None:
        canonical = self._canonical_sync_label(label)
        if not canonical:
            return
        if duration_ms <= 0:
            return

        normalized_status = str(status or "ok").lower()
        if normalized_status in {"error", "failed", "fail", "skipped"}:
            return

        bucket = self._sync_duration_history.get(canonical)
        if bucket is None:
            return
        bucket.append(int(duration_ms))
        overflow = len(bucket) - self._sync_duration_history_limit
        if overflow > 0:
            del bucket[0:overflow]

    def _estimate_exit_sync_timeout_s(self, default_timeout_s: float) -> float:
        def _p80(values):
            if not values:
                return 0
            ordered = sorted(int(v) for v in values)
            idx = max(0, int((len(ordered) - 1) * 0.8))
            return ordered[idx]

        user_p80 = _p80(self._sync_duration_history.get("用户数据库", []))
        hub_p80 = _p80(self._sync_duration_history.get("中央 Hub 数据库", []))
        if user_p80 <= 0 and hub_p80 <= 0:
            return default_timeout_s

        estimated_total_s = ((user_p80 + hub_p80) / 1000.0) * 1.2 + 1.0
        bounded_timeout_s = max(default_timeout_s, min(45.0, estimated_total_s))
        return round(bounded_timeout_s, 1)

    def _queue_maimemo_sync(self, voc_id, spell, interpretation, tags):
        if DRY_RUN:
            return
        self.sync_queue.put({
            "voc_id": str(voc_id),
            "spell": spell,
            "interpretation": interpretation,
            "tags": list(tags or []),
        })

    def _defer_maimemo_conflict(self, item, reason: str):
        self.conflict_sync_queue.put(item)
        self.logger.warning(
            f"⚠️ {item.get('spell', item.get('voc_id', 'unknown'))} 已进入冲突队列: {reason}",
            module="main",
        )

    def _maimemo_sync_worker(self):
        while True:
            item = self.sync_queue.get()
            try:
                if item is None:
                    break

                voc_id = item["voc_id"]
                spell = item["spell"]
                interpretation = item["interpretation"]
                tags = item["tags"] or ["雅思"]

                # 出队前二次校验当前数据库状态，避免启动快照过期。
                current_note = None
                try:
                    current_note = get_local_word_note(voc_id)
                except Exception as local_read_error:
                    self.logger.warning(
                        f"⚠️ {spell} 本地数据库读取失败，尝试云端/主连接重试: {local_read_error}",
                        module="main",
                    )

                if not current_note:
                    # 本地未命中时再查一次主连接（可能是云端连接），避免误判。
                    try:
                        current_note = get_word_note(voc_id)
                    except Exception as fallback_read_error:
                        self.logger.warning(
                            f"⚠️ {spell} 主连接读取失败，本次同步跳过: {fallback_read_error}",
                            module="main",
                        )
                if not current_note:
                    self.logger.warning(
                        f"⚠️ {spell} 未在数据库中检索到记录（可能尚未落库或已删除），本次跳过同步",
                        module="main",
                    )
                    continue

                current_status = int(current_note.get("sync_status", 0) or 0)
                status_desc = {
                    0: "待同步",
                    1: "已同步（墨墨已创建释义与本地一致）",
                    2: "冲突（墨墨已创建释义与本地不一致）",
                }.get(current_status, "未知状态")
                if current_status == 2:
                    self._defer_maimemo_conflict(item, "当前状态已是冲突态")
                    continue
                if current_status != 0:
                    self.logger.info(
                        f"ℹ️ {spell} 当前sync_status={current_status}（{status_desc}），跳过重复同步",
                        module="main",
                    )
                    continue

                try:
                    sync_result = self.momo.sync_interpretation(
                        voc_id,
                        interpretation,
                        tags=tags,
                        spell=spell,
                        force_create=True,
                        local_reference=interpretation,
                        return_details=True,
                    )
                    sync_status = 1
                    if isinstance(sync_result, dict):
                        sync_status = int(sync_result.get("sync_status", 0) or 0)
                    elif sync_result:
                        sync_status = 1
                    else:
                        sync_status = 0
                    sync_reason = sync_result.get("reason", "") if isinstance(sync_result, dict) else ""

                    if sync_status == 1:
                        try:
                            self._mark_processed_with_cache(voc_id, spell)
                        except Exception as cache_error:
                            self.logger.warning(f"⚠️ {spell} 已同步，但处理缓存更新失败: {cache_error}", module="main")
                        try:
                            ok = mark_note_synced(voc_id)  # 物理数据库打标，不再被缓存异常阻断
                            if not ok:
                                self.logger.warning(
                                    f"⚠️ {spell} 数据库状态写回未命中：目标sync_status=1（已同步）",
                                    module="main",
                                )
                        except Exception as sync_error:
                            self.logger.warning(f"⚠️ {spell} 同步状态写回失败: {sync_error}", module="main")
                    elif sync_status == 2:
                        try:
                            self._mark_processed_with_cache(voc_id, spell)
                        except Exception as cache_error:
                            self.logger.warning(f"⚠️ {spell} 冲突态已写回，但处理缓存更新失败: {cache_error}", module="main")
                        try:
                            ok = set_note_sync_status(voc_id, 2)
                            if not ok:
                                self.logger.warning(
                                    f"⚠️ {spell} 数据库状态写回未命中：目标sync_status=2（冲突）",
                                    module="main",
                                )
                        except Exception as sync_error:
                            self.logger.warning(f"⚠️ {spell} 冲突状态写回失败: {sync_error}", module="main")
                        self.logger.warning(f"⚠️ {spell} 云端释义与数据库内容不一致，已标记为冲突", module="main")
                    else:
                        if sync_reason:
                            self.logger.warning(
                                f"⚠️ {spell} 墨墨同步未完成: {sync_reason}",
                                module="main",
                            )
                        else:
                            self.logger.warning(f"⚠️ {spell} 墨墨同步未完成", module="main")
                except Exception as e:
                    self.logger.error(f"❌ {spell} 后台同步异常: {e}", module="main")
            finally:
                self.sync_queue.task_done()

        self._sync_worker_stopped = True

    def _flush_pending_maimemo_syncs(self, context_name: str):
        pending_count = self.sync_queue.qsize()
        if pending_count > 0:
            self.logger.info(
                f"🔁 还有 {pending_count} 个 {context_name} 结果正在后台同步，可继续其他操作。",
                module="main",
            )

    def shutdown(self):
        if not getattr(self, "sync_worker_thread", None):
            return

        pending_count = self.sync_queue.qsize()
        self.logger.info(f"退出前准备关闭后台同步线程，剩余任务 {pending_count} 个，请稍等...", module="main")
        self.sync_queue.put(None)
        self.sync_worker_thread.join(timeout=10.0)
        if self.sync_worker_thread.is_alive():
            self.logger.warning("后台同步线程未在 10 秒内结束，强行退出流程", module="main")
        else:
            self.logger.info("✅ 后台同步线程已平滑退出", module="main")

    def _check_esc_interrupt(self):
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ord(ch) == 27:
                print("\n" + "!"*30)
                print("检测到 Esc 键，正在中断并保存...")
                print("!"*30)
                self.logger.warning(" 检测到 Esc 键，正在中断并保存...")
                raise KeyboardInterrupt
            return ch
        return None

    def _wait_for_choice(self, valid_choices: list) -> str:
        """回归标准 input 以确保跨终端兼容性。"""
        while True:
            try:
                choice = input("请输入选项序号 (或按 Ctrl+C 退出): ").strip()
                if choice in valid_choices:
                    return choice
                print(f"❌ 无效选项，请从 {valid_choices} 中选择。")
            except (KeyboardInterrupt, EOFError):
                # 统一交给顶层异常处理，避免在被中断的终端句柄上二次输出导致 OSError。
                raise KeyboardInterrupt

    def _render_main_menu(self, today_count: int, future_count: int, status_line: str = ""):
        print("\n" + "=" * 35)
        print(f"👤 用户: {ACTIVE_USER} | 模式选择")
        print("=" * 35)
        print(f"  1. [今日任务] 处理今日待复习 ({today_count} 个)")
        if today_count == 0:
            print("     提示: 当前无今日待复习，可能需要先在墨墨 App 初始化计划")
        print(f"  2. [未来计划] 处理未来 7 天待学 ({future_count} 个)")
        print("  3. [智能迭代] 优化薄弱词助记 (基于数据反馈)")
        print("  4. [同步&退出] 保存所有数据并安全退出")
        print("-" * 35)
        if status_line:
            print(f"[状态] {status_line}")

    def _ui_print(self, message: str, style: str = ""):
        del style
        print(str(message or ""))

    def _ui_notice(self, title: str, message: str, border_style: str = "cyan"):
        del border_style
        print(f"\n[{title}]\n{message}")

    def _ask_text(self, prompt_text: str, default: str = "") -> str:
        if default:
            raw = input(f"{prompt_text} (默认: {default}): ").strip()
            return raw or default
        return input(f"{prompt_text}: ").strip()

    def _ask_secret(self, prompt_text: str) -> str:
        return getpass.getpass(f"{prompt_text}: ").strip()

    def _clear_screen(self):
        return

    def _set_menu_status_line(self, message: str):
        """在菜单输入期间更新底部状态栏文本，不打断菜单区域。"""
        with self._menu_ui_lock:
            self._menu_status_line = str(message or "").strip()

    def _consume_menu_status_line(self) -> str:
        with self._menu_ui_lock:
            text = self._menu_status_line
            self._menu_status_line = ""
            return text

    def _is_menu_active(self) -> bool:
        with self._menu_ui_lock:
            return bool(self._menu_active)

    def _set_menu_active(self, active: bool):
        with self._menu_ui_lock:
            self._menu_active = bool(active)

    def _install_menu_log_buffering(self):
        return

    def _append_ui_log(self, level: str, message: str) -> None:
        del level, message
        return

    def _should_buffer_log(self, level: str) -> bool:
        del level
        return False

    def _flush_buffered_logs(self):
        return

    def _render_log_panel(self):
        return

    def _render_sync_progress(self, label: str, progress: dict):
        """在 CLI 中渲染同步进度，不影响核心同步逻辑。"""
        current = int(progress.get("current", 0) or 0)
        total = int(progress.get("total", 0) or 0)
        message = progress.get("message", "")
        stage = progress.get("stage", "")

        if total > 0:
            width = 24
            ratio = min(max(current / total, 0.0), 1.0)
            filled = int(width * ratio)
            bar = "#" * filled + "-" * (width - filled)
            text = f"🔄 [{label}] [{bar}] {current}/{total} {message}"
            print(f"\r{text}", end="", flush=True)
            if stage in {"finalize", "error"} or current >= total:
                print()
        else:
            self._ui_print(f"🔄 [{label}] {message}", style="cyan")

    def _run_sync_with_progress(self, label: str, sync_func, dry_run: bool = False) -> dict:
        """前台同步时显示阶段进度；若函数不支持回调则自动降级。"""
        start_time = time.time()
        if dry_run:
            result = sync_func(dry_run=True)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self.logger.info(
                f"⏱️ [{label}] Dry Run 耗时 {duration_ms}ms",
                duration=duration,
                duration_ms=duration_ms,
                module="main",
                function="_run_sync_with_progress",
            )
            return result

        def _on_progress(payload: dict):
            self._render_sync_progress(label, payload)

        try:
            result = sync_func(dry_run=False, progress_callback=_on_progress)
        except TypeError:
            # 兼容测试中的简化 mock 或旧签名
            self._ui_print(f"🔄 [{label}] 开始同步...", style="cyan")
            result = sync_func(dry_run=False)
            self._ui_print(f"✅ [{label}] 同步完成", style="green")

        duration = time.time() - start_time
        duration_ms = int(duration * 1000)
        self._record_sync_duration(label, duration_ms, (result or {}).get("status", "ok"))
        self.logger.info(
            f"⏱️ [{label}] 同步耗时 {duration_ms}ms",
            duration=duration,
            duration_ms=duration_ms,
            upload=(result or {}).get("upload"),
            download=(result or {}).get("download"),
            status=(result or {}).get("status", "ok"),
            module="main",
            function="_run_sync_with_progress",
        )
        return result

    def _run_sync_with_stage_logs(self, label: str, sync_func) -> dict:
        """后台同步时记录阶段日志，不输出进度条。"""
        start_time = time.time()

        def _on_progress(payload: dict):
            stage = payload.get("stage", "")
            message = payload.get("message", "")
            if stage in {"error", "table-error"}:
                self.logger.warning(f"[{label}] {message}", module="main")
            else:
                self.logger.info(f"[{label}] {message}", module="main")

        try:
            result = sync_func(dry_run=False, progress_callback=_on_progress)
        except TypeError:
            self.logger.info(f"[{label}] 开始同步", module="main")
            result = sync_func(dry_run=False)
            self.logger.info(f"[{label}] 同步完成", module="main")

        duration = time.time() - start_time
        duration_ms = int(duration * 1000)
        self._record_sync_duration(label, duration_ms, (result or {}).get("status", "ok"))
        self.logger.info(
            f"⏱️ [{label}] 后台同步耗时 {duration_ms}ms",
            duration=duration,
            duration_ms=duration_ms,
            upload=(result or {}).get("upload"),
            download=(result or {}).get("download"),
            status=(result or {}).get("status", "ok"),
            module="main",
            function="_run_sync_with_stage_logs",
        )
        return result

    def _apply_startup_sync_result(self, stats: dict, interactive: bool):
        """应用启动一致性检查结果；interactive=False 时仅记录日志不打断流程。"""
        un_up = stats.get('upload', 0)
        un_down = stats.get('download', 0)
        sync_status = stats.get('status', 'ok')
        sync_reason = stats.get('reason', '')

        if sync_status == 'skipped':
            msg = f"⚠️ 未执行云端一致性检查: {sync_reason}"
            if not interactive and self._is_menu_active():
                self._set_menu_status_line(msg)
            else:
                self.logger.warning(msg)
            self.data_merged = False
            return

        if sync_status == 'error':
            msg = f"⚠️ 云端一致性检查失败: {sync_reason}"
            if not interactive and self._is_menu_active():
                self._set_menu_status_line(msg)
            else:
                self.logger.warning(msg)
            self.data_merged = False
            return

        if un_up > 0 or un_down > 0:
            self.data_merged = False
            if interactive:
                self._ui_notice(
                    "发现同步差异",
                    f"云端有 {un_down} 条新数据，本地有 {un_up} 条待上传。",
                    border_style="yellow",
                )
                ch = self._ask_text("是否立即进行合并？(Y/N, 默认 Y)", default="Y").lower()
                if ch != 'n':
                    self.logger.info("🚩 正在同步数据库，请稍候...")
                    self._run_sync_with_progress("用户数据库", sync_databases, dry_run=False)
                    self._run_sync_with_progress("中央 Hub", sync_hub_databases, dry_run=False)
                    self.logger.info("✅ 数据同步完成。")
                    self.data_merged = True
                else:
                    self.logger.warning("用户选择跳过同步，可能导致本地运行基于旧数据。")
            else:
                msg = (
                    f"后台检查完成：云端新增 {un_down} 条，本地待上传 {un_up} 条。"
                    "可在菜单选择 4 执行同步。"
                )
                if self._is_menu_active():
                    self._set_menu_status_line(msg)
                else:
                    self.logger.warning(f"⚠️ {msg}", module="main")
            return

        if not interactive and self._is_menu_active():
            self._set_menu_status_line("后台检查完成：云端与本地数据一致。")
        else:
            self.logger.info("✅ 云端与本地数据一致，无需同步。")
        self.data_merged = True

    def run(self):
        # 启动时执行 Dry Run 检查一致性（限时等待，超时转后台）
        self.logger.info("正在检测云端数据同步状态...")
        self.data_merged = False
        startup_timeout = float(os.getenv("STARTUP_SYNC_CHECK_TIMEOUT_S", "2.5"))
        startup_begin = time.time()
        startup_result = {"stats": None}
        done = threading.Event()

        def _startup_check_worker():
            try:
                startup_result["stats"] = sync_databases(dry_run=True)
            except Exception as e:
                startup_result["stats"] = {
                    "upload": 0,
                    "download": 0,
                    "status": "error",
                    "reason": str(e),
                }
            finally:
                done.set()

        self._startup_sync_thread = threading.Thread(target=_startup_check_worker, daemon=True)
        self._startup_sync_thread.start()

        if done.wait(timeout=startup_timeout):
            startup_wait_ms = int((time.time() - startup_begin) * 1000)
            self.logger.info(
                f"⏱️ 启动一致性检查前台完成，耗时 {startup_wait_ms}ms",
                duration=startup_wait_ms / 1000,
                duration_ms=startup_wait_ms,
                timeout_s=startup_timeout,
                module="main",
                function="run",
            )
            self._apply_startup_sync_result(startup_result.get("stats") or {}, interactive=True)
        else:
            startup_wait_ms = int((time.time() - startup_begin) * 1000)
            self.logger.info(
                f"⏱️ 启动一致性检查超过 {startup_timeout:.1f}s，先进入主菜单，后台继续检查。",
                duration=startup_wait_ms / 1000,
                duration_ms=startup_wait_ms,
                timeout_s=startup_timeout,
                module="main"
            )

            def _finalize_startup_check():
                done.wait()
                total_startup_check_ms = int((time.time() - startup_begin) * 1000)
                stats = startup_result.get("stats") or {
                    "upload": 0,
                    "download": 0,
                    "status": "error",
                    "reason": "missing-startup-sync-result",
                }
                if self._is_menu_active():
                    self._set_menu_status_line(f"后台一致性检查完成，耗时 {total_startup_check_ms}ms")
                else:
                    self.logger.info(
                        f"⏱️ 启动一致性检查后台完成，总耗时 {total_startup_check_ms}ms",
                        duration=total_startup_check_ms / 1000,
                        duration_ms=total_startup_check_ms,
                        module="main",
                        function="run",
                    )
                self._apply_startup_sync_result(stats, interactive=False)

            threading.Thread(target=_finalize_startup_check, daemon=True).start()

        while True:
            self._set_menu_active(True)
            # 获取今日任务
            res_today = self.momo.get_today_items(limit=500)
            today_task = res_today.get("data", {}).get("today_items", []) if res_today else []

            # 获取预习计划
            start_dt = datetime.now()
            end_dt = start_dt + timedelta(days=7)
            res_future = self.momo.query_study_records(
                start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
            )
            future_task = res_future.get("data", {}).get("records", []) if res_future else []

            status_line = self._consume_menu_status_line()
            self._render_main_menu(len(today_task), len(future_task), status_line)

            choice = self._wait_for_choice(["1", "2", "3", "4"])
            self._set_menu_active(False)
            self._flush_buffered_logs()
            
            if choice == "1":
                if not today_task:
                    self.logger.info("今日任务为空，返回主菜单。")
                    continue
                self._process_word_list(today_task, "今日任务")
                self._trigger_post_run_sync()
            elif choice == "2":
                # 允许用户自定义预习天数
                try:
                    days_input = self._ask_text("请输入预习天数 (建议 1-14 天, 回车默认为 7)", default="7")
                    if not days_input:
                        days = 7
                        selected_task = future_task # 复用初始获取的 7 天数据
                    else:
                        days = int(days_input)
                        if days <= 0: raise ValueError
                        self.logger.info(f"正在重新获取未来 {days} 天的任务...")
                        end_dt = start_dt + timedelta(days=days)
                        res_new = self.momo.query_study_records(
                            start_dt.strftime("%Y-%m-%dT00:00:00.000Z"), 
                            end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
                        )
                        selected_task = res_new.get("data", {}).get("records", []) if res_new else []
                    
                    self.logger.info(f"已选取未来 {days} 天任务，共 {len(selected_task)} 个单词")
                    self._process_word_list(selected_task, f"未来 {days} 天计划")
                    self._trigger_post_run_sync()
                except ValueError:
                    self._ui_print("❌ 输入无效，必须是正整数。回到主菜单。", style="red")
            elif choice == "3":
                im = IterationManager(self.ai_client, self.momo, self.logger)
                im.run_iteration()
                self._trigger_post_run_sync()
            elif choice == "4":
                self.logger.info("正在执行最后的数据同步...")
                self._run_sync_with_progress("用户数据库", sync_databases, dry_run=False)
                self._run_sync_with_progress("中央 Hub", sync_hub_databases, dry_run=False)
                self.logger.info("✅ 已安全保存所有数据至云端。再见！")
                break

    def _trigger_post_run_sync(self):
        """主流程结束后触发一次非阻塞或快捷的同步。"""
        if self._post_sync_thread and self._post_sync_thread.is_alive():
            self.logger.info("🔁 检测到已有后台同步任务正在运行，跳过重复触发。", module="main")
            return

        self.logger.info("🔁 正在后台将最新进度推送到云端...", module="main")
        def _sync_all_in_background():
            start_time = time.time()
            overall_status = "success"
            task_summaries = []

            def _merge_status(next_status: str) -> None:
                nonlocal overall_status
                rank = {"success": 0, "partial": 1, "failed": 2}
                if rank.get(str(next_status).lower(), 2) > rank.get(overall_status, 0):
                    overall_status = str(next_status).lower()

            try:
                user_result = self._run_sync_with_stage_logs("后台-用户数据库", sync_databases)
                user_status = str((user_result or {}).get("status", "ok")).lower()
                if user_status in {"error", "failed", "fail"}:
                    _merge_status("failed")
                    task_summaries.append("后台-用户数据库: failed")
                elif user_status in {"timeout", "partial"}:
                    _merge_status("partial")
                    task_summaries.append("后台-用户数据库: partial")
                else:
                    task_summaries.append("后台-用户数据库: ok")

                hub_result = self._run_sync_with_stage_logs("后台-中央 Hub", sync_hub_databases)
                hub_status = str((hub_result or {}).get("status", "ok")).lower()
                if hub_status in {"error", "failed", "fail"}:
                    _merge_status("failed")
                    task_summaries.append("后台-中央 Hub: failed")
                elif hub_status in {"timeout", "partial"}:
                    _merge_status("partial")
                    task_summaries.append("后台-中央 Hub: partial")
                else:
                    task_summaries.append("后台-中央 Hub: ok")

                # 后台同步后仅失效负缓存，避免重复查库且保证远端新增可见
                if overall_status == "success":
                    self._invalidate_processed_cache(only_negative=True)
            except Exception as e:
                _merge_status("failed")
                task_summaries.append(f"后台同步失败: {e}")
                self.logger.warning(f"后台同步失败: {e}", module="main")
            finally:
                self._post_sync_result = {
                    "overall_status": overall_status,
                    "task_summaries": task_summaries,
                }
                duration = time.time() - start_time
                duration_ms = int(duration * 1000)
                self.logger.info(
                    f"⏱️ 后台同步总耗时 {duration_ms}ms",
                    duration=duration,
                    duration_ms=duration_ms,
                    module="main",
                    function="_trigger_post_run_sync",
                )

        self._post_sync_thread = threading.Thread(target=_sync_all_in_background, daemon=True)
        self._post_sync_thread.start()

    def _process_word_list(self, word_list, name):
        if not word_list:
            self.logger.info(f"{name} 列表为空。")
            return
            
        self.logger.info(f"正在启动 {name} 处理流程...")

        # 先做输入去重，避免同一 voc_id 在热路径里重复查词、重复写回和重复同步
        deduped_words = []
        seen_voc_ids = set()
        duplicate_count = 0
        for word in word_list:
            voc_id = str(word.get("voc_id") or "").strip()
            if not voc_id:
                continue
            if voc_id in seen_voc_ids:
                duplicate_count += 1
                continue
            seen_voc_ids.add(voc_id)
            deduped_words.append(word)

        if duplicate_count:
            self.logger.info(f"已去重 {duplicate_count} 个重复词条")

        word_list = deduped_words
        
        # 1. 记录进度快照 (Smart Snapshot)
        count = log_progress_snapshots(word_list)
        if count > 0:
            self.logger.info(f"📈 [Track] 已更新 {count} 个单词的进度流水")

        # 2. 过滤已有 AI 笔记的单词 (批量检查 ai_word_notes 表)
        self.logger.info(f"正在批量检查 {len(word_list)} 个单词的 AI 笔记...")

        # 提取所有 voc_id
        all_voc_ids = [str(w.get("voc_id")) for w in word_list]

        # 先批量过滤已处理词，避免重复同步和重复日志
        processed_ids = self._get_processed_ids_cached(all_voc_ids)
        if processed_ids:
            self.logger.info(f"已过滤 {len(processed_ids)} 个已处理单词")

        # 批量查询云端/本地数据库
        from core.db_manager import find_words_in_community_batch, save_ai_word_notes_batch

        # 今日任务/未来计划优先本地命中，避免把云端查词放进热路径
        hot_path_name = name == "今日任务" or name.startswith("未来")
        skip_cloud = getattr(self, 'data_merged', False) or hot_path_name
        if skip_cloud:
            self.logger.info("本次处理启用本地优先策略，跳过云端补查...")
        else:
            self.logger.info("未合并数据，查询云端数据库...")

        cached_notes = find_words_in_community_batch(
            all_voc_ids,
            skip_cloud=skip_cloud,
            ai_provider=AI_PROVIDER,
            prompt_version=self.prompt_version,
        )

        pending_words = []
        skipped_processed = 0
        try:
            # 批量处理缓存命中的单词
            cached_words = []
            for w in word_list:
                self._check_esc_interrupt()
                voc_id = str(w.get("voc_id"))
                spell = w.get("voc_spelling")

                if voc_id in processed_ids:
                    skipped_processed += 1
                    continue

                # 检查是否有 AI 笔记（从批量查询结果中获取）
                if voc_id in cached_notes:
                    community_note, source_db = cached_notes[voc_id]
                    self.logger.info(f"  🏆 [Cache Hit] {spell} - {source_db}")
                    if source_db == "当前数据库":
                        content_origin = "current_db_reused"
                        content_source_scope = "local"
                    elif source_db == "云端数据库":
                        content_origin = "community_reused"
                        content_source_scope = "cloud"
                    else:
                        content_origin = "history_reused"
                        content_source_scope = "local_history"
                    cached_words.append({
                        'voc_id': voc_id,
                        'spell': spell,
                        'community_note': community_note,
                        'source_db': source_db,
                        'content_origin': content_origin,
                        'content_source_db': source_db,
                        'content_source_scope': content_source_scope,
                    })
                else:
                    pending_words.append(w)

            if skipped_processed:
                self.logger.info(f"跳过 {skipped_processed} 个已完成处理的单词")

            # 批量保存缓存命中的笔记
            if cached_words:
                notes_data = [{
                    'voc_id': item['voc_id'],
                    'payload': item['community_note'],
                    'metadata': {
                        'content_origin': item['content_origin'],
                        'content_source_db': item['content_source_db'],
                        'content_source_scope': item['content_source_scope'],
                    }
                } for item in cached_words]
                save_ai_word_notes_batch(notes_data)

                # 将同步延后到处理结束，减少热路径里的阻塞调用
                for item in cached_words:
                    brief = clean_for_maimemo(item['community_note'].get('basic_meanings', ''))
                    self._queue_maimemo_sync(item['voc_id'], item['spell'], brief, ["雅思", "考研"])

                if DRY_RUN:
                    for item in cached_words:
                        self._mark_processed_with_cache(item['voc_id'], item['spell'])

            if not pending_words:
                self.logger.info("✨ 无需调用 AI。")
                return

            self.logger.info(f"💎 [AI Phase] 需解析 {len(pending_words)} 个单词")

            # 方案2：AI 生成与写入/同步流水化
            # - 受控并发生成（默认 2 线程）
            # - 主线程按批次顺序落库/同步，保证语义与日志顺序稳定
            total_pending = len(pending_words)
            max_safe_batch = max(BATCH_SIZE, int(os.getenv("MAX_SAFE_BATCH_SIZE", "25")))
            min_batch = 1
            current_batch_size = max(min_batch, BATCH_SIZE)
            ai_workers = max(1, int(os.getenv("AI_PIPELINE_WORKERS", "2")))
            submit_gap = float(os.getenv("AI_BATCH_SUBMIT_DELAY_S", "0.3"))

            next_pos = 0
            next_batch_idx = 0
            expected_idx = 0
            in_flight = {}
            last_submit_ts = 0.0

            def _submit_next(executor):
                nonlocal next_pos, next_batch_idx, last_submit_ts
                if next_pos >= total_pending:
                    return False

                now = time.time()
                if now - last_submit_ts < submit_gap:
                    time.sleep(submit_gap - (now - last_submit_ts))

                batch = pending_words[next_pos: next_pos + current_batch_size]
                start_pos = next_pos
                idx = next_batch_idx
                next_pos += len(batch)
                next_batch_idx += 1

                batch_spells = [w["voc_spelling"] for w in batch]
                self.logger.debug(
                    f"批次 {idx + 1} 入队 ({start_pos + len(batch)}/{total_pending}) | "
                    f"size={len(batch)} | workers={ai_workers}"
                )
                self.logger.debug(
                    f"批次 {idx + 1} 调用 AI 生成 | words={','.join(batch_spells)}",
                    module="main",
                    batch_index=idx + 1,
                    batch_size=len(batch),
                    words=",".join(batch_spells),
                )
                start_ts = time.time()
                fut = executor.submit(self.ai_client.generate_mnemonics, batch_spells)
                in_flight[idx] = {
                    "future": fut,
                    "batch": batch,
                    "start_pos": start_pos,
                    "start_ts": start_ts,
                }
                last_submit_ts = time.time()
                return True

            with ThreadPoolExecutor(max_workers=ai_workers) as executor:
                while len(in_flight) < ai_workers and _submit_next(executor):
                    pass

                while expected_idx < next_batch_idx:
                    slot = in_flight.get(expected_idx)
                    if slot is None:
                        break

                    batch = slot["batch"]
                    start_pos = slot["start_pos"]
                    start_ts = slot["start_ts"]

                    latency = int((time.time() - start_ts) * 1000)
                    batch_spells = [item.get("voc_spelling", "") for item in batch]
                    try:
                        results, metadata = slot["future"].result()
                    except Exception as future_error:
                        self.logger.error(
                            f"批次 {expected_idx + 1} AI 执行异常",
                            module="main",
                            batch_index=expected_idx + 1,
                            latency_ms=latency,
                            batch_size=len(batch),
                            words=",".join(batch_spells),
                            error=str(future_error),
                            error_type=type(future_error).__name__,
                        )
                        results, metadata = [], {
                            "error": str(future_error),
                            "error_type": type(future_error).__name__,
                            "stage": "future",
                        }

                    if not results:
                        err_msg = (metadata or {}).get("error") or "unknown"
                        err_type = (metadata or {}).get("error_type") or "Unknown"
                        err_stage = (metadata or {}).get("stage") or "unknown"
                        self.logger.error(
                            f"批次 {expected_idx + 1} AI 处理失败",
                            module="main",
                            batch_index=expected_idx + 1,
                            latency_ms=latency,
                            batch_size=len(batch),
                            words=",".join(batch_spells),
                            error=err_msg,
                            error_type=err_type,
                            stage=err_stage,
                        )
                        # 失败时收缩批大小
                        current_batch_size = max(min_batch, current_batch_size - 1)
                    else:
                        bid = str(uuid.uuid4())
                        save_ai_batch({
                            "batch_id": bid,
                            "request_id": metadata.get("request_id"),
                            "ai_provider": AI_PROVIDER,
                            "model_name": self.ai_client.model_name,
                            "prompt_version": self.prompt_version,
                            "batch_size": len(batch),
                            "total_latency_ms": latency,
                            "total_tokens": metadata.get("total_tokens", 0),
                            "finish_reason": metadata.get("finish_reason"),
                        })
                        self._process_results(batch, results, start_pos, total_pending, bid)

                        # 自适应批大小：成功且快则增，慢则降
                        if latency <= 12000 and len(results) >= max(1, len(batch) // 2):
                            current_batch_size = min(max_safe_batch, current_batch_size + 1)
                        elif latency >= 30000:
                            current_batch_size = max(min_batch, current_batch_size - 1)

                    del in_flight[expected_idx]
                    expected_idx += 1

                    while len(in_flight) < ai_workers and _submit_next(executor):
                        pass
        finally:
            self._flush_pending_maimemo_syncs(name)

    def _process_results(self, batch_words, ai_results, current_start, total, batch_id):
        ai_map = {item["spelling"].lower(): item for item in ai_results}
        notes_to_save = []
        pending_sync_items = []
        
        # ⚠️ 不再使用跨 AI 调用的共享连接。
        # 原因：Turso/libsql 使用 Hrana 流式协议，流有服务端存活时限。
        # 在 AI API 调用期间（约 15+ 秒）持有同一流，会导致服务端回收流，
        # 后续 commit 时触发 "stream not found" 崩溃。
        # 改为让每个 DB 函数自行管理短生命周期连接，确保每次 write 都是新鲜流。
        for idx, w in enumerate(batch_words):
            num = current_start + idx + 1
            spell = w["voc_spelling"].lower()
            vid = str(w["voc_id"])
            
            if spell in ai_map:
                payload = ai_map[spell]
                original_meanings = (
                    w.get("voc_meanings")
                    or w.get("voc_meaning")
                    or w.get("meanings")
                    or w.get("meaning")
                    or w.get("original_meanings")
                )
                meta = {
                    "batch_id": batch_id,
                    "original_meanings": original_meanings,
                    "content_origin": "ai_generated",
                    "content_source_db": None,
                    "content_source_scope": None,
                    "maimemo_context": {
                        "review_count": w.get("review_count"),
                        "short_term_familiarity": w.get("short_term_familiarity")
                    }
                }
                notes_to_save.append({"voc_id": vid, "payload": payload, "metadata": meta})
                
                if DRY_RUN:
                    self._mark_processed_with_cache(vid, spell)
                else:
                    brief = clean_for_maimemo(payload.get('basic_meanings', ''))
                    pending_sync_items.append({
                        "num": num,
                        "total": total,
                        "voc_id": vid,
                        "spell": spell,
                        "brief": brief,
                        "tags": ["雅思"],
                    })
            else:
                self.logger.warning(f"{spell} 结果缺失")

        saved_ok = True
        if notes_to_save:
            from core.db_manager import save_ai_word_notes_batch
            saved_ok = save_ai_word_notes_batch(notes_to_save)

        if pending_sync_items:
            if not saved_ok:
                self.logger.warning("⚠️ 批量落库失败，已取消本批次收尾同步入队", module="main")
                return

            for item in pending_sync_items:
                self.logger.info(f"[{item['num']}/{item['total']}] ✅ {item['spell']} 已加入收尾同步队列")
                self._queue_maimemo_sync(item["voc_id"], item["spell"], item["brief"], item["tags"])

if __name__ == "__main__":
    # 解析命令行参数
    help_epilog = """
功能概览:
    MOMO Script 会从墨墨 OpenAPI 拉取任务，进行 AI 助记生成，并在结束时执行同步与收尾。

菜单入口:
    1. 今日任务     处理今日待复习单词
    2. 未来计划     处理未来 7 天待学单词
    3. 智能迭代     优化薄弱词助记（基于数据反馈）
    4. 同步&退出    保存所有数据并安全退出

关键环境变量:
    MOMO_ENV                运行环境 (development|staging|production)
    MOMO_CONFIG_FILE        日志配置文件路径 (默认: config/logging.yaml)
    MOMO_USER               当前用户 profile（默认: default）
    AI_PIPELINE_WORKERS     AI 并发工作线程数（默认: 2）
    EXIT_SYNC_TIMEOUT_S     退出同步最大等待秒数（默认: 8.0）

PowerShell 示例:
    python main.py
    python main.py --env production --log-level INFO
    python main.py --async-log --enable-stats
    $env:AI_PIPELINE_WORKERS='4'; $env:EXIT_SYNC_TIMEOUT_S='15'; python main.py
"""
    parser = argparse.ArgumentParser(
        description='墨墨背单词AI助记系统（交互式菜单入口）',
        epilog=help_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--env', '--environment',
                       choices=['development', 'staging', 'production'],
                       default=os.getenv('MOMO_ENV', 'development'),
                       help='运行环境 (默认: development)')
    parser.add_argument('--config', '--config-file',
                       default=os.getenv('MOMO_CONFIG_FILE', 'config/logging.yaml'),
                       help='配置文件路径 (默认: config/logging.yaml)')
    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='覆盖控制台日志级别')
    parser.add_argument('--async-log', action='store_true',
                       help='启用异步日志')
    parser.add_argument('--enable-stats', action='store_true',
                       help='启用日志统计')

    args = parser.parse_args()

    _disable_signal_wakeup_fd()

    # 移除可能会导致 stdin 阻塞的强制编码重配置
    manager = None
    try:
        manager = StudyFlowManager(environment=args.env, config_file=args.config)

        # 如果指定了命令行参数，覆盖配置
        if args.log_level or args.async_log or args.enable_stats:
            # 重新创建日志器以应用覆盖配置
            log_config = get_full_config(args.env, args.config)
            if args.log_level:
                log_config["console_level"] = args.log_level
            if args.async_log:
                log_config["use_async"] = True
            if args.enable_stats:
                log_config["enable_stats"] = True

            manager.logger = setup_logger(
                ACTIVE_USER,
                environment=args.env,
                config_file=args.config,
                use_async=log_config.get("use_async"),
                enable_stats=log_config.get("enable_stats")
            )

        manager.run()
    except KeyboardInterrupt:
        if manager and getattr(manager, "logger", None):
            try:
                manager.logger.info("用户手动退出", module="main")
            except Exception:
                pass
    except Exception as e:
        # 崩溃路径优先复用现有 logger，避免额外导入副作用。
        if manager and getattr(manager, "logger", None):
            try:
                manager.logger.error(f"意外崩溃: {e}", exc_info=True, module="main")
            except Exception as log_error:
                print(f"程序崩溃: {e}", file=sys.stderr)
                print(f"日志系统也出现错误: {log_error}", file=sys.stderr)
        else:
            print(f"程序崩溃: {e}", file=sys.stderr)
    finally:
        if manager:
            try:
                if hasattr(manager, "shutdown"):
                    manager.shutdown()
                if getattr(manager, "momo", None) and hasattr(manager.momo, "close"):
                    manager.momo.close()
                if getattr(manager, "ai_client", None) and hasattr(manager.ai_client, "close"):
                    manager.ai_client.close()
            except Exception as close_error:
                logger = manager.logger if getattr(manager, "logger", None) else None
                if logger:
                    logger.warning(f"退出收尾: 客户端资源释放异常: {close_error}", module="main")
        # 自动同步数据到云端
        try:
            logger = manager.logger if manager and getattr(manager, "logger", None) else None
            exit_sync_timeout_s = float(os.getenv("EXIT_SYNC_TIMEOUT_S", "8.0"))
            if manager and hasattr(manager, "_estimate_exit_sync_timeout_s"):
                adaptive_timeout_s = manager._estimate_exit_sync_timeout_s(exit_sync_timeout_s)
                if adaptive_timeout_s != exit_sync_timeout_s and logger:
                    logger.info(
                        f"退出同步超时已按近期耗时动态调整为 {adaptive_timeout_s:.1f}s（基础值 {exit_sync_timeout_s:.1f}s）",
                        module="main"
                    )
                exit_sync_timeout_s = adaptive_timeout_s
            if logger:
                logger.info("正在执行退出前自动同步...", module="main")

            deadline = time.time() + exit_sync_timeout_s
            sync_state = {"overall_status": "success"}
            status_rank = {"success": 0, "partial": 1, "failed": 2}
            task_summaries = []
            skip_explicit_sync = False

            def _merge_status(next_status: str) -> None:
                current_status = sync_state["overall_status"]
                if status_rank.get(next_status, 2) > status_rank.get(current_status, 0):
                    sync_state["overall_status"] = next_status

            def _run_exit_sync(label: str, sync_func, result_bucket: dict):
                try:
                    result_bucket["stats"] = sync_func(dry_run=False)
                except Exception as sync_error:
                    result_bucket["error"] = sync_error

            sync_jobs = [
                ("用户数据库", sync_databases),
                ("中央 Hub 数据库", sync_hub_databases),
            ]
            sync_threads = []
            sync_results = {}

            existing_post_sync_thread = getattr(manager, "_post_sync_thread", None) if manager else None
            if existing_post_sync_thread and existing_post_sync_thread.is_alive():
                remaining = max(0.1, deadline - time.time())
                if logger:
                    logger.info("检测到后台同步任务仍在执行，优先复用并等待其完成...", module="main")
                existing_post_sync_thread.join(timeout=remaining)
                if existing_post_sync_thread.is_alive():
                    _merge_status("partial")
                    task_summaries.append("后台同步任务: timeout")
                    skip_explicit_sync = True
                    if logger:
                        logger.warning(
                            f"后台同步任务等待超时（总超时 {exit_sync_timeout_s:.1f}s），跳过重复发起退出同步。",
                            module="main"
                        )
                else:
                    post_sync_result = getattr(manager, "_post_sync_result", None) if manager else None
                    if isinstance(post_sync_result, dict):
                        reused_status = str(post_sync_result.get("overall_status", "success")).lower()
                        if reused_status == "failed":
                            _merge_status("failed")
                        elif reused_status == "partial":
                            _merge_status("partial")
                        task_summaries.extend(post_sync_result.get("task_summaries", []))
                    else:
                        task_summaries.append("后台同步任务: reused-ok")
                    skip_explicit_sync = True
                    if logger:
                        logger.info("后台同步任务已完成，跳过重复发起退出同步。", module="main")

            if not skip_explicit_sync:
                for label, sync_func in sync_jobs:
                    bucket = {}
                    sync_results[label] = bucket
                    thread = threading.Thread(
                        target=_run_exit_sync,
                        args=(label, sync_func, bucket),
                        daemon=True,
                        name=f"exit-sync-{label}",
                    )
                    thread.start()
                    sync_threads.append((label, thread, bucket))

                for label, thread, bucket in sync_threads:
                    remaining = max(0.1, deadline - time.time())
                    thread.join(timeout=remaining)

                    if thread.is_alive():
                        msg = f"{label}同步超时，已跳过等待（总超时 {exit_sync_timeout_s:.1f}s）"
                        if logger:
                            logger.warning(msg, module="main")
                        _merge_status("partial")
                        task_summaries.append(f"{label}: timeout")
                        continue

                    sync_error = bucket.get("error")
                    if sync_error is not None:
                        msg = f"{label}同步失败: {sync_error}"
                        if logger:
                            logger.warning(msg, module="main")
                        _merge_status("failed")
                        task_summaries.append(f"{label}: failed")
                        continue

                    stats = bucket.get("stats") or {}
                    sync_status = str(stats.get("status", "ok")).lower()
                    if sync_status in {"error", "failed", "fail"}:
                        _merge_status("failed")
                        task_summaries.append(f"{label}: failed")
                    elif sync_status in {"timeout", "partial"}:
                        _merge_status("partial")
                        task_summaries.append(f"{label}: partial")
                    else:
                        task_summaries.append(f"{label}: ok")
                    if logger:
                        logger.info(
                            f"{label}同步完成: 上传 {stats.get('upload', 0)}, 下载 {stats.get('download', 0)}",
                            duration_ms=stats.get('duration_ms'),
                            module="main",
                        )

            if logger:
                overall_status = sync_state["overall_status"]
                if overall_status == "success":
                    logger.info("数据已自动同步到云端。", module="main")
                elif overall_status == "partial":
                    logger.warning("已触发退出同步，但存在未完成任务；下次启动将继续补偿同步。", module="main")
                else:
                    logger.warning("退出同步未完成，请稍后手动执行同步或下次启动自动补偿。", module="main")

                if task_summaries:
                    logger.info(f"退出同步摘要: {'; '.join(task_summaries)}", module="main")
        except Exception as e:
            if manager and getattr(manager, "logger", None):
                try:
                    manager.logger.warning(f"退出时自动同步失败: {e}", module="main")
                except Exception:
                    pass

        if logger:
            logger.info("程序已安全退出。", module="main")
