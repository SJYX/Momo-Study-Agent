# 混合双轨架构重构设计 (Hybrid Dual-Track Architecture)

> **Date:** 2026-05-18
> **Status:** Approved
> **Branch:** feat/web-ui

## 1. 概述

将 MOMO_Script 从 **libSQL Embedded Replica（二进制帧同步）** 迁移到 **Turso Sync（逻辑 CDC 同步）**，同时重构为混合双轨架构：User_Sync_DB（pyturso embedded replica）+ Global_Cache_DB（HTTP remote query）。核心目标：

1. **同步内核升级**：`libsql` → `pyturso`，`conn.sync()`（整帧） → `push()`/`pull()`（逻辑 CDC）
2. **架构升级**：单体 DB → 双轨（用户私有库 + 全局缓存池）+ 3 级查找流水线
3. **写入模型升级**：写入发到云端 → 本地写入 + 显式 push（离线友好）

核心底线：用户现有词汇数据零丢失、平滑过渡。

### 1.1 设计决策汇总

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 同步内核 | `pyturso` + `turso.sync`（逻辑 CDC） | 替代 `libsql` 二进制帧同步；支持本地写入 + 显式 push/pull；原生 MVCC 并发写入；**已验证 pyturso 包可用，API: `turso.sync.connect()` / `db.push()` / `db.pull()`** |
| ai_word_notes 拆分 | 整表留在 User_Sync_DB | 迁移成本最低，本地表结构不变 |
| Global_Cache_DB 连接 | HTTP Remote Query | 无本地副本，多用户共享，离线自动降级 |
| 缓存主键 | spelling + prompt_version + ai_provider 三维度 hash | 支持同一词不同 provider 的缓存共存 |
| 网络超时 | 抛出 CacheNetworkError，外层熔断 | 避免断网时连续超时雪崩 |
| 覆写保护 | ai_word_notes 新增 is_customized 列 | 用户编辑后绝对不被缓存覆盖 |
| 回写时机 | AI 生成后 fire-and-forget 异步回写 | 不阻塞主流程，其他用户立即可命中 |
| 历史种子 | 997 条 ai_generated 上传缓存池 | 新用户首次查词即命中 |
| 架构方案 | 方案 C：全新 WordLookup Pipeline | 最清晰的 3 级流程，职责单一 |
| 并发写入 | pyturso 原生 MVCC | 消除 WalConflict 防护代码，简化 connection.py；支持并发读写 |
| CDC 冲突 | Last-Write-Wins（LWW） | 本项目场景：离线编辑是最终意图；`is_customized=1` 不受影响 |
| 缓存异步回写 | 专用写入线程 + Queue | 与主循环完全隔离，HTTP 耗时不影响查词速度；背压控制防止队列无限增长 |
| LLM 失败重试 | 最多 3 次，超限标记 failed | 避免敏感词/拼写错误词无限重试 LLM |

## 2. 目标架构

### 2.1 两个数据库实体

**User_Sync_DB**（`history-{user}.db`，Turso Sync Embedded Replica）

- 同步方式：`pyturso` 逻辑 CDC 同步 — `db.push()`（本地→云端） + `db.pull()`（云端→本地）
  - 与旧版 `libsql` `conn.sync()` 的区别：传输逻辑变更（而非整页），支持本地写入，MVCC 并发
- 连接：`turso.sync.connect("app.db", remote_url=..., auth_token=...)`，替代旧版 `libsql.connect(sync_url=..., auth_token=...)`
- 写入模型：所有读写在本地完成（毫秒级），`push()` 显式推送变更到云端；`pull()` 拉取远端变更
- 并发支持：pyturso 引擎原生 MVCC，不再需要单连接守护进程 + 写队列的 WalConflict 防护
- 包含的表：
  - `processed_words` — 用户已处理词（1247 行 @ Asher）
  - `ai_word_notes` — AI 笔记（1223 行 @ Asher，**新增 `is_customized` 列**）
  - `ai_word_iterations` — 迭代历史
  - `word_progress_history` — 熟悉度追踪（1462 行 @ Asher）
  - `ai_batches` — 批次元数据（1204 行 @ Asher）
  - `system_config` / `test_run_logs`

**Global_Cache_DB**（Turso 云端，HTTP Remote Query）

- 同步方式：无本地副本，纯 HTTP SQL 请求（Turso `/v2/pipeline` API）
- 连接：新建 `GlobalCacheClient`，`requests.Session` 连接复用
- 包含的表：
  - `ai_cache` — 全局 AI 缓存池

### 2.2 3 级查找流程

