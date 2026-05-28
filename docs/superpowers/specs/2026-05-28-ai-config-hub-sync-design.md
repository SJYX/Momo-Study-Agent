# AI 配置跨设备同步设计

**日期**：2026-05-28
**状态**：已批准
**范围**：将 AI 配置（provider / API key / model / base_url）从本地 .env 迁移到 Hub 数据库，实现跨设备同步

---

## 1. 背景与动机

当前 AI 配置（`AI_API_KEY`、`AI_MODEL`、`AI_BASE_URL`、`AI_PROVIDER`）存储在本地文件 `data/profiles/<user>.env`，每台设备各有一份，互不通信。用户在设备 A 修改配置后，设备 B 无法感知。

Hub 数据库（`momo-users-hub.db`）已有 `user_credentials` 表，存储加密凭据（turso_db_url、turso_auth_token、momo_token、mimo_api_key、gemini_api_key），具备跨设备同步能力。将 AI 配置纳入同一机制即可实现跨设备同步。

## 2. 设计决策

| 决策项 | 选择 | 理由 |
| --- | --- | --- |
| 读取优先级 | Hub 优先，本地 .env fallback | 云端为准，设备 A 改配置 → Hub 更新 → 设备 B 自动拉到 |
| 存储范围 | 4 字段全量加密存 Hub | 完整配置一键同步，换设备零配置 |
| 向后兼容 | 双写（Hub + 本地 .env） | 旧版 CLI / 离线场景仍能工作 |
| 存储方式 | 扩展 `user_credentials` 表（方案 A） | 复用已有加密/CRUD 模式，改动最小 |

## 3. Schema 变更

`user_credentials` 表新增 4 列，幂等 ALTER TABLE：

```sql
ALTER TABLE user_credentials ADD COLUMN ai_api_key_enc  TEXT;
ALTER TABLE user_credentials ADD COLUMN ai_model_enc    TEXT;
ALTER TABLE user_credentials ADD COLUMN ai_base_url_enc TEXT;
ALTER TABLE user_credentials ADD COLUMN ai_provider_enc TEXT;
```

位置：`database/schema.py` 的 `_init_hub_schema` 和 `init_users_hub_tables`，用 try/except 包裹（与现有 `updated_at` 列迁移方式一致）。

## 4. CRUD 层变更（`database/hub_users.py`）

### 4.1 写入

扩展 `save_user_credentials_to_hub` 的 `field_map`：

```python
field_map = {
    "turso_db_url": "turso_db_url_enc",
    "turso_auth_token": "turso_auth_token_enc",
    "momo_token": "momo_token_enc",
    "mimo_api_key": "mimo_api_key_enc",
    "gemini_api_key": "gemini_api_key_enc",
    # 新增
    "ai_api_key": "ai_api_key_enc",
    "ai_model": "ai_model_enc",
    "ai_base_url": "ai_base_url_enc",
    "ai_provider": "ai_provider_enc",
}
```

同步更新 INSERT OR REPLACE 语句和参数列表。

### 4.2 读取

扩展 `get_user_credentials_from_hub` 的 `decrypt_map`，加上 4 个新字段。

同时修复现有 bug：`mimo_api_key` 和 `gemini_api_key` 的 decrypt_map 值应为 `data.get("mimo_api_key_enc")` 而非字符串 `"mimo_api_key_enc"`。

### 4.3 新增便捷函数

新增 `save_ai_config_to_hub(user_id, ai_config: dict)` 和 `get_ai_config_from_hub(user_id) -> dict`，封装 AI 配置的读写，供 API 层直接调用。

## 5. 数据流

### 5.1 写入流程

```
前端 POST /api/users/{username}/ai-config
  → save_ai_config()
    → save_ai_config_to_hub(user_id, {ai_api_key, ai_model, ai_base_url, ai_provider})
    → _update_profile_env(profile_path, env_updates)  # 保留双写
    → 刷新内存中的 ProfileConfig 缓存
```

### 5.2 读取流程

```
load_profile_config(profile_name)
  → 先读本地 .env（现有逻辑不变）
  → 尝试从 Hub 读 user_credentials（新增）
  → 如果 Hub 有 ai_api_key → 用 Hub 值覆盖 ProfileConfig 对应字段
  → 如果 Hub 没有或不可达 → 用本地 .env 的值（fallback）
```

### 5.3 加密

复用现有 `_encrypt_secret_value` / `_decrypt_secret_value`（CTR 模式 + HMAC-SHA256）。两台设备能互相解密的前提是配置了同一个 `ENCRYPTION_KEY` 环境变量。

## 6. 错误处理

| 场景 | 行为 |
| --- | --- |
| Hub 不可达 / 超时 | `get_user_credentials_from_hub` 返回 None → 走本地 fallback，不报错 |
| `ENCRYPTION_KEY` 未配置 | 跳过 Hub 写入/读取，WARNING 日志，只走本地 .env |
| 首次使用（Hub 无记录） | Hub 返回 None → 用本地 .env → 用户保存时双写 |
| 并发写入 | INSERT OR REPLACE，后写覆盖先写 |

## 7. 测试策略

- **单元测试**：`save_ai_config_to_hub` / `get_ai_config_from_hub` 新字段的加密解密往返
- **集成测试**：双写 → Hub 优先读 → 本地 fallback 完整路径
- **边界测试**：Hub 不可达 fallback、ENCRYPTION_KEY 缺失跳过、Hub 无记录首次保存

## 8. 影响范围

| 文件 | 变更类型 |
| --- | --- |
| `database/schema.py` | ALTER TABLE（4 列） |
| `database/hub_users.py` | 扩展 field_map / decrypt_map + 新增便捷函数 |
| `web/backend/routers/users.py` | save_ai_config 双写 |
| `web/backend/profile_config.py` | load_profile_config 增加 Hub 读取 |
| `tests/unit/database/test_hub_ai_config.py` | 新增测试 |
