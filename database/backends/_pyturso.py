from __future__ import annotations

"""Pyturso sync backend implementation.

Wraps turso.sync.connect() into a TursoBackend-compliant class.
This module must NOT import from database.connection (circular-import risk).
"""

import os
import threading
import time
from typing import Any

# ── pyturso availability (集中探针) ──
from database.backends import HAS_PYTURSO

# ── helpers from database.utils (no circular import) ──
from database.utils import _debug_log

# ── V007 format migration (lazy-imported inside connect) ──


# ═══════════════════════════════════════════════════════════════
# TursoBackend implementation
# ═══════════════════════════════════════════════════════════════


class PytursoBackend:
    """TursoBackend implementation wrapping turso.sync (pyturso)."""

    name = "pyturso"

    def connect(
        self,
        db_path: str,
        url: str,
        token: str,
        *,
        do_sync: bool = False,
        do_pull: bool = True,
    ) -> Any:
        """Create a pyturso Turso Sync connection.

        与官方示例 (docs/api/turso_api.md / pyturso README) 一致的最小流程:
          1. V007 format migration (清理掉非 turso 格式的旧文件)
          2. turso.sync.connect() — pyturso 自动从远端 bootstrap, 并在 connect 内部
             建出 -info 边车 + sync 元数据。这一步对 10MB+ 的库可能耗时 60-150s
             (pyturso 内部会等服务端 long-poll 完成), 这是正常的, 不是卡死。
          3. (可选) db.pull() — 拉远端最新增量。对刚 bootstrap 的库通常是 no-op,
             因为 connect 时已经同步过了。

        关于 do_pull:
          - True (默认): 每次 connect 都额外 pull 一次。建议给写连接/单例用。
          - False: 跳过额外 pull。建议给频繁打开的读连接用 (节省一次 RPC)。
            ⚠️ 不会引起边车缺失——pyturso connect 内部自己负责建边车。

        关于 checkpoint(): 这个流程里不调用。checkpoint 是用来压缩本地 WAL 控制
        磁盘占用的, 与 sync 状态/可读性无关。WAL 压缩留给 do_sync_on() 或更上层
        显式调用决定。
        """
        if not HAS_PYTURSO:
            raise RuntimeError("pyturso is not available")

        import turso

        _debug_log(
            f"[pyturso] db_path={db_path}, url={url[:50]}...",
            module="database.backends._pyturso",
        )

        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        db_label = "Hub" if "hub" in os.path.basename(db_path).lower() else "主库"

        # ── Step 1: V007 format migration ──
        # 历史迁移代码已清理，现在直接跳过，交给 pyturso 的 bootstrap 机制自动处理
        pass

        def _is_valid_sqlite(fp: str) -> bool:
            try:
                if not os.path.exists(fp) or os.path.getsize(fp) == 0:
                    return False
                with open(fp, "rb") as f:
                    header = f.read(16)
                return bool(header and header.startswith(b"SQLite format 3"))
            except Exception:
                return False

        db_existed_before = _is_valid_sqlite(db_path)

        # ── Step 2: turso.sync.connect() — 全部由 pyturso 处理 ──
        # 对于首次 bootstrap 大库 (>10MB), pyturso 在写完数据页后还会等服务端
        # long-poll, 通常 60-150s 才返回, 这是 pyturso 当前实现的正常行为
        # (见 issue tracker 和 docs/sync/usage)。开后台线程汇报进度避免用户误以为卡死。
        _t0 = time.time()
        _connect_done = threading.Event()

        def _bootstrap_progress():
            while not _connect_done.wait(timeout=5.0):
                try:
                    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
                except OSError:
                    size = 0
                elapsed = time.time() - _t0
                operation = "连接中" if db_existed_before else "首次 bootstrap"
                extra_note = "" if db_existed_before else " (可能耗时 60-150s)"
                _debug_log(
                    f"[{db_label}] {operation}... 已 {elapsed:.0f}s,"
                    f" .db 文件 {size / 1024 / 1024:.2f} MB{extra_note}",
                    level="INFO",
                    module="database.backends._pyturso",
                )

        _progress_thread = threading.Thread(target=_bootstrap_progress, daemon=True)
        _progress_thread.start()
        try:
            db = turso.sync.connect(
                db_path,
                remote_url=url,
                auth_token=token,
            )
        finally:
            _connect_done.set()
        _elapsed = time.time() - _t0
        _debug_log(
            f"[{db_label}] turso.sync.connect 完成 (耗时 {_elapsed:.1f}s)",
            level="INFO",
            module="database.backends._pyturso",
        )

        try:
            db.execute("PRAGMA busy_timeout=30000;")
            db.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            _debug_log(
                f"pyturso PRAGMA 配置失败（可忽略）: {e}",
                level="WARNING",
                module="database.backends._pyturso",
            )

        # ── Step 3: 可选的 pull (拉增量) ──
        # 对刚 bootstrap 的库通常是 no-op (connect 已经同步过); 对已有 .db 的库
        # 用来拉远端增量。失败一律非致命——本地数据可读, 等下次 sync 再补。
        if do_pull and not do_sync:
            try:
                changed = db.pull()
                _debug_log(
                    f"[{db_label}] pull 完成 (changed={changed})",
                    level="INFO",
                    module="database.backends._pyturso",
                )
            except Exception as e:
                _debug_log(
                    f"[{db_label}] pull 失败（非致命，本地仍可用）: {e}",
                    level="WARNING",
                    module="database.backends._pyturso",
                )

        # ── Step 4: Full sync cycle if requested ──
        # 拆开 push / pull 单独计时,因为 connect(do_sync=True) 路径上
        # 整轮可能花数十秒,需要看清是 push 在清本地积压还是 pull 在拉远端。
        if do_sync:
            try:
                _t_push = time.time()
                _debug_log(
                    f"[{db_label}] push 开始...",
                    level="INFO",
                    module="database.backends._pyturso",
                )
                db.push()
                _debug_log(
                    f"[{db_label}] push 完成",
                    start_time=_t_push,
                    level="INFO",
                    module="database.backends._pyturso",
                )
                _t_pull = time.time()
                db.pull()
                _debug_log(
                    f"[{db_label}] pull 完成",
                    start_time=_t_pull,
                    level="INFO",
                    module="database.backends._pyturso",
                )
                _debug_log(
                    f"[{db_label}] 同步完成 (push→pull)",
                    level="INFO",
                    module="database.backends._pyturso",
                )
            except Exception as e:
                _debug_log(
                    f"[{db_label}] 同步失败: {e}",
                    level="WARNING",
                    module="database.backends._pyturso",
                )

        return db

    def do_push_only(self, conn: Any) -> None:
        """Push local changes to remote and checkpoint.

        Raises:
            Exception: Propagates exceptions from push or checkpoint to allow caller to detect failures.
        """
        if not hasattr(conn, "push"):
            return

        _t_push = time.time()
        conn.push()
        _debug_log(
            f"[pyturso do_push_only] push 完成",
            start_time=_t_push,
            level="INFO",
            module="database.backends._pyturso",
        )

        _t_ckpt = time.time()
        conn.checkpoint()
        _debug_log(
            f"[pyturso do_push_only] checkpoint 完成",
            start_time=_t_ckpt,
            level="INFO",
            module="database.backends._pyturso",
        )

    def do_pull_only(self, conn: Any) -> None:
        """Pull remote changes to local.

        Pull failures are logged but not propagated (local data remains usable).
        """
        if not hasattr(conn, "pull"):
            return

        try:
            _t_pull = time.time()
            conn.pull()
            _debug_log(
                f"[pyturso do_pull_only] pull 完成",
                start_time=_t_pull,
                level="INFO",
                module="database.backends._pyturso",
            )
        except Exception as e:
            _debug_log(
                f"[pyturso do_pull_only] pull 失败（非致命，本地仍可用）: {e}",
                level="WARNING",
                module="database.backends._pyturso",
            )

    def do_sync_on(self, conn: Any) -> None:
        """Trigger a full sync cycle (push → pull → checkpoint) on an existing pyturso connection.

        Raises:
            Exception: Propagates exceptions from do_push_only to allow caller to detect push failures.
        """
        # Rely on internal guards in do_push_only/do_pull_only
        self.do_push_only(conn)  # Let push exceptions propagate
        self.do_pull_only(conn)  # Pull failures are logged internally