```
┌──────────────────────────────────────────────────────────────┐
│                    WordLookup (core/word_lookup.py)          │
│                                                              │
│  lookup(spelling, prompt_version, ai_provider)               │
│    │                                                         │
│    ├── Level 1: User_Sync_DB (本地 ai_word_notes)           │
│    │   ├─ 命中 + is_customized → return (local_customized)  │
│    │   ├─ 命中 → return (local)                             │
│    │   └─ 未命中 → 继续                                      │
│    │                                                         │
│    ├── Level 2: Global_Cache_DB (HTTP POST /query)          │
│    │   ├─ CacheNetworkError → raise (外层熔断)               │
│    │   ├─ 命中 → 合流写入 User_Sync_DB → return (cache)     │
│    │   └─ 未命中 → 继续                                      │
│    │                                                         │
│    └── Level 3: LLM API (mimo/gemini)                       │
│        ├─ 成功 → 双向回写 → return (ai)                     │
│        │   ├── INSERT User_Sync_DB (同步)                    │
│        │   └── INSERT Global_Cache_DB (fire-and-forget 异步) │
│        └─ 失败 → raise APIError                              │
└──────────────────────────────────────────────────────────────┘
```

## 3. 模块设计

### 3.1 `core/word_lookup.py`（新建）

统一编排 3 级查找的核心模块。

```python
class LookupResult:
    note: Dict[str, Any]
    source: str  # "local" | "local_customized" | "cache" | "ai"

class WordLookup:
    def __init__(self, logger, ai_client, cache_client, db_path=None):
        self.logger = logger
        self.ai_client = ai_client          # 现有 mimo/gemini client
        self.cache_client = cache_client    # GlobalCacheClient
        self.db_path = db_path

    def lookup(self, spelling, prompt_version, ai_provider) -> LookupResult:
        """3 级查找。CacheNetworkError 和 APIError 向上抛。"""
        ...
```

**异常传播规则**：

- `CacheNetworkError`：Level 2 超时/连接失败，直接 raise，不降级到 Level 3
- `APIError`：Level 3 LLM 调用失败，直接 raise
- 外层 `study_workflow.py` 捕获后标为 pending，本轮跳过

**批量熔断机制**：

```python
network_available = True
MAX_LLM_RETRIES = 3  # 单词 LLM 失败上限

for word in batch_words:
    if not network_available:
        pending_words.append(word)
        continue
    try:
        result = word_lookup.lookup(word.spelling, prompt_version, ai_provider)
    except CacheNetworkError:
        pending_words.append(word)
        network_available = False  # 熔断：后续词不再发起网络请求
        continue
    except APIError:
        word.llm_fail_count = getattr(word, "llm_fail_count", 0) + 1
        if word.llm_fail_count >= MAX_LLM_RETRIES:
            word.status = "failed"  # 超过上限，标记为永久失败，不再重试
        else:
            pending_words.append(word)  # 未到上限，下次重试
        continue
```

**重试上限机制**：避免 Level 3 反复失败的词（敏感词、拼写错误等）无限重试 LLM。

- 每个词维护 `llm_fail_count` 计数器
- 达到 `MAX_LLM_RETRIES`（默认 3）后标记为 `failed`，不再进入 pending
- 失败词会在日志中告警，用户可手动干预

### 3.2 `database/cache_client.py`（新建）

Global_Cache_DB 的 HTTP 客户端。使用 Turso `/v2/pipeline` endpoint 执行远程 SQL（已确认可用）。

> **连接方式**：`POST {base_url}/v2/pipeline`，Bearer token 认证，通过 SQL pipeline 协议执行查询。
> 与 User_Sync_DB 的 pyturso embedded replica 不同，Global_Cache_DB 无本地副本，纯 HTTP SQL。

```python
class CacheNetworkError(Exception):
    """缓存 HTTP 查询超时/连接失败。"""

class GlobalCacheClient:
    def __init__(self, url: str, token: str, timeout: float = 3.0):
        self.endpoint = url.rstrip("/") + "/v2/pipeline"  # Turso SQL pipeline endpoint（已验证）
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def cache_key(spelling, prompt_version, ai_provider) -> str:
        raw = f"{spelling}:{prompt_version}:{ai_provider}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def find(self, spelling, prompt_version, ai_provider) -> Optional[Dict]:
        """查询缓存。所有 requests 异常转为 CacheNetworkError。"""
        ...

    def write(self, note, prompt_version, ai_provider):
        """写入缓存（fire-and-forget）。异常仅日志，不抛出。"""
        ...
```

**`/v2/pipeline` 请求格式**（Turso SQL Pipeline 协议）：

