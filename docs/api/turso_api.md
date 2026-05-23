# Turso Python API Reference (pyturso)

> 本文档聚焦 `pyturso` 及 `turso.sync` 的核心 API，适用于本地/嵌入式数据库与同步场景。
>
> 来源: https://docs.turso.tech/llms.txt (2026-05-22 更新)

---

## 1. 包选择: pyturso vs libsql

| 特性 | `pyturso` | `libsql` |
|------|-----------|----------|
| 适用场景 | 本地/嵌入式数据库、同步 | 已有 libsql 代码库 |
| 引擎 | Turso Database (全新重写) | libSQL (SQLite fork) |
| 并发写入 | 支持 (MVCC) | 不支持 |
| 同步 | push/pull (local-first) | Embedded Replicas (写入走云端主库) |
| API | Python `sqlite3` 兼容 | Python `sqlite3` 兼容 |

**新项目推荐使用 `pyturso`** — 基于 Turso Database 引擎，支持并发写入和 local-first 同步。

---

## 2. 安装

```bash
# uv
uv add pyturso

# pip
pip install pyturso
```

---

## 3. 基础连接与查询

```python
import turso

# 本地文件数据库
db = turso.connect("app.db")

# 内存数据库
db = turso.connect(":memory:")

# 创建表 & 插入数据
db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
db.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
db.commit()

# 查询
for row in db.execute("SELECT * FROM users"):
    print(row)
```

---

## 4. Turso Sync (`turso.sync`)

所有读写操作在本地文件上执行（快速、支持离线），通过 `.push()` / `.pull()` 显式控制同步时机。

### 4.1 连接配置

```python
import os
import turso.sync

conn = turso.sync.connect(
    path="./app.db",                                    # 本地数据库路径
    remote_url=os.environ["TURSO_DATABASE_URL"],        # libsql://... 格式
    remote_auth_token=os.environ["TURSO_AUTH_TOKEN"],   # 认证 token
    # long_poll_timeout_ms=10_000,                      # 可选: 服务端长轮询超时
    # bootstrap_if_empty=False,                         # 可选: 首次启动不自动从远端拉取
)
```

> **注意**: 首次运行时本地数据库会自动从远端引导，此时远端必须可达。设置 `bootstrap_if_empty=False` 可跳过自动引导。

### 4.2 同步 API

#### `push()` — 推送本地变更到云端

```python
conn.execute("INSERT INTO notes (id, body) VALUES (?, ?)", ("n1", "hello"))
conn.commit()
conn.push()  # 逻辑 SQL 语句发送到服务端，冲突策略: last push wins
```

#### `pull()` — 拉取远端变更到本地

```python
changed = conn.pull()  # 返回 bool，表示是否有变更
print("Pulled changes:", changed)
```

#### `checkpoint()` — 压缩本地 WAL

同步数据库禁用了自动 checkpoint，需手动调用以控制磁盘占用：

```python
conn.checkpoint()
```

#### `stats()` — 同步统计信息

```python
s = conn.stats()
print({
    "cdc_operations": s.cdc_operations,
    "main_wal_size": s.main_wal_size,
    "revert_wal_size": s.revert_wal_size,
    "network_received_bytes": s.network_received_bytes,
    "network_sent_bytes": s.network_sent_bytes,
    "last_pull_unix_time": s.last_pull_unix_time,
    "last_push_unix_time": s.last_push_unix_time,
    "revision": s.revision,
})
```

---

## 5. 离线优先策略

设置 `bootstrap_if_empty=False` 允许应用在无网络时首次启动：

```python
import os
import turso.sync

conn = turso.sync.connect(
    path="./local.db",
    remote_url=os.environ["TURSO_URL"],
    remote_auth_token=os.environ["TURSO_AUTH_TOKEN"],
    bootstrap_if_empty=False,
)

# 启动时尝试拉取
try:
    conn.pull()
except Exception:
    pass  # 离线，本地数据仍可读写

# 定时或网络恢复时推送
def sync_when_online(conn):
    try:
        conn.push()
    except Exception:
        pass  # 无连接，变更安全保存在本地文件
```

---

## 6. 加密 (Encryption at Rest)

```python
from turso import connect, EncryptionOpts

conn = connect(
    "encrypted.db",
    experimental_features="encryption",
    encryption=EncryptionOpts(
        cipher="aegis256",
        hexkey="b1bbfda4f589dc9daaf004fe21111e00dc00c98237102f5c7002a5669fc76327"
    )
)
```

**支持的加密算法**: `aegis256`, `aegis256x2`, `aegis128l`, `aegis128x2`, `aegis128x4`, `aes256gcm`, `aes128gcm`

> **警告**: 加密数据库无法用标准 SQLite 客户端打开，必须使用 pyturso 引擎。

---

## 7. 冲突解决

同步采用 **Last Push Wins** 策略：

