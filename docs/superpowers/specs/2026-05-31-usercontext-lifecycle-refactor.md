# UserContext 生命周期重构

> 日期：2026-05-31
> 状态：Approved

## 问题

`save_ai_config` 保存 AI 配置时调用 `cleanup(username)` 销毁整个 UserContext（含 DB 连接、同步协调器），导致：
1. 下一个请求触发 `_create_context()` 全量重建
2. `init_db()` → `turso.sync.connect()` 重新连接数据库
3. 同步协调器被 shutdown + 重建
4. 不必要的 DB 重连开销

根因：`_create_context()` 混合了两种不同生命周期的资源（DB 基础设施 vs AI 业务组件），AI 配置变更触发全量重建。

## 方案

`_create_context` 拆成两阶段：
1. `_ensure_db_infrastructure(ctx)` — DB 连接 + 同步协调器，幂等（已存在则跳过）
2. `_build_ai_components(ctx)` — AI client + workflow，可独立重建

`save_ai_config` 调用新增的 `refresh_ai(profile_name)` 方法，只重建 AI 组件，不动 DB。

## 改动文件

| 文件 | 改动 |
|---|---|
| `web/backend/user_context.py` | 拆分 `_create_context`；加 `refresh_ai()` |
| `web/backend/routers/users.py` | `save_ai_config` 调 `refresh_ai()` 替代 `cleanup()` |
| `database/schema.py` | `init_db` 加幂等检查 |