```python
# 请求体
payload = {
    "requests": [
        {
            "type": "execute",
            "stmt": {
                "sql": "INSERT OR IGNORE INTO ai_cache (cache_key, ...) VALUES (?, ...)",
                "args": [{"type": "text", "value": cache_key}, ...]
            }
        }
    ]
}
resp = self.session.post(self.endpoint, json=payload, headers={
    "Authorization": f"Bearer {self.token}"
}, timeout=self.timeout)

# 响应体 — HTTP 200 不等于 SQL 成功，需检查内部 type 字段
# resp.json() = {"results": [{"type": "ok", "response": {"result": {...}}}]}
# 或 {"results": [{"type": "error", "error": {"message": "..."}}]}
for result in resp.json().get("results", []):
    if result.get("type") == "error":
        raise RuntimeError(result["error"]["message"])
```

**专用写入线程设计**（fire-and-forget 实现）：

```python
# database/cache_client.py
import threading
import queue
from queue import Queue

class CacheWriteWorker:
    """专用后台线程，消费写入队列，异步回写 Global_Cache_DB。"""

    def __init__(self, client: GlobalCacheClient):
        self.client = client
        self._queue: Queue = Queue(maxsize=256)
        self._thread = threading.Thread(target=self._run, daemon=True, name="cache-writer")
        self._thread.start()

    def submit(self, note, prompt_version, ai_provider):
        """非阻塞投递。队列满时静默丢弃（缓存写入是 best-effort）。"""
        try:
            self._queue.put_nowait((note, prompt_version, ai_provider))
        except queue.Full:
            self.client.logger.warning("Cache write queue full, dropping background write.")
        except Exception as e:
            self.client.logger.error(f"Unexpected error queuing cache write: {e}")

    def _run(self):
        while True:
            note, pv, provider = self._queue.get()
            try:
                self.client.write(note, pv, provider)
            except Exception:
                pass  # write() 内部已 log
            finally:
                self._queue.task_done()
```

- `daemon=True`：进程退出时自动清理，无需显式 join
- `Queue(maxsize=256)`：背压控制，防止离线时队列无限增长
- `put_nowait` + 静默丢弃：缓存写入是 best-effort，不阻塞主流程
- 与主循环（同步）完全隔离，HTTP 耗时不影响查词速度

**关键设计**：

- `/v2/pipeline` 是 Turso 的 SQL 执行 endpoint（非 Management API），需按 pipeline 协议构造 JSON
- HTTP 200 ≠ SQL 成功，必须检查响应内 `results[].type` 字段
- `find()` 使用 `requests.RequestException` 作为基础拦截网（覆盖 Timeout、ConnectionError、HTTPError）
- `write()` 由 `CacheWriteWorker` 专用线程消费，与主流程完全隔离
- `INSERT OR IGNORE` 防止并发写入的主键冲突
- `timeout=3.0` 秒，可配置

### 3.3 与现有模块的职责划分

| 模块 | 职责 | 是否改动 |
|------|------|---------|
| `WordLookup` | 3 级查找编排 | 新建 |
| `WordService` | enrich / partition / mark_completed | 不变 |
| `study_workflow.py` | 批量处理 + 异常捕获 + pending | 修改 |
| `community_lookup.py` | 本地历史库查找（保留作为 WordLookup 内部的 Level 1 子逻辑） | 不变 |
| `notes_repo.py` | CRUD + sync 标记 | 小改（`update_memory_aid` 加 `is_customized=1`） |
| `database/connection.py` | 连接管理 + 同步 | **大改** — 从 libsql Embedded Replica 迁移到 pyturso；消除 WalConflict 防护代码（单连接守护、写队列、GC hack 等）；使用 `turso.sync.connect()` + `push()`/`pull()` 替代 `libsql.connect()` + `conn.sync()` |
| `database/sync_service.py` | 同步管线 | **中改** — `conn.sync()` 调用改为 `db.push()`/`db.pull()`；软超时机制可能需要调整 |
| `database/execution_engine.py` | 写队列 + 后台同步守护 | **简化** — pyturso 原生 MVCC 可能消除写队列需求；`_sync_daemon` 改为 `push()`/`pull()` 调度 |

## 4. Schema 变更

### 4.1 User_Sync_DB：is_customized 列（V005，已执行）

迁移脚本：`database/migrations/V005_is_customized.py`（已执行，无需再操作）

```sql
ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0;
```

- 幂等执行（迁移框架自动检测列是否已存在）
- 所有现有记录 DEFAULT 0（纯 AI 生成，未被用户编辑）
- 用户通过 Web UI 编辑 memory_aid 时，`UPDATE ai_word_notes SET memory_aid=?, is_customized=1 WHERE voc_id=?`

### 4.2 Global_Cache_DB：新建 ai_cache 表

首次启动时通过 `GlobalCacheClient` 的初始化方法执行：

```sql
CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY,
    spelling TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    ai_provider TEXT NOT NULL,
    ai_output_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    usage_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_spelling ON ai_cache (spelling);
```

