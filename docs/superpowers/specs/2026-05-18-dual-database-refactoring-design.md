# 混合双轨架构重构设计 (Hybrid Dual-Track Architecture)

> **Date:** 2026-05-18
> **Status:** Approved
> **Branch:** feat/web-ui

## 1. 概述

将 MOMO_Script 的单体数据库架构重构为"混合双轨架构"，分离用户私有同步库（User_Sync_DB）和全局 AI 缓存池（Global_Cache_DB）。核心底线：用户现有词汇数据零丢失、平滑过渡。

### 1.1 设计决策汇总

| 决策点 | 选择 | 理由 |
|--------|------|------|
| ai_word_notes 拆分 | 整表留在 User_Sync_DB | 迁移成本最低，本地表结构不变 |
| Global_Cache_DB 连接 | HTTP Remote Query | 无本地副本，多用户共享，离线自动降级 |
| 缓存主键 | spelling + prompt_version + ai_provider 三维度 hash | 支持同一词不同 provider 的缓存共存 |
| 网络超时 | 抛出 CacheNetworkError，外层熔断 | 避免断网时连续超时雪崩 |
| 覆写保护 | ai_word_notes 新增 is_customized 列 | 用户编辑后绝对不被缓存覆盖 |
| 回写时机 | AI 生成后 fire-and-forget 异步回写 | 不阻塞主流程，其他用户立即可命中 |
| 历史种子 | 997 条 ai_generated 上传缓存池 | 新用户首次查词即命中 |
| 架构方案 | 方案 C：全新 WordLookup Pipeline | 最清晰的 3 级流程，职责单一 |

## 2. 目标架构

### 2.1 两个数据库实体

**User_Sync_DB**（`history-{user}.db`，Embedded Replica）

- 同步方式：libsql `conn.sync()` 双向帧同步
- 连接：现有 Embedded Replica 单例模式不变
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
        pending_words.append(word)
        continue
```

### 3.2 `database/cache_client.py`（新建）

Global_Cache_DB 的 HTTP 客户端。

```python
class CacheNetworkError(Exception):
    """缓存 HTTP 查询超时/连接失败。"""

class GlobalCacheClient:
    def __init__(self, url: str, token: str, timeout: float = 3.0):
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
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

**关键设计**：

- `find()` 使用 `requests.RequestException` 作为基础拦截网（覆盖 Timeout、ConnectionError、HTTPError）
- `write()` 内部 log + swallow，fire-and-forget 模式
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

## 4. Schema 变更

### 4.1 User_Sync_DB：新增 is_customized 列

迁移脚本：`database/migrations/V002_add_is_customized.py`

```sql
ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0;
```

- 幂等执行（IF NOT EXISTS 由迁移框架保证）
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

迁移脚本：`database/migrations/V003_seed_global_cache.py`

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
| `database/cache_client.py` | 新建 | 低 | HTTP 客户端 |
| `database/migrations/V002_add_is_customized.py` | 新建 | 低 | 幂等 ALTER |
| `database/migrations/V003_seed_global_cache.py` | 新建 | 低 | 一次性回填 |
| `core/study_workflow.py` | 修改 | 中 | 主流程循环 + pending + 熔断 |
| `database/notes_repo.py` | 修改 | 低 | `update_memory_aid` 加 `is_customized=1` |
| `config.py` | 修改 | 低 | 新增缓存配置项 |
| `core/ui_manager.py` | 修改 | 低 | 显示 source 标签 |

## 7. 数据安全保证（6 道防线）

### 7.1 数据热备份

V002 迁移执行前，自动创建预迁移快照：

```python
# database/migrations/V002_add_is_customized.py
import shutil, os, time

_PRE_MIGRATION_MARKER = "pre_V002_snapshot"

def _snapshot_before_migration(db_path: str) -> str:
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"{os.path.basename(db_path)}_pre_V002_{ts}.db")
    if not os.path.exists(dst):
        shutil.copy2(db_path, dst)
    return dst
```

同时备份 `.db-wal` 和 `.db-shm`（如有）。

### 7.2 Schema 无痛升级

- `ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0`
- SQLite ADD COLUMN + DEFAULT 是原子操作，不锁表、不重写数据页
- 现有 1223 条记录自动获得 `is_customized=0`，无需手动回填
- 迁移框架（`database/migrations/runner.py`）在事务内执行，失败自动 rollback

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
| V002 ADD COLUMN | `UPDATE ai_word_notes SET is_customized=0`（V002 downgrade 函数） |
| V003 种子数据 | `DELETE FROM ai_cache WHERE cache_key LIKE '...'`（按 seed 标记删除） |
| Level 2 合流写入 | 从预迁移快照恢复 `.db` 文件 |
| fire-and-forget 缓存 | `TRUNCATE TABLE ai_cache`（Global_Cache_DB 是纯缓存，清空不影响用户数据） |

### 7.6 代码层回滚

- `git revert` 回退到重构前代码
- 新建文件（`word_lookup.py`、`cache_client.py`）直接删除，无副作用
- 修改文件（`study_workflow.py`、`notes_repo.py`）通过 revert 恢复原状

### 7.7 安全清单

| 写操作 | 目标库 | 保护措施 |
| ------ | ------ | ------- |
| V002: ADD COLUMN | User_Sync_DB | 预快照 + 原子 DDL + 写队列 |
| V003: INSERT INTO ai_cache | Global_Cache_DB | 全新库，零风险 |
| `_upsert_local()` 缓存合流 | User_Sync_DB | 参数化 SQL + 写队列 + is_customized 保护 |
| `UPDATE is_customized=1` | User_Sync_DB | 参数化 SQL + 写队列 |
| fire-and-forget 缓存回写 | Global_Cache_DB | 异步 + 异常吞掉，不影响主库 |

**铁律**：全程零 DROP TABLE / DROP COLUMN / DELETE FROM User_Sync_DB。

## 8. 离线 / 异常场景矩阵

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
| P2 | `database/migrations/V002_add_is_customized.py` | 是（幂等 ALTER） | false |
| P3 | 修改 `study_workflow.py` 加 flag 分支 | 是（flag=false 走老逻辑） | false |
| P4 | 修改 `notes_repo.py` 加 `is_customized=1` | 是（不影响读取） | false |
| P4.5 | Turso 建库 + 种子数据回填 `V003_seed_global_cache.py` | 是 | false |
| P5 | 端到端测试：设 flag=true，验证 L1/L2/L3 全链路 | 是（可随时关回） | true/false 切换 |
| P6 | 清理：移除老逻辑分支（可选，最后一个 PR） | 是 | 移除 flag |

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

## 10. Turso Global_Cache_DB 建库指南

### 10.1 使用 Turso CLI 创建数据库

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

### 10.2 使用 Turso Management API（可选脚本）

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
