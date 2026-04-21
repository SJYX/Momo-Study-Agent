# MOMO Script — 文档库清理与重构方案

## 1. Context

本项目 `docs/` 目录累计 38 个 `.md` 文件、6326 行。扫描后发现五类健康问题：

| 类型 | 代表文件 | 对 vibe coding 的伤害 |
| --- | --- | --- |
| A. 已完成的 "PHASE 计划" 伪装成活文档 | `PHASE_2/3/4_*.md`、`EMBEDDED_REPLICAS_*.md`、`OPEN_SOURCE_TRANSITION_PLAN.md`（~1200 行） | AI 打开会误以为"当前任务是 Phase 2"，把几百行"TODO"吃进上下文 |
| B. 已修复的故事穿着"修复指南"马甲 | `WAL_CONFLICT_FIX.md`、`CONCURRENCY_REFACTOR.md`（~780 行） | AI 以为问题未解决，给出重复建议；真正该落地到代码守则的精华被淹没 |
| C. 内容重叠 | `architecture/OVERVIEW.md + SYSTEM_ARCHITECTURE.md + DATA_FLOW.md`（3 份 ~140 行讲同一件事） | AI 被迫读 3 遍同一块内容，主要差别只是措辞 |
| D. 断片/残缺 | `LOG_SYSTEM.md` 开头混入 Phase3 残片；`decision_flow.md §7` 无头；`AUTO_SYNC.md §同步范围` 章节被错位嵌入"本地并发写入配置"之后；`database/README.md` 头 44 行与 `AI_CONTEXT §3.1` 重复 | AI 读出来是一堆 glitch |
| E. 失效引用 + 过期索引 | 6 个文档引用 `core/db_manager.py`，但该文件已是 3972 行的"兼容保留 facade"，真实业务逻辑在 `database/` 包；`DOCUMENT_INDEX.md` 漏列 10+ 文件 | AI 去错文件找函数，改错位置 |

**目标：** 做一轮文档断舍离，让未来 AI 会话打开 3 个文件（`CLAUDE.md` → `AI_CONTEXT.md` → 相关专项）就能拿到做任务所需的全部上下文，活目录体积缩减 30-40%。

---

## 2. 用户已决策的取舍

| 议题 | 选择 |
| --- | --- |
| 已完成 PHASE 文档处置 | **激进归档**：全部移到 `docs/history/phases/` |
| `DOCUMENT_INDEX.md` | **删除**（AI_CONTEXT + README 已是 SSoT） |
| `CLAUDE.md`（根目录） | **升级为 AI 会话首页**：当前状态 + 模块地图 + 红线 + 调试路径 |
| `architecture/` 合并 | **三合一**：OVERVIEW + SYSTEM_ARCHITECTURE + DATA_FLOW → `ARCHITECTURE.md`；保留 DATABASE_DESIGN 和 decision_flow |
| 分支策略 | **新建 `docs/cleanup`**（从 `main` 拉出，单 PR） |
| 归档前提炼精华 | **是**：WAL 重试、并发守则、Embedded Replicas 原理抽出 15-30 行规则补到 AI_CONTEXT / database/README，再归档原文 |

---

## 3. 目标状态（文档终局）