`cache_key` = `sha256(f"{spelling}:{prompt_version}:{ai_provider}")[:16]`

### 4.3 种子数据回填

迁移脚本：`database/migrations/V006_seed_global_cache.py`

**前置条件**：环境已加载 Turso 云端凭据（`TURSO_CACHE_DB_URL` + `TURSO_CACHE_AUTH_TOKEN`）

**数据来源**：Asher 的 `ai_word_notes` 表中 `content_origin = 'ai_generated'` 的 997 条记录。

**版本身份赋值**：

对于能通过 `batch_id` JOIN `ai_batches` 获取真实 `ai_provider` / `prompt_version` 的记录，使用真实值。对于 JOIN 不到的，fallback 到：

```python
DEFAULT_PROMPT_VERSION = "v1_legacy_structured"
DEFAULT_AI_PROVIDER = "mimo"  # 当前 AI_PROVIDER 默认值
```

**提取字段**：从 ai_word_notes 中提取 AI 输出字段（basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text），打包为 JSON。

**写入方式**：批量 INSERT OR IGNORE 到 Global_Cache_DB。

## 5. 配置变更

`config.py` 新增：

```python
# Global Cache DB (云端 AI 缓存池)
TURSO_CACHE_DB_URL = os.getenv("TURSO_CACHE_DB_URL")
TURSO_CACHE_AUTH_TOKEN = os.getenv("TURSO_CACHE_AUTH_TOKEN")
CACHE_TIMEOUT_S = float(os.getenv("CACHE_TIMEOUT_S", "3.0"))
```

## 6. 改动文件清单

| 文件 | 改动类型 | 风险 | 说明 |
|------|---------|------|------|
| `core/word_lookup.py` | 新建 | 低 | 3 级查找编排 |
| `database/cache_client.py` | 新建 | 低 | HTTP 客户端（Global_Cache_DB） |
| `database/migrations/V006_seed_global_cache.py` | 新建 | 低 | 一次性回填 |
| `database/migrations/V007_migrate_db_format.py` | 新建 | 中 | libSQL → pyturso 格式迁移 |
| `core/study_workflow.py` | 修改 | 中 | 主流程循环 + pending + 熔断 |
| `database/notes_repo.py` | 修改 | 低 | `update_memory_aid` 加 `is_customized=1` |
| `config.py` | 修改 | 低 | 新增缓存配置项 |
| `core/ui_manager.py` | 修改 | 低 | 显示 source 标签 |
| **`database/connection.py`** | **重写** | **高** | **从 `libsql.connect(sync_url=...)` 迁移到 `turso.sync.connect()`；消除 WalConflict 防护（单连接守护、GC hack、写队列）；pyturso 原生 MVCC 并发** |
| **`database/sync_service.py`** | **修改** | **中** | **`conn.sync()` → `db.push()`/`db.pull()`** |
| **`database/execution_engine.py`** | **简化** | **中** | **写队列可能不再需要；`_sync_daemon` 改为 push/pull 调度** |
| **`requirements.txt`** | **修改** | **低** | **添加 `pyturso`；保留 `libsql` 宽限期 1 个版本周期** |

## 7. 数据安全保证（7 道防线）

### 7.1 数据热备份（高风险迁移前通用策略）

任何高风险迁移执行前，自动创建预迁移快照（V005 已执行，本节描述通用模式，适用于 V006/V007 及未来迁移）：

```python
# database/migrations/runner.py — 通用快照函数
import os, time

def _snapshot_before_migration(conn, migration_name: str) -> str:
    """使用 SQLite 原生 VACUUM INTO 创建在线快照。

    VACUUM INTO 在运行时自动处理 WAL/SHM 合流，产出一致的物理快照，
    不锁表、不影响正在运行的读写操作。
    """
    db_dir = os.path.dirname(os.path.abspath(conn.execute("PRAGMA database_list").fetchone()[2]))
    backup_dir = os.path.join(db_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"history_pre_{migration_name}_{ts}.db")
    conn.execute(f"VACUUM INTO '{backup_path}'")
    return backup_path
```

使用 `VACUUM INTO`（SQLite 3.27+）而非 `shutil.copy2`，保证 WAL 未提交事务也被正确合流。

### 7.2 Schema 无痛升级

- V005 已执行：`ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0`，无问题
- SQLite ADD COLUMN + DEFAULT 是原子操作，不锁表、不重写数据页
- 现有 1223 条记录自动获得 `is_customized=0`，无需手动回填
- 迁移框架（`database/migrations/runner.py`）在事务内执行，失败自动 rollback
- 未来迁移（V006/V007）同理：幂等 + 事务保护

### 7.3 影子测试 / 沙箱验证