1. 两个客户端修改同一行并 push，后 push 的客户端定义远端状态
2. pull 时如有未推送的本地变更：
   - 本地数据库临时回滚到最后同步状态
   - 应用远端变更
   - 重放未推送的本地变更
   - 回滚-重放过程是原子的

---

## 8. SQLAlchemy 集成

安装 SQLAlchemy 方言：

```bash
pip install sqlalchemy-libsql
```

### 连接方式

```python
from sqlalchemy import create_engine

# Embedded Replicas (推荐)
engine = create_engine(
    "sqlite+libsql:///embedded.db",
    connect_args={
        "auth_token": TURSO_AUTH_TOKEN,
        "sync_url": TURSO_DATABASE_URL,
    },
)

# 纯远程
engine = create_engine(
    f"sqlite+{TURSO_DATABASE_URL}?secure=true",
    connect_args={"auth_token": TURSO_AUTH_TOKEN},
)

# 内存
engine = create_engine("sqlite+libsql://")

# 本地文件
engine = create_engine("sqlite+libsql:///local.db")
```

### 模型定义 & 查询

```python
from sqlalchemy import String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

class Base(DeclarativeBase):
    pass

class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

# 查询
with Session(engine) as session:
    for item in session.scalars(select(Item)):
        print(item)
```

---

## 9. 本地同步服务器 (开发测试)

使用 Turso CLI 启动本地同步服务器，无需 Turso Cloud：

```bash
tursodb ./server.db --sync-server 0.0.0.0:8080
```

客户端连接（无需 auth token）：

```python
import turso.sync

# Client A: 写入并推送
client_a = turso.sync.connect(
    path="./client-a.db",
    remote_url="http://localhost:8080",
)
client_a.execute("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT)")
client_a.commit()
client_a.execute("INSERT INTO notes VALUES ('n1', 'hello from A')")
client_a.commit()
client_a.push()

# Client B: 拉取
client_b = turso.sync.connect(
    path="./client-b.db",
    remote_url="http://localhost:8080",
)
client_b.pull()
rows = client_b.execute("SELECT * FROM notes").fetchall()
print(rows)  # [('n1', 'hello from A')]
```

---

## 10. Partial Sync (实验性)

按需拉取数据库页面，无需下载完整文件。

### Prefix Bootstrap — 按字节前缀引导

```python
import turso.sync

conn = turso.sync.connect(
    path="./app.db",
    remote_url="libsql://...",
    partial_sync_opts=turso.sync.PartialSyncOpts(
        bootstrap_strategy=turso.sync.PartialSyncPrefixBootstrap(length=128 * 1024),
    ),
)
```

### Query Bootstrap — 按查询结果引导

```python
conn = turso.sync.connect(
    path=":memory:",
    remote_url="libsql://...",
    partial_sync_opts=turso.sync.PartialSyncOpts(
        bootstrap_strategy=turso.sync.PartialSyncQueryBootstrap(
            query="SELECT * FROM messages WHERE user_id = 'u_123' LIMIT 100"
        ),
    ),
)
```

### 可选参数

- `segment_size`: 批量读取段大小，默认 128 KiB
- `prefetch`: 预测并预取相关页面（如 B-tree 子节点）

```python
turso.sync.connect(
    ...,
    partial_sync_opts=turso.sync.PartialSyncOpts(
        bootstrap_strategy=turso.sync.PartialSyncPrefixBootstrap(length=128 * 1024),
        segment_size=16 * 1024,
        prefetch=True,
    ),
)
```

---

## 11. libsql 远程访问 (无本地文件场景)

适用于 serverless/无状态环境，无法存储本地文件时直接通过网络访问 Turso Cloud。

```bash
pip install libsql
```

```python
import os
import libsql

conn = libsql.connect(
    database=os.environ["TURSO_DATABASE_URL"],  # libsql://... 格式
    auth_token=os.environ["TURSO_AUTH_TOKEN"],
)

conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
conn.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
conn.commit()

rows = conn.execute("SELECT * FROM users").fetchall()
```

> **建议**: 大多数场景推荐使用 `turso.sync`（本地读写 + push/pull），仅在无法存储本地文件时使用 `libsql` 远程访问。

---

## 12. SQL over HTTP (无 SDK 轻量访问)

任何 HTTP 客户端均可直接调用，无需安装 Python SDK。

### 获取连接信息

```bash
# 获取 HTTP URL
turso db show <db-name> --http-url

# 创建 token
turso db tokens create <db-name>
```

### Python 示例 (requests)

```python
import requests
import os

url = f"{os.environ['TURSO_DATABASE_URL'].replace('libsql://', 'https://')}/v2/pipeline"
token = os.environ["TURSO_AUTH_TOKEN"]

resp = requests.post(url, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}, json={
    "requests": [
        {"type": "execute", "stmt": {"sql": "SELECT * FROM users"}},
        {"type": "close"},
    ],
})

data = resp.json()
for result in data["results"]:
    if result["type"] == "ok":
        print(result["response"])
```