```
docs/
├── CHANGELOG.md                      # 保留，追加清理日志
├── api/                              # 不动
│   ├── available_models.txt
│   ├── maimemo_openapi.yaml
│   ├── momo_api_summary.md
│   ├── turso_api.md
│   └── xiaomi_mimo_api.md
├── architecture/
│   ├── ARCHITECTURE.md               # ⬅ 新（OVERVIEW+SYSTEM+DATA_FLOW 三合一）
│   ├── DATABASE_DESIGN.md            # 保留，修引用
│   ├── LOG_SYSTEM.md                 # 保留，删头部 9 行 Phase3 残片
│   └── decision_flow.md              # 保留，修 §7 断尾
├── dev/
│   ├── AI_CONTEXT.md                 # 保留，顶部新增"当前状态快照"；§3.1 吸收 WAL PRAGMA 细节
│   ├── AUTO_SYNC.md                  # 保留，修 §同步范围 的 Hub 错位
│   ├── CONTRIBUTING.md               # 保留，整节重写数据库规范引用
│   ├── DECISIONS.md                  # 保留，健康
│   ├── LOGGING.md                    # 保留
│   ├── LOGGING_LEVELS.md             # 保留，修 db_manager 引用
│   ├── QUICK_START.md                # 保留，清失效链接
│   └── WEB_UI_PLAN.md                # 保留（feat/web-ui 分支加的）
├── history/
│   ├── DOCS_COMPLETION_SUMMARY.md    # 不动
│   ├── DOCS_OPTIMIZATION_SUMMARY.md  # 不动
│   ├── NEW_USER_ZERO_CREDENTIAL_PLAN.md  # 不动
│   ├── VIBE_CODING_SUMMARY.md        # 不动
│   └── phases/                       # ⬅ 新
│       ├── README.md                 # 一页索引，记录每个归档文档的历史意义 + 当前替代位置
│       ├── PHASE_2_WRITE_SIMPLIFICATION.md
│       ├── PHASE_3_SYNC_OPTIMIZATION.md
│       ├── PHASE_4_TESTING_VALIDATION.md
│       ├── EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md
│       ├── EMBEDDED_REPLICAS_MIGRATION.md   # 从 architecture/ 挪来
│       ├── OPEN_SOURCE_TRANSITION_PLAN.md
│       ├── WAL_CONFLICT_FIX.md              # 从 docs/ 挪来
│       └── CONCURRENCY_REFACTOR.md          # 从 docs/ 挪来
└── prompts/                          # 不动（生产 prompts + 评估样本）
    ├── dev/gem_prompt_iteration.md
    ├── evaluation/sample.md
    ├── gem_prompt.md
    ├── score_prompt.md
    ├── refine_prompt.md
    └── original_prompt.md

项目根:
├── CLAUDE.md                         # ⬅ 升级：从 30 行指针 → 100 行 AI 首页
├── README.md                         # 小幅修订，移除 DOCUMENT_INDEX 引用
└── PROJECT_STATUS.md                 # 不动（但内容将在 CLAUDE.md 升级时参考同步）

数据库包:
└── database/README.md                # 删头 44 行（与 AI_CONTEXT §3.1 重复的 WAL 守则），吸收 PRAGMA 精华

已删除:
- docs/DOCUMENT_INDEX.md
- docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md（5 行纯指针 stub，history/ 已有完整版）
- docs/WAL_CONFLICT_FIX.md（移到 history/phases/）
- docs/CONCURRENCY_REFACTOR.md（移到 history/phases/）
- docs/architecture/OVERVIEW.md（合并入 ARCHITECTURE.md）
- docs/architecture/SYSTEM_ARCHITECTURE.md（合并入 ARCHITECTURE.md）
- docs/architecture/DATA_FLOW.md（合并入 ARCHITECTURE.md）
- docs/architecture/EMBEDDED_REPLICAS_MIGRATION.md（移到 history/phases/）
- docs/dev/PHASE_2_WRITE_SIMPLIFICATION.md（移到 history/phases/）
- docs/dev/PHASE_3_SYNC_OPTIMIZATION.md（移到 history/phases/）
- docs/dev/PHASE_4_TESTING_VALIDATION.md（移到 history/phases/）
- docs/dev/EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md（移到 history/phases/）
- docs/dev/OPEN_SOURCE_TRANSITION_PLAN.md（移到 history/phases/）
```

**净变化：** 38 个 md → 25 个 md；活目录（`docs/` 非 history）约 3500 行 → 约 2100 行；`history/phases/` +1800 行（一次写完永远不用再读）。

---

## 4. 精华提炼清单（归档前必须先做）

### 4.1 从 `WAL_CONFLICT_FIX.md` 提炼到 `database/README.md`

新增/更新章节 **"本地 WAL 并发配置（生产值）"**：

```markdown
## 本地 WAL 并发配置

所有本地 libsql / sqlite3 连接初始化时必须设置：

- `PRAGMA busy_timeout=5000` — WAL 锁冲突时自动重试 5 秒（不是立即失败）
- `PRAGMA wal_autocheckpoint=1000` — 每 1000 页自动 checkpoint，避免 WAL 文件无限增长
- `PRAGMA synchronous=NORMAL` — 性能/安全折衷
- `PRAGMA journal_mode=WAL`

已在以下位置落地：`_open_local_connection`、`_connect_embedded_replica`、`_get_hub_local_conn._open_local_connection`。

## 批量写入重试守则

`_execute_batch_writes()` 对 WAL 冲突采用 3 次指数退避（100ms → 200ms → 400ms）。
`_writer_daemon` 遇到 WAL 冲突时保留 batch、睡 500ms 等 replica，其它异常则丢弃 batch 继续。
```

