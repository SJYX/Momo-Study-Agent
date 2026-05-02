# C01 首页与导航策略（默认 Ops Monitor）

状态：confirmed  
更新时间：2026-05-02

## 1. 章节目标

明确默认首页、首次进入路径、导航分层、跨页跳转与回退策略，确保“监控先看，执行高效”。

## 2. 已确认输入

1. 默认首页应为 `Ops Monitor`。
2. `Today Command Center` 是主执行入口。
3. 整体采用 A+ 双轨：监控台 + 执行台。
4. 无 active profile 的新用户先进入 `UserGateway`。

## 3. 定稿决策

1. 全局入口：
   - 有 active profile：默认进入 `Ops Monitor`
   - 无 active profile：先进入 `UserGateway`
2. Ops Monitor 首屏优先级：`任务态势 > 失败热区 > 系统健康 > 队列延迟`
3. Ops->Today 主 CTA：首屏右上固定，文案 `进入 Today 执行`
4. 顶部导航：不允许自定义默认二级落点，统一固定
5. 返回策略：优先回来源页；无来源时回 `Ops Monitor`
6. 最近访问：启用快速入口，显示最近 3 个页面

## 4. 章节计划（可执行）

1. 路由与入口守卫
   - 固化默认首页路由为 `Ops Monitor`
   - 无 active profile 强制转 `UserGateway`
2. Ops 首页首屏布局
   - 按定稿优先级布局 4 大监控块
   - 放置固定主 CTA（进入 Today 执行）
3. 来源回退机制
   - 路由状态记录来源页
   - 无来源统一回 Ops
4. 最近访问实现
   - 维护最近访问 3 项
   - 提供点击直达并去重更新
5. 验证
   - 功能：入口、跳转、回退、最近访问
   - 回归：不破坏 profile 守卫与现有导航

## 5. 验收标准

1. 有 active profile 时，打开即进 Ops Monitor。
2. 无 active profile 时，打开即进 UserGateway。
3. Ops 首屏首屏信息顺序与定稿一致。
4. 右上主按钮始终可见并可直达 Today。
5. 业务页返回遵循“来源优先，无来源回 Ops”。
6. 最近访问入口稳定显示 3 项且可跳转。

## 6. 风险与回退

1. 风险：默认首页从 Today 改为 Ops 可能增加一次点击。
   - 处置：固定主 CTA + 最近访问降低跳转成本。
2. 风险：来源回退链路丢失。
   - 处置：无来源兜底回 Ops，避免死链。
3. 风险：最近访问状态污染。
   - 处置：按 profile 维度隔离最近访问缓存。

## 7. 关联文档

1. `docs/dev/web_ui/WEB_UI_EXEC_PLAN.md`
2. `docs/dev/web_ui/WEB_UI_INTERACTION_PATHS.md`
3. `docs/dev/web_ui/chapters/CHANGELOG.md`