- `GLOBAL_CACHE_ENABLED=false`（默认值）：新代码路径完全不执行
- 老逻辑（`community_lookup` + AI 直连）100% 保留，行为与重构前完全一致
- 可在不影响日常使用的前提下开发、编译、部署新模块

### 7.4 一键热切换

- `.env` 中改 `GLOBAL_CACHE_ENABLED=true/false`
- `core/feature_flags.py::is_enabled()` 在每个 batch 处理时检查
- **无需重启**：下次 batch 自动切换到新/老逻辑
- 支持部分回滚：打开开关 → 发现问题 → 关闭开关 → 恢复老逻辑

### 7.5 数据层回滚

| 操作 | 回滚方式 |
|------|---------|
| V005: is_customized ADD COLUMN | 已执行，无需回滚（ALTER ADD COLUMN 幂等，重复执行无害） |
| V006: 种子数据 INSERT INTO ai_cache | `DELETE FROM ai_cache WHERE cache_key LIKE '...'`（按 seed 标记删除） |
| V007: .db 格式迁移 | 从 `.pre_pyturso.bak` 备份恢复原 `.db` 文件 |
| Level 2 合流写入 | 从 §7.1 通用快照恢复 `.db` 文件 |
| fire-and-forget 缓存 | `DELETE FROM ai_cache`（Global_Cache_DB 是纯缓存，清空不影响用户数据。SQLite 无 TRUNCATE 关键字，DELETE 不带 WHERE 时自动触发 Truncate 优化） |

### 7.6 代码层回滚

- `git revert` 回退到重构前代码
- 新建文件（`word_lookup.py`、`cache_client.py`）直接删除，无副作用
- 修改文件（`study_workflow.py`、`notes_repo.py`）通过 revert 恢复原状

### 7.7 安全清单

| 写操作 | 目标库 | 保护措施 |
| ------ | ------ | ------- |
| V002: ADD COLUMN | User_Sync_DB | 预快照 + 原子 DDL |
| V003: INSERT INTO ai_cache | Global_Cache_DB | 全新库，零风险 |
| `_upsert_local()` 缓存合流 | User_Sync_DB | 参数化 SQL + is_customized 保护 |
| `UPDATE is_customized=1` | User_Sync_DB | 参数化 SQL |
| fire-and-forget 缓存回写 | Global_Cache_DB | 异步 + 异常吞掉，不影响主库 |
| pyturso 本地写入 | User_Sync_DB | 原生 MVCC 事务保护；`push()` 失败不回滚本地写（待确认冲突解决策略） |

**铁律**：全程零 DROP TABLE / DROP COLUMN / DELETE FROM User_Sync_DB（SQL 级操作）。
V007 格式迁移中的 `os.remove(db_path)` 是文件级替换（非 SQL DDL），始终在有 `.bak` 备份的前提下执行，不违反本铁律。

> **注意**：pyturso 迁移后，旧版 libSQL 的 WalConflict 防护铁律（单连接、GC hack、cursor discipline）不再适用。Turso Database 引擎使用 MVCC，支持并发读写。但需要验证 `push()` 的冲突解决策略（§8 离线场景更新见下）。

## 8. 离线 / 异常场景矩阵

### 8.1 3 级查找场景

| 场景 | Level 1 | Level 2 | Level 3 | 行为 |
|------|---------|---------|---------|------|
| 正常在线，本地有 | 命中 | 跳过 | 跳过 | 返回 local |
| 正常在线，本地无，缓存有 | miss | 命中 | 跳过 | 合流返回 cache |
| 正常在线，全 miss | miss | miss | 调用 | AI 生成，双写返回 |
| 断网，本地有 | 命中 | 跳过 | 跳过 | 返回 local |
| 断网，本地无 | miss | raise | 不可达 | CacheNetworkError → pending |
| 缓存超时，本地无 | miss | raise | 不可达 | CacheNetworkError → pending |
| 缓存超时，本地有非 custom | 命中 | 跳过 | 跳过 | 返回 local |
| 用户改过 memory_aid | 命中+custom | 跳过 | 跳过 | 返回 local_customized |
| 缓存命中但本地有 custom | 命中+custom | 跳过 | 跳过 | 返回 local_customized |
| LLM 失败 | miss | miss | raise | APIError → pending |
| 缓存写入失败 | — | — | 异步 | 日志告警，不影响返回 |

### 8.2 pyturso 同步场景（Logical Sync 迁移后）