### 4.2 从 `CONCURRENCY_REFACTOR.md` 提炼到 `ARCHITECTURE.md`

新增架构图段落 **"并发模型"**，保留其精华的架构图：

```
业务线程（多）—┬→ [ThreadLocal 读连接] → 本地 SQLite 副本（读专用）
               └→ [写队列 Queue(10000)] → [后台写守护线程（单）] → Embedded Replica（写专用）
                                                                      ↕
                                                               [云端 Turso（conn.sync()）]
```

配一句话解释：读写分离、写序列化、严禁业务线程直连。详细实现见 `database/connection.py`。

### 4.3 从 `EMBEDDED_REPLICAS_MIGRATION.md` 提炼到 `ARCHITECTURE.md`

新增段落 **"数据同步模型（libsql Embedded Replicas）"**，2-3 段讲清：
- Embedded Replica = 本地 SQLite 文件 + libsql 协议自动帧同步
- `conn.sync()` 做增量，不用手工对比元数据
- 旧手工 `_sync_table` / `_sync_progress_history` / `_sync_hub_table` 已删除
- 纯本地模式（无 TURSO_DB_URL）自动降级为 sqlite3

### 4.4 AI_CONTEXT.md 顶部新增"当前状态快照"

写一段 15-20 行的"截至 YYYY-MM-DD 的项目态势"：

```markdown
## 0.5 当前状态快照（2026-04-21）

- 版本：1.0.0；Python 3.12+。
- 数据层：已完成 Embedded Replicas 迁移（Phase 0-4），`conn.sync()` 取代手工增量；
  `core/db_manager.py` 是 3972 行兼容 facade，新代码应直接引用 `database/` 包。
- 同步层：高性能 feat/high-perf-sync 分支已合回 main；写队列 + 后台守护线程已稳定。
- 正在进行：Web 前端界面（feat/web-ui 分支，见 dev/WEB_UI_PLAN.md）。
- 近期不碰：Prompt 文件（docs/prompts/），API 参考（docs/api/）。
```

这节**每次发版或大 PR 合并后必须更新**，让 AI 一眼看清所处阶段。

---

## 5. 引用修复清单（批量替换）

活文档（保留或合并后的文档）里所有 `core/db_manager.py::X` 引用，按下表替换为真实实现位置：

| 旧引用 | 新位置 |
| --- | --- |
| `get_processed_ids_in_batch` / `mark_processed` / `save_ai_word_note` / `save_ai_word_notes_batch` / `save_ai_batch` / `mark_processed_batch` | `database/momo_words.py` |
| `find_words_in_community_batch` / `get_latest_progress` / `get_unsynced_notes` | `database/momo_words.py` |
| `sync_databases` / `sync_hub_databases` / `mark_note_synced` / `set_note_sync_status` | `database/momo_words.py` |
| `_get_conn` / `_get_local_conn` / `_get_read_conn` / `_get_cloud_conn` | `database/connection.py` |
| `_get_main_write_conn_singleton` / `_get_hub_write_conn_singleton` / `_writer_daemon` | `database/connection.py` |
| `_execute_batch_writes` / `_row_to_dict` / `_get_singleton_conn_op_lock` | `database/connection.py` |
| `_create_tables` / `init_db` / `_init_hub_schema` / `init_users_hub_tables` | `database/schema.py` |
| `get_timestamp_with_tz` / `clean_for_maimemo` / `_is_sqlite_data_corruption_error` | `database/utils.py` |
| Hub 用户 CRUD 相关函数 | `database/hub_users.py` |

**历史文档（移到 `history/phases/` 后）不改引用**——它们是时间胶囊，保留旧路径更能反映当时事实。

**实施方式**：`core/db_manager.py` 保留，因为仍在工作的 facade；所有引用它为入口的写法都替换。

**具体执行**：用 `grep -rn "core/db_manager" docs/architecture docs/dev CLAUDE.md database/README.md` 过一遍，逐处评估后改写或明确注明"历史实现"。Grep 统计显示活文档中 13 处引用（扣除将被归档的 6 个文件里的 16 处，活文档实际约 25 处）。

---

## 6. 执行拆分（提交级粒度）

