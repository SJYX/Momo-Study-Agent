# 开源转向实施计划（去加密管理，用户自配凭证）

## 目标

- 项目面向开源用户发布，不再负责托管或分发任何真实凭证。
- 用户自行提供并管理自己的 AI 与 Turso 凭证。
- 默认配置路径清晰、可复现、10 分钟内可跑通。

## 非目标

- 不再提供“管理员代建数据库 + 分发加密凭证”的主流程。
- 不追求保留旧版加密链路的长期兼容（仅保留短期迁移窗口）。

## 分阶段执行

### Phase 1：配置与入口去加密化（优先）

- 在配置加载中将明文环境变量作为唯一主路径。
- 将 `TURSO_AUTH_TOKEN_ENC` 标记为弃用（可选保留一次兼容提醒）。
- 新用户向导改为只写入明文 `TURSO_AUTH_TOKEN`，不再写 `TURSO_AUTH_TOKEN_ENC`。
- 保留现有多用户 profile 结构，但每个用户自行填写/维护自己的凭证。

验收标准：
- 新用户仅通过 `.env.example` + `data/profiles/<user>.env` 即可启动。
- 启动不再依赖 `core/secret_store.py` 才能完成主流程。

### Phase 2：功能降级与脚本整理

- 将离线引导与自动代建数据库相关逻辑改为可选或移除。
- 标记脚本状态（active/legacy/deprecated），避免误导开源用户。
- 清理 README 中“企业级加密/管理员代建”的默认叙述。

验收标准：
- 主文档不再暗示项目会提供管理员凭证。
- 仅保留与“用户自配凭证”一致的入口与说明。

### Phase 3：安全与发布治理

- 发布前执行凭证泄露扫描（工作树与历史）。
- 完善 `.gitignore` 与贡献规范中的安全条款。
- 发布迁移说明：旧字段弃用、新字段替代、回滚方式。

验收标准：
- 仓库无真实 key/token。
- 文档包含最小可运行示例与常见故障排查。

## 建议的行为变更（待确认）

- `FORCE_CLOUD_MODE` 默认值改为 `False`（更适合开源初次体验）。
- `run_setup()` 去掉额外门禁输入，聚焦凭证配置。
- 删除或下线离线加密引导脚本默认入口。

## 风险与回滚

- 风险：旧用户仅有 `TURSO_AUTH_TOKEN_ENC` 时，直接移除解密会导致启动失败。
- 缓解：保留 1 个版本的兼容读取并打印弃用警告。
- 回滚：保留单独分支，必要时恢复 `secret_store` 读取逻辑。

## 执行顺序（本仓库）

1. 配置层：`config.py`
2. 向导层：`core/config_wizard.py`
3. 文档层：`README.md`、`.env.example`、`docs/dev/CONTRIBUTING.md`
4. 脚本层：`scripts/generate_offline_bootstrap_bundle.py`、`scripts/redeem_offline_bootstrap_bundle.py`
5. 验证：`python -m py_compile` + 启动 smoke test

## 当前状态

- [x] 迁移计划文档已创建
- [x] 关键分歧项确认
- [x] Phase 1 代码改造
- [x] 文档更新
- [x] 验证与总结