| 场景 | 旧行为（libsql） | 新行为（pyturso） | 备注 |
|------|----------------|-----------------|------|
| 在线写入 | 写入发到云端 primary，再 reflect 回本地 | 本地写入 → `push()` 推送到云端 | 写入更快（本地毫秒级） |
| 离线写入 | 不支持（readYourWrites=true 时阻塞） | 支持 — 本地写入，`push()` 延迟到上线后 | 新能力 |
| push 冲突 | N/A | **Last-Write-Wins（LWW）**：时间戳最新的写入胜出 | 本项目可接受：离线期间用户编辑的 ai_word_notes 是最终意图，远端修改（来自另一设备）被覆盖是预期行为。`is_customized=1` 的记录不受影响（Level 1 优先返回 local_customized，不会走 cache 合流） |
| 初始同步 | `conn.sync()` 整库拉取 | `pull()` 支持 lazy load — 按需拉取页面 | 启动更快 |
| 后台同步 | `_sync_daemon` 每 2s 检查 → `conn.sync()` | `push()`/`pull()` 间隔调度 | 需要重新设计调度策略 |

## 9. 增量开发策略

### 9.1 Feature Flag 控制

复用现有 Phase 6.1 Kill Switch 框架（`core/feature_flags.py`）。

**新增 flag**：`GLOBAL_CACHE_ENABLED`

- 注册到 `_KNOWN_FLAGS` 集合
- 添加到 `core/settings.py` 的 Settings 模型
- `.env` 中默认 `GLOBAL_CACHE_ENABLED=false`（安全默认值）
- 为 `true` 时走 `WordLookup` 3 级查找，为 `false` 时走现有老逻辑

```python
# core/feature_flags.py — _KNOWN_FLAGS 新增
"GLOBAL_CACHE_ENABLED",
```

```python
# core/settings.py — Settings 模型新增
GLOBAL_CACHE_ENABLED: bool = False
```

### 9.2 开发阶段保证日常可用

| 阶段 | 做什么 | 系统是否可用 | Flag 状态 |
| ---- | ------ | ----------- | --------- |
| P0 | 新建 `database/cache_client.py` + 单测 | 是（不接入主流程） | false |
| P1 | 新建 `core/word_lookup.py` + 单测 | 是（不接入主流程） | false |
| P2 | `V005_is_customized.py` 已执行（跳过） | — | — |
| P3 | 修改 `study_workflow.py` 加 flag 分支 | 是（flag=false 走老逻辑） | false |
| P4 | 修改 `notes_repo.py` 加 `is_customized=1` | 是（不影响读取） | false |
| P4.5 | Turso 建库 + 种子数据回填 `V006_seed_global_cache.py` | 是 | false |
| P5 | 端到端测试：设 flag=true，验证 L1/L2/L3 全链路 | 是（可随时关回） | true/false 切换 |
| **P6** | **pyturso 迁移（详见 §10）：`.db` 格式迁移 → `libsql` → `turso.sync`；connection.py 重写；消除 WalConflict 防护；同步管线改为 push/pull** | **需要充分回归测试** | **独立 feature branch** |
| P7 | 清理：移除老逻辑分支（可选，最后一个 PR） | 是 | 移除 flag |

> **P6 是高风险阶段**：`connection.py` 重写影响所有数据库操作。建议在 P0-P5（双轨架构）稳定后，作为独立 feature branch 合并，充分回归测试后上线。

**核心原则**：每个阶段完成后 `main.py` 和 Web 都能正常启动。Flag=false 时行为与重构前 100% 一致。

### 9.3 Flag 分支代码示例

```python
# core/study_workflow.py
from core.feature_flags import is_enabled

def process_batch(self, batch_words, ...):
    if is_enabled("GLOBAL_CACHE_ENABLED"):
        return self._process_batch_with_lookup(batch_words, ...)
    else:
        return self._process_batch_legacy(batch_words, ...)  # 现有逻辑不变
```

### 9.4 pyturso 迁移代码示例（P6 阶段）

```python
# database/connection.py — 迁移后
import turso.sync

def _connect_turso_sync(db_path, remote_url, auth_token):
    """替代 _connect_embedded_replica()"""
    db = turso.sync.connect(
        db_path,
        remote_url=remote_url,
        auth_token=auth_token,
    )
    # 不再需要: _check_same_thread, WalConflict 防护, GC hack
    # pyturso 原生 MVCC 支持并发读写
    return db

# 同步调用 — 替代 conn.sync()
db.push()  # 本地 → 云端
db.pull()  # 云端 → 本地
```

## 10. pyturso 迁移详细方案（P6 阶段）

> P6 的核心目标：将 User_Sync_DB 从 libSQL Embedded Replica 迁移到 pyturso Turso Sync。
> 双轨架构（P0-P5）应先稳定，P6 作为独立 feature branch 合并。

### 10.1 pyturso SDK 确认信息

- **包名**：`pyturso`
- **核心 API**（已验证可用）：
  - `import turso.sync`
  - `db = turso.sync.connect(db_path, remote_url=..., auth_token=...)` — 替代 `libsql.connect(sync_url=..., auth_token=...)`
  - `db.push()` — 本地变更推送到云端
  - `db.pull()` — 云端变更拉取到本地
  - `db.stats()` — 同步状态观察
  - `db.checkpoint()` — 检查点控制