每个 commit 独立可 revert，建议按以下顺序：

### Commit 1 — 建历史归档骨架 + 移档

```bash
git checkout main
git checkout -b docs/cleanup
mkdir -p docs/history/phases

git mv docs/dev/PHASE_2_WRITE_SIMPLIFICATION.md          docs/history/phases/
git mv docs/dev/PHASE_3_SYNC_OPTIMIZATION.md             docs/history/phases/
git mv docs/dev/PHASE_4_TESTING_VALIDATION.md            docs/history/phases/
git mv docs/dev/EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md docs/history/phases/
git mv docs/dev/OPEN_SOURCE_TRANSITION_PLAN.md           docs/history/phases/
git mv docs/architecture/EMBEDDED_REPLICAS_MIGRATION.md  docs/history/phases/
git mv docs/WAL_CONFLICT_FIX.md                          docs/history/phases/
git mv docs/CONCURRENCY_REFACTOR.md                      docs/history/phases/
git rm docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md    # 5 行 stub

# 新增 docs/history/phases/README.md：一页目录 + 替代位置
```

commit: `docs: 归档已完成的 PHASE/MIGRATION/FIX 文档到 history/phases/`

### Commit 2 — 提炼精华到活文档

修改 3 个活文档（新增小节或替换）：
- `docs/dev/AI_CONTEXT.md` 顶部插入 §0.5 当前状态快照
- `database/README.md` 新增/替换 "本地 WAL 并发配置" 和 "批量写入重试守则" 章节（同时删除头 44 行与 AI_CONTEXT §3.1 重复的泛化守则）
- （§4.2/§4.3 的架构/同步精华先准备好，随 Commit 3 一起落）

commit: `docs: 把 WAL 重试与并发守则精华落到 AI_CONTEXT 与 database/README`

### Commit 3 — architecture 三合一

- 新建 `docs/architecture/ARCHITECTURE.md`（含精华段落 §4.2 并发模型、§4.3 同步模型）
- `git rm docs/architecture/OVERVIEW.md`
- `git rm docs/architecture/SYSTEM_ARCHITECTURE.md`
- `git rm docs/architecture/DATA_FLOW.md`

commit: `docs: 合并 architecture/OVERVIEW + SYSTEM + DATA_FLOW 为单一 ARCHITECTURE.md`

### Commit 4 — 修断片

- `docs/architecture/LOG_SYSTEM.md`：删除第 1-9 行 "Phase 3 运维优化" 残片，保留 "# 日志系统设计" 起的内容
- `docs/architecture/decision_flow.md`：重写 §7 的断尾（line 98-111），让 §6 相关文档 → §7 配置分支（含 7.1/7.2/7.3） → §8 建议阅读顺序 → §9 结论 正常串联
- `docs/dev/AUTO_SYNC.md`：把 line 156-164 的 "### Hub 库" 挪回 "## 同步范围" 节下，与 "### 用户库" 并列（目前被错位嵌到"本地并发写入配置"之后）
- `database/README.md` 头部重复段：已在 Commit 2 处理

commit: `docs: 修复 LOG_SYSTEM / decision_flow / AUTO_SYNC 的结构断片`

### Commit 5 — 引用修复

按 §5 表逐处替换 `core/db_manager.py::X` 引用：
- `docs/architecture/DATABASE_DESIGN.md`
- `docs/architecture/decision_flow.md`
- `docs/architecture/ARCHITECTURE.md`（刚新建）
- `docs/dev/CONTRIBUTING.md`（`## 数据库规范` 节整块重写 `_row_to_dict / _get_conn / get_timestamp_with_tz` 路径）
- `docs/dev/LOGGING_LEVELS.md`（11 处，多数是"详见 core/db_manager" 类句式，按表替换）
- `docs/dev/AUTO_SYNC.md`
- `docs/dev/AI_CONTEXT.md`
- `CLAUDE.md`（升级时一并处理，见 Commit 6）

commit: `docs: 把活文档里 core/db_manager 引用改指到 database/ 包真实位置`

### Commit 6 — CLAUDE.md 升级为 AI 首页 + 删 DOCUMENT_INDEX

`CLAUDE.md` 结构（约 100 行）：

