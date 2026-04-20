# MOMO_Script 工业级集成测试架构说明

本架构旨在为 `MOMO_Script` 提供一套稳定、仿真且极具防御性的自动化测试基座。通过动态凭据注入、真实内存数据库和进程交互沙盒，不仅防范常规逻辑漏洞，更能精准暴露出诸如 **异步死锁、终端挂起、底层 SQLite 文件抢延** 等高维运行态缺陷。

## 1. 核心设计原理

### 1.1 动态交互隔离与防死结 (TTY & Process Sandboxing)
由于自动化测试中的 `sys.stdin.isatty` 始终返回 False，传统测试总是完美跳过了与用户的选择交互。
* **实现方式**：在 `tests/core/test_interactive_process.py` 中，不使用 Mock 直接篡改核心行为，而是深度 Mock 给定系统入口点（伪造 `isatty=True` 和 `input`），并且拦截真实的进程替换命令 `subprocess.run`。
* **防御对象**：能够测试到真实环境从 `os.execv` 退订到 `subprocess.run` 防止 Windows TTY 接管丢失而卡死的环境重载逻辑。

### 1.2 高保真内存数据库驻留 (Persistent Memory DB)
许多模块（如 `weak_word_filter.py`）容易出现由于 Mock 过度而掩盖内部 SQL 返回缺失或未定义变量（如拼写错误）的问题。
* **实现方式**：采用真实 `sqlite3.connect("file:testdb?mode=memory&cache=shared", uri=True)` 并在夹具间挂载。这与基础的 Mock 完全不同，它是货真价实的 C 层数据库，不随代码里局部的 `conn.close()` 而消灭。
* **防御对象**：确保任何涉及到查询与连表操作的模块可以依赖真实的假数据验证（如检查平均熟悉度，判断空值回落等）。

### 1.3 工业级云端并发测试 (Concurrency & WalConflict Avoidance)
由于 LibSQL 底层（Rust Embedded Replica 层）会对每一个带 `sync_url` 的连接创建一个永固的后台专属同步守护精灵（`Sync Daemon`），极易导致 `.wal` 锁争用进而引发灾难级的 `WalConflict` 或 `Ctrl+C` 断开失效。
* **实现方式**：我们设计了 `tests/core/test_db_manager.py::test_db_concurrent_readonly_leak`。在激活云端模式 (`cloud_integ_env`) 下，使用数十个线程同时对核心接口发起高频快照写入。
* **防御对象**：用来强力制止未来开发者误用全局 `_get_conn()` 发起纯本地只读查询而导致的后台进程泄漏问题，严格验证架构的读写底层隔离（即核心 AI 批次需只读查表时强制基于 `_get_read_conn` 返回无后台 Daemon 的安全连接）。

---

## 2. 环境准备与配置

在运行带有集成效果的测试前，程序需要具备能够被动态注入的 Turso 凭据以确保验证行为最贴近真实产品。请在工程 `.env` 中按要求配制好：

```bash
# 测试专用用户库
TURSO_TEST_DB_URL=libsql://momo-test-user-ashershi.aws-ap-northeast-1.turso.io
TURSO_TEST_AUTH_TOKEN=your_test_user_token

# 测试专用 Hub 库
TURSO_TEST_HUB_DB_URL=libsql://momo-test-hub-ashershi.aws-ap-northeast-1.turso.io
TURSO_TEST_HUB_AUTH_TOKEN=your_test_hub_token
```

> **注意：**我们的测试 `conftest.py` 会全局（通过 `autouse`）默认使用 `isolate_cloud_configuration` 剥离生产库防止污染。如果需要建立带远端并发同步能力的环境请一定要依赖或手动引入 `cloud_integ_env` 夹具。

---

## 3. 测试文件分布指南

测试套件统一在 `tests/` 下根据模块特性执行分层。重点覆盖：

### 3.1 环境级核心模块
* **`tests/core/test_db_manager.py`**：囊括了海量并发插入队列调度、高并发 `WalConflict` 泄露防卫、以及在多态数据融合（Cloud vs Local SQLite）下的自动降级备份回溯。
* **`tests/core/test_interactive_process.py`**：隔离级验证交互流程以及 Windows IO 接托管兼容性验证。
* **`tests/core/test_weak_word_filter.py`**：高度内聚的记忆/熟悉度评分模型，通过 `URl=file:test%memory` 高保真库进行无感数据压延校验。

### 3.2 功能链路型集成
* **`tests/integration/test_cloud_sync.py`**：验证后台写线程从队列摄入直至底层同步远端的跨网路完整功能。

---

## 4. 如何运行测试

全局命令，建议进入工程根目录操作：

```powershell
$env:PYTHONPATH="."
# 运行全部验证套件（由于存在高并发压测，不推荐带 -s 同步打印）
pytest tests/ -v

# 仅运行数据库关键底层高频争用能力防线
pytest tests/core/test_db_manager.py::test_db_concurrent_readonly_leak -v
```

---

## 5. 开发建议与避坑必读

> [!WARNING]
> 不要过度使用 **Mock（桩函数）**！我们已经见识过了把 `_get_user_stats` Mock 掉之后将一个低级的变量 `NameError` 放进生产系统的教训；对于关键 IO 计算必须用内存 sqlite3 实现模拟；
> 严禁向读取性质或短命的 Python 局部函数滥用 **_get_conn()**！在支持 LibSQL 环境的机制下每次该方法被建立，都等价于在 Rust 底层召唤了一个永不死亡跟 WAL 死磕的同步死神！必须以调用带有独立线程缓存与限制特性的 **_get_read_conn()** 替换！