- **安装**：`pip install pyturso` 或 `uv add pyturso`
- **SQLite3 兼容**：pyturso 声称 `sqlite3` 接口兼容

### 10.2 待验证的兼容性点

pyturso 声称 `sqlite3` 接口兼容，但以下点需要在 P6 早期验证：

| 验证项 | 影响 | 验证方式 |
| ------ | ------ | ------- |
| `row_factory` 行为 | AI_CONTEXT §3.1 禁用 `row_factory` | 连接后执行 SELECT，检查返回类型 |
| `PRAGMA` 语法 | `busy_timeout`, `synchronous=NORMAL`, `wal_checkpoint(TRUNCATE)` | 逐条执行现有 PRAGMA |
| `with_read_session` 装饰器 | 所有只读操作的并发安全 | 在 pyturso connection 上测试装饰器 |
| `VACUUM INTO` 支持 | §7.1 预迁移快照 | 执行 VACUUM INTO 测试 |
| 加密支持 | 当前 libsql 支持 `encryption_key` 参数 | 检查 pyturso connect 是否接受加密参数 |

> **建议**：P6 启动时先写一个小的验证脚本（`scripts/validate_pyturso_compat.py`），逐项打勾后才开始正式迁移。

### 10.3 .db 文件格式迁移（P6 前置步骤）

现有用户的 `.db` 文件是 libSQL 格式的 Embedded Replica。需要确认 pyturso（Turso Sync）能否直接打开这些文件。

**迁移策略**（三步走）：

#### Step 1 — 格式探测

```python
# database/migrations/V007_migrate_db_format.py
import turso.sync

def _detect_format(db_path: str) -> str:
    """探测 .db 文件是否兼容 pyturso。
    尝试用 turso.sync.connect 打开，成功则返回 "turso_sync"，
    失败则判定为 "libsql_embedded_replica"。
    """
    try:
        db = turso.sync.connect(db_path)
        db.close()
        return "turso_sync"
    except Exception:
        return "libsql_embedded_replica"
```

#### Step 2 — 格式转换（如果 pyturso 无法直接打开 libSQL 格式）

方案 A：**导出-导入法**（推荐，最安全）

```python
def _migrate_libsql_to_turso(db_path: str) -> str:
    """将 libSQL 格式 .db 转换为 pyturso 兼容格式。

    1. 用 libsql 打开旧库（只读），导出所有表结构 + 数据
    2. 用 pyturso 创建新库
    3. 在新库中重建表结构 + 导入数据
    4. 原文件重命名为 .db.bak，新文件替换
    """
    import shutil, sqlite3

    # 1. 备份
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)

    # 2. 用标准 sqlite3 导出（libSQL 兼容 SQLite3 读取）
    #    过滤 SQLite 内部表（sqlite_sequence, _litestream_seq 等），避免污染新库
    INTERNAL_PREFIXES = ("sqlite_sequence", "_litestream_", "sqlite_")
    conn_old = sqlite3.connect(db_path)
    dump_path = db_path + ".dump.sql"
    with open(dump_path, "w") as f:
        for line in conn_old.iterdump():
            # 跳过内部表的 CREATE/INSERT/DELETE 语句
            if any(f'"{p}"' in line or f" {p} " in line for p in INTERNAL_PREFIXES):
                continue
            f.write(line + "\n")
    conn_old.close()
    del conn_old  # 显式释放，防止 Windows 下 SQLite 文件句柄延迟释放

    # 3. 用 pyturso 创建新库并导入
    import time as _time
    for _attempt in range(3):
        try:
            os.remove(db_path)
            break
        except PermissionError:
            if _attempt == 2:
                raise
            _time.sleep(0.5)  # Windows 句柄释放重试
    db_new = turso.sync.connect(db_path)
    db_new.execute("PRAGMA foreign_keys=OFF;")  # 临时关闭外键，避免子表先于父表导入
    with open(dump_path, "r") as f:
        db_new.executescript(f.read())
    db_new.execute("PRAGMA foreign_keys=ON;")
    db_new.close()

    # 4. 清理临时文件
    os.remove(dump_path)
    return backup_path
```

方案 B：**原地升级**（如果 pyturso 支持直接打开 libSQL 格式）

```python
def _migrate_in_place(db_path: str) -> str:
    """如果 pyturso 能直接打开 libSQL 文件，只需执行一次 push/pull
    即可将其注册为 Turso Sync 副本。"""
    db = turso.sync.connect(db_path, remote_url=REMOTE_URL, auth_token=TOKEN)
    db.push()  # 将本地数据推送到云端，建立同步关系
    db.close()
```