```markdown
# Momo Study Agent — AI 会话首页

## 当前状态（xxxx-xx-xx）
（从 AI_CONTEXT §0.5 同步精简版，1-2 行）

## 你在哪里
本项目是基于墨墨 OpenAPI 的多用户 AI 助记工具，Python 3.12+，CLI 为主、Web 前端在 feat/web-ui 分支。

## 模块地图（10 行表格）
| 做什么 | 去哪改 | 别碰 |
| --- | --- | --- |
| 主流程编排 | main.py | 进程锁逻辑 |
| 业务总线 | core/study_workflow.py | UI/DB 调用签名 |
| 墨墨 API | core/maimemo_api.py | 频控 lock |
| AI 生成 | core/gemini_client.py / mimo_client.py | — |
| 数据库读写 | database/momo_words.py（业务）、database/connection.py（连接）、database/schema.py（表） | core/db_manager.py（兼容 facade，只读不改） |
| 配置加载 | config.py | `ACTIVE_USER` 全局语义 |
| 多用户 profile | core/profile_manager.py / core/config_wizard.py | data/profiles/*.env 真实凭据 |
| 日志 | core/logger.py | print() 禁用 |
| 同步 | core/sync_manager.py（业务）、database/connection.py（引擎）| conn.sync() 路径 |

## 三条红线（违反即停）
1. 任何写入必须经 `_write_queue`（`database/connection.py`），严禁业务线程直连 SQL。
2. Prompt 硬编码禁止；必须放 `docs/prompts/*.md`，由 `config.py` 常量读取。
3. Hub 库（用户元数据）与个人库（学习数据）严格分离，凭据不落个人库。

详细 MUST 清单见 [docs/dev/AI_CONTEXT.md](docs/dev/AI_CONTEXT.md)。

## 找东西
- 规则/红线：`docs/dev/AI_CONTEXT.md`
- 架构/数据流：`docs/architecture/ARCHITECTURE.md`
- 表结构：`docs/architecture/DATABASE_DESIGN.md`
- 同步机制：`docs/dev/AUTO_SYNC.md`
- 日志：`docs/dev/LOGGING.md` / `LOGGING_LEVELS.md`
- 已完成的历史项目（别当作 TODO）：`docs/history/phases/`
- 当前正在做：`docs/dev/WEB_UI_PLAN.md`

## 调试定位
- 运行日志：`logs/<user>.log`
- 用户数据库：`data/history-<user>.db`
- Profile：`data/profiles/<user>.env`
- 进程锁：`data/.process.lock`（被占则只能有一个 Python 进程在跑）

## 默认回归命令
`python -m pytest tests/ -v --tb=short -m "not slow"`
```

同时：
- `git rm docs/DOCUMENT_INDEX.md`
- `README.md`：移除"文档索引 → DOCUMENT_INDEX.md" 的引用；把 "AI 开发上下文入口" 指向 `CLAUDE.md → docs/dev/AI_CONTEXT.md`

commit: `docs: 升级 CLAUDE.md 为 AI 会话首页并删除 DOCUMENT_INDEX.md`

### Commit 7 — CHANGELOG + 收尾

- `docs/CHANGELOG.md` 追加条目 "2026-04-21 · 文档大清理"，记录所有移动/删除/合并/升级
- 扫一遍 `history/DOCS_OPTIMIZATION_SUMMARY.md` / `history/DOCS_COMPLETION_SUMMARY.md` 里的 DOCUMENT_INDEX 引用，加一条后记"已于 2026-04-21 移除"（历史文档本身内容不改）

commit: `docs: CHANGELOG 记录 2026-04-21 文档清理`

---

## 7. 验证步骤

**自动验证：**

```bash
# 1. 没有断链（对 docs/ 内的相对引用做 grep 存在性检查）
python - <<'PY'
import os, re, sys
broken = []
root = "docs"
for dp, dn, fn in os.walk(root):
    for f in fn:
        if not f.endswith(".md"): continue
        p = os.path.join(dp, f)
        with open(p, "r", encoding="utf-8") as h:
            for i, line in enumerate(h, 1):
                for m in re.finditer(r"\]\(([^)]+\.md[^)]*)\)", line):
                    link = m.group(1).split("#")[0]
                    target = os.path.normpath(os.path.join(dp, link))
                    if not os.path.exists(target):
                        broken.append((p, i, link))
print("broken links:", len(broken))
for b in broken[:20]: print(b)
sys.exit(1 if broken else 0)
PY

# 2. 活文档里不应再有 DOCUMENT_INDEX 引用
! grep -r "DOCUMENT_INDEX" docs/ --include="*.md" | grep -v "^docs/history/"

# 3. 活文档里不应再有对已归档文件的相对引用
! grep -rE "WAL_CONFLICT_FIX|CONCURRENCY_REFACTOR|PHASE_[234]|EMBEDDED_REPLICAS_(MIGRATION|PHASE)|OPEN_SOURCE_TRANSITION" \
    docs/ --include="*.md" | grep -v "^docs/history/"

# 4. 全量测试保持绿
python -m pytest tests/ -v --tb=short -m "not slow"
```

**人工验证（AI vibe coding 场景模拟）：**

1. 扮演"新 AI 会话第一次打开这个项目"：只读 `CLAUDE.md`，2 分钟内能否说出"如果我要加一个新 AI 提供商，该改哪些文件？不能碰什么？"
2. 扮演"修同步 bug"：从 `CLAUDE.md` → 对应专项文档 → 实际代码，路径是否顺畅？
3. 打开 `docs/history/phases/README.md`：能否从归档文档的一句话简介反向定位到当前代码的对应实现？

---

## 8. 风险与兜底

| 风险 | 缓解 |
| --- | --- |
| 归档后有人记得老路径直接访问 404 | `docs/history/phases/README.md` 提供重定向表；`docs/CHANGELOG.md` 留迁移记录 |
| 外部链接（如 GitHub issue）指向老路径 | `git mv` 保留 rename 检测，GitHub 会自动映射；实际访问仍能打开（只是路径换了前缀） |
| CLAUDE.md 升级后和 AI_CONTEXT 内容出现矛盾 | CLAUDE.md = "你在哪里"（地图），AI_CONTEXT = "你能做什么"（规则），界限是：CLAUDE.md 只放指向，规则全走 AI_CONTEXT；矛盾时以 AI_CONTEXT 为准并修 CLAUDE.md |
| 引用修复改漏 | Commit 5 用 §5 表 + grep 核验：`grep -rn "core/db_manager" docs/architecture docs/dev CLAUDE.md database/README.md` 活文档预期 0 命中（或仅存于明确标注"历史 facade"的段落） |
| architecture 三合一时精华丢失 | Commit 3 前先把每个被删文件 `git show HEAD:docs/architecture/OVERVIEW.md` 备份到临时位置，确认 ARCHITECTURE.md 至少覆盖所有关键点后再 rm |
| feat/web-ui 分支后续合并冲突 | 本次清理不改 `docs/dev/WEB_UI_PLAN.md`（已在 feat/web-ui 独立管理）；合并顺序建议：docs/cleanup 先回 main，feat/web-ui 再 rebase on main |

---

## 9. 不动的范围（Scope Out）

- **代码层面**：不改 `core/*.py` / `database/*.py` / `main.py` / `config.py`。只动 `.md` 和 `database/README.md`。
- **Prompts**：`docs/prompts/` 下所有文件（生产 prompt + 评估样本）不改。
- **API 参考**：`docs/api/` 除索引引用外不改。
- **既有 history/**：`docs/history/VIBE_CODING_SUMMARY.md` 等已归档文档不动。
- **测试**：`tests/` 不改。

---

## 10. 一句话总结

**一次 PR 做三件事：** (a) 把 8 份"已完成的 PHASE/FIX 文档" + 2 份"纯指针 stub" + DOCUMENT_INDEX 从活目录清走；(b) 把 3 份重叠架构文档合成 1 份，同时修掉 4 处断片和 25 处失效引用；(c) 把 `CLAUDE.md` 升级为 100 行的 AI 会话首页。目标：AI vibe coding 时"读完 CLAUDE.md 就知道该去哪"，而不是在 38 个文件里淘金。

---

## 11. 本方案的前置步骤

1. **切回 main 分支**：`git checkout main`（当前在 `feat/web-ui`）
2. **从 main 拉新分支**：`git checkout -b docs/cleanup`
3. 按 §6 的 7 个 commit 顺序执行
4. 自测通过后开 PR 合回 main

> 注：本方案文档本身放在 plan 目录，如需归档到仓库（类似 `WEB_UI_PLAN.md`），可在 Commit 6 或 7 附带复制一份到 `docs/history/phases/DOCS_CLEANUP_PLAN.md`（而不是 dev/，因为这份工作交付后也就成了历史）。