### 参数绑定

```python
# 位置参数
{"stmt": {"sql": "SELECT * FROM users WHERE id = ?", "args": [{"type": "integer", "value": "1"}]}}

# 命名参数
{"stmt": {"sql": "SELECT * FROM users WHERE name = :name", "named_args": [{"name": "name", "value": {"type": "text", "value": "Alice"}}]}}
```

### 响应字段

| 字段 | 说明 |
|------|------|
| `cols` | 返回列信息 |
| `rows` | 返回行数据 |
| `affected_row_count` | 影响行数 |
| `last_insert_rowid` | 最后插入行 ID |
| `rows_read` / `rows_written` | 读写行数统计 |
| `query_duration_ms` | 查询耗时 (ms) |

---

## 13. 向量搜索 (Vector Search)

Turso 原生支持向量相似度搜索，无需扩展。适用于语义搜索、推荐系统、RAG 等场景。

### 向量类型

| 类型 | 每维度存储 | 适用场景 |
|------|-----------|---------|
| `vector32` | 4 字节 | 大多数 ML embedding (OpenAI, sentence-transformers) |
| `vector64` | 8 字节 | 高精度场景 |
| `vector8` | 1 字节 | 大规模搜索，可接受精度损失 |
| `vector1bit` | 1 bit | 二进制哈希，~32x 压缩 |
| `vector32_sparse` | 非零值+索引 | TF-IDF、高维稀疏数据 |

### 建表 & 插入

```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    title TEXT,
    content TEXT,
    embedding BLOB
);

INSERT INTO documents (title, content, embedding) VALUES
    ('ML basics', 'Introduction to ML...', vector32('[0.2, 0.5, 0.1, 0.8]')),
    ('DB fundamentals', 'How databases work...', vector32('[0.1, 0.3, 0.9, 0.2]'));
```

### 相似度查询

```sql
-- 余弦距离 (文本 embedding 推荐)
SELECT title,
       vector_distance_cos(embedding, vector32('[0.25, 0.55, 0.15, 0.75]')) AS distance
FROM documents
ORDER BY distance
LIMIT 5;

-- 欧氏距离 (图像 embedding、空间数据)
SELECT title,
       vector_distance_l2(embedding, vector32('[0.25, 0.55, 0.15, 0.75]')) AS distance
FROM documents
ORDER BY distance
LIMIT 5;
```

### 向量索引 (DiskANN 加速)

大数据集建议创建向量索引，使用近似最近邻算法加速查询：

```sql
-- 创建索引
CREATE INDEX doc_idx ON documents(libsql_vector_idx(embedding));

-- 使用索引查询 top-k
SELECT title FROM vector_top_k('doc_idx', vector32('[0.25, 0.55, 0.15, 0.75]'), 3)
JOIN documents ON documents.rowid = id;
```

索引可选参数：

```sql
CREATE INDEX doc_idx ON documents(
    libsql_vector_idx(embedding, 'metric=l2', 'compress_neighbors=float8')
);
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `metric` | 距离函数: `cosine` / `l2` | `cosine` |
| `max_neighbors` | 每节点最大邻居数 | `3 * sqrt(D)` |
| `compress_neighbors` | 邻居压缩类型 | 不压缩 |
| `search_l` | 搜索时访问邻居数 | 200 |
| `insert_l` | 插入时访问邻居数 | 70 |

### 工具函数

```sql
-- 提取向量为 JSON
SELECT vector_extract(embedding) FROM documents WHERE id = 1;

-- 拼接向量
SELECT vector_concat(vector32('[1.0, 2.0]'), vector32('[3.0, 4.0]'));