#### Step 3 — 迁移确认

迁移后验证：

- 行数一致性：`SELECT COUNT(*) FROM each_table` 与迁移前对比
- Schema 一致性：`PRAGMA table_info()` 逐表对比
- WAL 状态：确认迁移后无残留 WAL/SHM 文件

#### 决策树

```text
能用 pyturso 直接打开现有 .db？
├─ 是 → 方案 B（原地升级，执行 push 建立同步关系）
└─ 否 → 方案 A（导出-导入法，最安全）
```

> **安全保证**：方案 A 始终保留 `.pre_pyturso.bak` 备份，方案 B 在 push 前保留 VACUUM INTO 快照。
> 两种方案的备份文件在验证通过后手动清理。

### 10.4 P6 迁移实施步骤

完整的 P6 迁移流程（作为独立 feature branch）：

```text
P6.0  写兼容性验证脚本 → 逐项确认（§10.2 表格）
P6.1  .db 格式迁移（§10.3 决策树选择方案 A 或 B）
P6.2  database/connection.py 重写：
      - _connect_embedded_replica() → _connect_turso_sync()
      - import libsql → import turso.sync
      - 删除 WalConflict 防护代码（单连接守护、GC hack、写队列）
P6.3  database/sync_service.py 修改：
      - conn.sync() → db.push() / db.pull()
      - 软超时机制调整
P6.4  database/execution_engine.py 简化：
      - 写队列移除或降级为可选
      - _sync_daemon 改为 push/pull 调度
      - 每次 pull() 后调用 db.checkpoint() 合流 WAL
        （无新增 WAL 时空 checkpoint 开销可忽略，无需额外定时器）
P6.5  requirements.txt 更新：
      - 添加 pyturso
      - 保留 libsql-experimental（宽限期：P6 合并后保留 1 个版本周期，
        确认 pyturso 稳定后再移除，保留包级回退能力）
P6.6  全量回归测试：
      - 所有现有测试通过
      - 手动验证：CLI 启动、Web 启动、离线写入、push/pull 同步
      - 验证 MVCC 并发读写
P6.7  合并到 main
```

### 10.5 与 libsql 的 API 差异

| 特性 | libsql (旧) | pyturso/turso.sync (新) | 需要处理 |
| ------ | ----------- | ---------------------- | ------- |
| 连接方式 | `libsql.connect(sync_url=..., auth_token=...)` | `turso.sync.connect(path, remote_url=..., auth_token=...)` | 重写连接函数 |
| 同步方式 | `conn.sync()`（整帧二进制） | `db.push()` / `db.pull()`（逻辑 CDC） | 重写同步调用 |
| 并发模型 | 单连接守护 + 写队列（WalConflict 防护） | 原生 MVCC，支持并发读写 | 删除 WalConflict 代码 |
| 离线写入 | readYourWrites=true 时阻塞 | 原生支持，push 延迟到上线 | 新能力 |
| 加密 | `encryption_key` 参数 | 待验证（§10.2） | 验证后决定 |
| row_factory | 支持但 AI_CONTEXT 禁用 | 待验证（§10.2） | 验证后决定 |

## 11. Turso Global_Cache_DB 建库指南

### 11.1 使用 Turso CLI 创建数据库

```bash
# 1. 安装 Turso CLI（如未安装）
# Windows: winget install tursodatabase.turso-cli
# 或: iwr https://get.tur.so/install.ps1 -useb | iex

# 2. 登录
turso auth login

# 3. 创建缓存数据库
turso db create history-asher-cache --group default

# 4. 获取连接信息
turso db show history-asher-cache --url
# 输出类似: libsql://history-asher-cache-ashershi.turso.io

# 5. 获取 auth token
turso db tokens create history-asher-cache
# 输出一个 JWT token

# 6. 在 .env 中配置
# TURSO_CACHE_DB_URL=libsql://history-asher-cache-ashershi.turso.io
# TURSO_CACHE_AUTH_TOKEN=eyJhbGciOi...
# GLOBAL_CACHE_ENABLED=false
```

### 11.2 使用 Turso Management API（可选脚本）

如果已配置 `TURSO_MGMT_TOKEN` 和 `TURSO_ORG_SLUG`（项目已有），可自动化建库：

```python
# scripts/create_cache_db.py
import os, requests

org = os.getenv("TURSO_ORG_SLUG")
token = os.getenv("TURSO_MGMT_TOKEN")
resp = requests.post(
    f"https://api.tur.so/v1/organizations/{org}/databases",
    headers={"Authorization": f"Bearer {token}"},
    json={"name": "history-asher-cache", "group": "default"},
    timeout=30,
)
print(resp.json())
```
