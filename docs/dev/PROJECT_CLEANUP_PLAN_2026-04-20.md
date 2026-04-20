# 项目整理计划书（2026-04-20）

## 一、现状诊断（基于仓库当前状态）
- 代码主体分层清晰（`core/`、`database/`、`tests/`、`docs/`），但“规范与实际”有漂移。
- 工具链不一致：`pyproject.toml` 已配置 `ruff/mypy/pytest`，但 `Makefile` 仍用 `black/isort/flake8`。
- 依赖声明不一致：`pyproject.toml` 用 `libsql-client`，`requirements.txt` 用 `libsql`。
- 运行产物与仓库边界不干净：`data/`、`logs/`、`temp/` 体积较大，且存在被跟踪的副本/`-wal/-shm` 文件。
- 根目录存在临时验证脚本与未跟踪文件，影响项目可维护性和新成员理解成本。

## 二、整理目标（4周）
- 建立“单一事实源”：依赖、命令、文档入口、架构规则各只有一个权威来源。
- 清理运行产物与历史包袱，保证仓库可长期迭代。
- 固化质量门禁（lint/type/test/docs-check）并让 CI 可复现。
- 让新成员在 30 分钟内完成环境启动、一次测试、一次主流程试跑。

## 三、分阶段执行计划

### 第 1 周：基线冻结与结构清洁
- 冻结当前可运行基线，打 `baseline` 标签并记录风险清单。
- 统一仓库边界：清理/归档临时脚本、未跟踪清单文件、`temp/`。
- 修正 `.gitignore` 与已跟踪运行产物（特别是 `data/profiles/.cloud_lookup_replicas`、`.recovery_replicas`）。
- 交付物：`REPO_HYGIENE_REPORT.md`、干净的 `git status`、可重复的最小运行步骤。

### 第 2 周：工程规范统一（依赖+命令+质量门）
- 统一依赖入口（建议只保留 `pyproject.toml` 为主，`requirements.txt` 由其导出或删除）。
- 对齐命令体系：`Makefile` 改为 `ruff format/check + mypy + pytest`。
- 增加 pre-commit 与最小 CI（lint + type + unit smoke）。
- 交付物：统一后的开发命令文档、通过的本地质量门、CI 首次绿灯。

### 第 3 周：测试与稳定性收敛
- 测试分层重整：`unit/integration/experiments` 清晰分区，默认运行不含实验与慢测。
- 把根目录临时验证脚本迁移到 `tools/` 或 `tests/experiments/` 并标注用途/生命周期。
- 补关键模块最小回归集（`database.connection`、`sync_manager`、`study_workflow`）。
- 交付物：测试矩阵文档、稳定回归命令、失败用例处理清单。

### 第 4 周：文档闭环与发布就绪
- 文档去重：`README` 面向使用者，`docs/dev/AI_CONTEXT.md` 面向开发规范，`PROJECT_STATUS.md` 只保留状态。
- 建立“变更影响矩阵”模板（代码改动必须对应文档更新）。
- 完成一次发布彩排（从空环境安装到主流程运行）。
- 交付物：`v1-maintainability` 里程碑、发布检查清单、维护手册。

## 四、优先级任务池（建议按顺序）
1. 清理被跟踪的运行时数据库副本与 WAL/SHM 文件。
2. 统一依赖与构建入口（`pyproject` 为准）。
3. 重写 `Makefile` 与 CI，让命令和实际工具链一致。
4. 规范测试入口与标记，隔离 experiments。
5. 文档索引更新，删除重复/过时说明。
6. 建立“归档区”处理历史脚本，避免根目录继续堆积。

## 五、验收标准（量化）
- `git status` 默认干净；运行后新增产物不进入版本控制。
- 新环境从克隆到 `pytest -m "not slow"` 通过时间 ≤ 30 分钟。
- CI 固定通过 `lint + type + tests`，主分支禁止绕过。
- 文档入口减少到 3 个核心入口，且互不冲突。
- 关键流程（启动、同步、退出）有最小自动化回归覆盖。

## 六、本周启动动作（D1-D3）
1. 建立 `cleanup/plan` 分支，先做“只删不改逻辑”的仓库清洁提交。
2. 处理依赖与命令统一（先改 `Makefile`，再跑一轮质量门）。
3. 提交一版“整理后目录规范”并同步文档索引。