-- 切片
SELECT vector_slice(vector32('[1.0, 2.0, 3.0, 4.0, 5.0]'), 1, 4);
```

> **限制**: 最大维度 65536；`vector1bit` 不支持欧氏距离。

---

## 14. 已知问题与变通方案 (Known Issues)

> 经过 2026-05 大量端到端测试沉淀的"踩过的坑",新人接 pyturso 时**先读完这一章再写代码**。

### 14.1 首次 bootstrap 慢 (80~150s) — 阻塞主线程

**症状**: 远端库 ~10MB 时,`turso.sync.connect()` 在数据下载完(几秒)后会**继续阻塞 70~140s**,
日志看不到任何变化,客户端 CPU=0,没有持有任何 TCP 连接,但 Python 调用就是不返回。

**根因**: pyturso 的 `connect_sync` 内部在 `sync_db.connect()` 阶段会做一次 server-side
long-poll 等待变更通告,服务端默认会挂起接近自己的超时上限才返回空。这段时间 `.db` 主文件
已经写完、`-info` 边车已经存在,但 pyturso 不返回连接对象。

**确认这是慢、不是死**:

- 文件大小停在 ≈10 MB **不变化**
- 进程 CPU 累计 < 1s
- `Get-NetTCPConnection -OwningProcess <PID>` 显示**没有**指向 `*.turso.io` 的连接
- 等满约 80~150s 后 connect 会自己返回

**变通**:

1. ⚠️ **不要** 在调用线程上等(会冻住 Web 服务器):
   - 把 `turso.sync.connect()` 放到后台线程,主线程立即返回给上游(参考
     [`web/backend/user_context.py`](../../web/backend/user_context.py)
     的 `_warmup_chain_safe`)
2. ⚠️ **不要** 试图加 timeout 强行打断:
   - `socket.setdefaulttimeout(N)` 在我们的实测里 N=120s 也没触发(pyturso 内部对 socket
     超时有重试,会"吞错重试"直到耗尽)
   - 设小了反而触发 `IncompleteRead` 错误,文件已写但状态不一致
   - `long_poll_timeout_ms=N` 这个参数官方说**只对显式 pull 生效, 对 connect 内部 long-poll 不生效**
3. ❌ **`bootstrap_if_empty=False` + 手动 pull**:
   - 实测 pull 13 分钟后抛 `IncompleteRead`,数据为空。**不要走这条路**
4. ❌ **`PartialSyncOpts(PrefixBootstrap(128KB))`** (官方推荐"快速首连"):
   - Windows 平台直接 Rust panic: `has_hole is not supported for the given IO implementation`
   - 这条路在 Windows 上**被 pyturso 自身阻塞**,只能等上游修
5. ✅ **正确做法 — 后台 bootstrap + readiness gate**:
   - 见 [`web/backend/user_context.py`](../../web/backend/user_context.py)
     的 `_warmup_sync_and_kick_async` 实现:
     - `_create_context` 立即返回,把 init_db 推到 daemon 线程
     - 状态机 `not_started → db_init_in_progress → db_init_done → done`
   - 见 [`web/backend/app.py`](../../web/backend/app.py) 的 `_gate_unready_db` middleware:
     - 业务 API 在 `db_init_in_progress` 时返回 503 + `SYNCING` + `Retry-After: 5`
     - 白名单 `/api/health`, `/api/users`, `/api/preflight`, `/api/ops`
   - 见 [`/api/health/ready`](../../web/backend/app.py) 端点 + 前端
     [`SyncGate.tsx`](../../web/frontend/src/components/SyncGate.tsx) 遮罩组件

### 14.2 URL scheme 必须保留 `libsql://`

`turso.sync.connect()` 接受 `libsql://...` 的 URL,内部会自己 replace 为 `https://`
(见 `turso/lib_sync.py:440-441`)。**不要在传参前提前替换**——传 `https://` 虽然能下载数据,
但行为未文档化,可能不会建立完整 sync 元数据。

`docs/api/turso_api.md` 中`§12 SQL over HTTP` 那种 `/v2/pipeline` 直连场景才需要手动改
`https://`,**不要把那条路径的 URL 转换搬到 `turso.sync.connect()` 上**。

### 14.3 `_pyturso.py` 进度日志 — 给用户反馈"还活着"

由于首次 bootstrap 没有进度回调,我们在 wrapper 里开了 daemon 线程每 5s 报一次
`.db` 文件大小:

```text
[主库] bootstrap 进行中... 已 5s, .db 文件 10.11 MB (首次 bootstrap 可能耗时 60-150s)
[主库] bootstrap 进行中... 已 10s, .db 文件 10.11 MB
...
[主库] turso.sync.connect 完成 (耗时 141.5s)
```

文件大小**不再增长**就是已经进到 long-poll 等待阶段,继续等就行,不要 kill 进程。

### 14.4 关于 `auth_token` vs `remote_auth_token`

官方部分文档(包括 [`sync/usage`](https://docs.turso.tech/sync/usage))页面写的关键字参数是
`remote_auth_token`,但**实际 Python 实现**(`turso/lib_sync.py:414`)用的是 `auth_token`。
保留 `auth_token=`,不要改成 `remote_auth_token=` — 后者会被 Python 当成未识别参数报错。

### 14.5 `pyturso` 是 BETA 软件

[PyPI](https://pypi.org/project/pyturso/) 明确说当前版本 (v0.5.1, 2026-03 发布) 仍可能有
bug。已知问题列表见 [Issue #5971](https://github.com/tursodatabase/turso/issues/5971):
零填充页面 bug (我们尚未确认是否影响我们的场景)。建议:

- 升级 pyturso 前先在 dev 环境跑一遍 [`tests/integration/ping_db.py`](../../tests/integration/ping_db.py)
- 重要数据继续依赖 V007 quarantine 机制做兜底
