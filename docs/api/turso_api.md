# Turso API 速查

> **Turso Platform API** 文档。需要详细信息请访问 https://docs.turso.tech/api-reference/

---

## 目录

- [核心操作](#核心操作)
  - 1. Create Database
  - 2. Generate Database Auth Token
- [数据库管理](#数据库管理)
  - 3. List Databases
  - 4. Retrieve Database
  - 5. Delete Database
- [配置与令牌](#配置与令牌)
  - 6. Retrieve Database Configuration
  - 7. Invalidate All Database Auth Tokens
  - 8. Create API Token
  - 9. Validate API Token
- [数据迁移](#数据迁移)
  - 10. Upload Database
- [项目说明](#项目说明)

---

## 核心操作

### 1. Create Database

创建一个新的 Turso 数据库。

**请求**

```
POST /v1/organizations/{organizationSlug}/databases
```

**请求头**

```
Authorization: Bearer TOKEN
Content-Type: application/json
```

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 数据库名，仅允许小写字母、数字、短横线，最长 64 字符 |
| `group` | string | ✓ | 目标分组名称（必须已存在） |
| `seed` | object |  | 数据库源，type 可为 `database` 或 `database_upload` |
| `size_limit` | string |  | 最大数据库大小，如 `1mb`、`256mb`、`1gb` |
| `remote_encryption` | object |  | 加密配置，包含 `encryption_key` 和 `encryption_cipher` |

**示例**

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases' \
  -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
      "name": "history_asher",
      "group": "default"
  }'
```

**响应**

```json
{
  "database": {
    "DbId": "f5655623-c30f-484b-881c-b80b4cb89ec8",
    "Hostname": "5d18f3ce-a5d7-4a93-9bde-c736c3f4c081",
    "Name": "history_asher"
  }
}
```

**错误**

| 代码 | 说明 |
|------|------|
| 400 | 请求字段不合法或 `group` 不存在 |
| 409 | 数据库名已存在 |

---

### 2. Generate Database Auth Token

为指定数据库生成认证令牌。用于 `libsql.connect(url, auth_token=...)` 连接。

**请求**

```
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens
```

**查询参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `expiration` | string | `never` | 过期时间格式，如 `2w1d30m`（2 周 1 天 30 分钟） |
| `authorization` | string | `full-access` | 权限级别：`full-access` 或 `read-only` |

**请求头**

```
Authorization: Bearer TOKEN
```

**请求体（可选）**

```json
{
  "permissions": {
    "read_attach": {
      "databases": ["db_name1", "db_name2"]
    }
  }
}
```

**示例**

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens?expiration=2w&authorization=full-access' \
  -H 'Authorization: Bearer TOKEN'
```

**响应**

```json
{
  "jwt": "eyJhbGc..."
}
```

**错误**

| 代码 | 说明 |
|------|------|
| 400 | `expiration` 格式错误 |
| 404 | 数据库不存在 |

---

## 数据库管理

### 3. List Databases

列出指定组织的所有数据库。

**请求**

```
GET /v1/organizations/{organizationSlug}/databases
```

**用途**

- 验证新数据库是否已创建
- 发现当前可用数据库
- 为同步操作提供数据库列表

---

### 4. Retrieve Database

获取单个数据库的元信息。

**请求**

```
GET /v1/organizations/{organizationSlug}/databases/{databaseName}
```

**用途**

- 检查数据库是否存在
- 获取数据库 ID 及状态
- 验证数据库所属组

---

### 5. Delete Database

删除指定数据库（不可恢复）。

**请求**

```
DELETE /v1/organizations/{organizationSlug}/databases/{databaseName}
```

**用途**

- 清理测试数据库
- 重新创建失败的数据库实例

---

## 配置与令牌

### 6. Retrieve Database Configuration

获取数据库配置详情。

**请求**

```
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/configuration
```

**用途**

- 验证数据库所在分组与区域
- 检查大小限制与其他配置

---

### 7. Invalidate All Database Auth Tokens

使指定数据库的所有令牌失效。

**请求**

```
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens/invalidate
```

**用途**

- 令牌泄露时撤销所有权限
- 强制用户重新生成新令牌

---

### 8. Create API Token

生成用户级 API Token（多重组织支持）。

**请求**

```
POST /v1/api-tokens
```

**请求体**

```json
{
  "name": "my-token",
  "organization": "organizationSlug"
}
```

**用途**

- 通过脚本或 CLI 访问 Turso API
- 为不同环境创建隔离 Token

---

### 9. Validate API Token

验证 API Token 有效性。

**请求**

```
POST /v1/api-tokens/validate
```

**用途**

- 启动前验证 `TURSO_AUTH_TOKEN` 有效性
- 自动化配置检查

---

## 数据迁移

### 10. Upload Database

将本地 SQLite 数据库上传为 Turso 数据库源。

**请求**

```
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/upload
```

**用途**

- 迁移现有本地 SQLite 数据库到 Turso
- 缩短新数据库初始化时间（作为 `seed`）

---

## 项目说明

### 当前使用

- **创建个人数据库**：`core/config_wizard.py` 中新用户初始化时调用 API #1
- **创建中央库**：手动在 Turso 上创建 `momo_users_hub` 数据库（一次性），用来存储所有用户元数据
- **生成令牌**：自动从 API #2 响应的 Hostname 和 Token 中获取

### 中央库（momo_users_hub）

全局共用数据库，记录所有用户信息：

| 表名 | 说明 |
|------|------|
| `users` | 用户基本信息（用户名、AI Provider、创建时间等） |
| `user_api_keys` | API Key 存储（Fernet 加密） |
| `user_sync_history` | 数据同步记录 |
| `user_stats` | 学习统计数据 |
| `user_sessions` | 用户会话追踪（IP、客户端信息） |
| `admin_logs` | 管理员操作日志 |

**使用场景**：
- 用户管理与统计
- 跨用户数据查询
- 安全审计日志
- 系统监控


### 配置字段

新用户的 `data/profiles/{username}.env` 会包含：

```bash
TURSO_ORG_SLUG="my-org"          # 组织标识
TURSO_DB_NAME="history_asher"    # 数据库名
TURSO_DB_HOSTNAME="xxx.turso.io" # 数据库主机名（来自 API #1 响应）
TURSO_DB_URL="https://xxx.turso.io"  # 标准化 URL（自动补全）
TURSO_AUTH_TOKEN="..."           # JWT 令牌（来自 API #2 响应）
```

### 运行时行为

1. 启动时加载用户 `.env`
2. `_get_conn()` 自动路由：
   - 如果提供 `TURSO_DB_URL` + `TURSO_AUTH_TOKEN`，连接到云端（libSQL）
   - 否则回退到本地 SQLite
3. 双向同步仅在 Turso 连接可用时执行

---

## 更多资源

- [Turso 官方 API 文档](https://docs.turso.tech/api-reference/)
- [libSQL Python 客户端](https://docs.turso.tech/sdk/python/quickstart.md)
- [Authentication](https://docs.turso.tech/api-reference/authentication.md)

创建一个新的 Turso 数据库。

### 请求

POST /v1/organizations/{organizationSlug}/databases

### 请求头

- Authorization: Bearer TOKEN
- Content-Type: application/json

### 请求体字段

- `name` (string, required)
  - 新数据库名称
  - 仅允许小写字母、数字、短横线
  - 最长 64 个字符
- `group` (string, required)
  - 目标分组名称
  - 必须已存在
- `seed` (object, optional)
  - `type`: `database` 或 `database_upload`
  - `name`: 当 type 为 `database` 时，表示要复制的数据库名
  - `timestamp`: ISO 8601 格式的恢复点时间
- `size_limit` (string, optional)
  - 最大数据库大小，支持带单位值，如 `1mb`、`256mb`、`1gb`
- `remote_encryption` (object, optional)
  - `encryption_key`: Base64 编码的加密密钥
  - `encryption_cipher`: 加密算法，如 `aes256gcm`、`aes128gcm`、`chacha20poly1305`、`aegis128l`、`aegis128x2`、`aegis128x4`、`aegis256`、`aegis256x2`、`aegis256x4`

### 示例请求

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases' \
  -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
      "name": "new-database",
      "group": "default"
  }'
```

### 返回

成功返回 JSON 对象，包含 `database` 字段。

```json
{
  "database": {
    "DbId": "f5655623-c30f-484b-881c-b80b4cb89ec8",
    "Hostname": "5d18f3ce-a5d7-4a93-9bde-c736c3f4c081",
    "Name": "57a53a41-8fc6-4cb6-814b-8205ec348d0c"
  }
}
```

### 常见错误

- `400 Bad Request`
  - 请求体字段不合法
  - `group` 不存在
- `409 Conflict`
  - 名称已存在

## 2. Generate Database Auth Token

为指定数据库生成一次性认证令牌，用于授权后续连接或操作。

### 请求

POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens

### 请求参数

- `expiration` (query, string, optional)
  - 令牌过期时间，例如 `2w1d30m`
  - 默认：`never`
- `authorization` (query, string, optional)
  - 令牌权限级别
  - 可选值：`full-access`、`read-only`
  - 默认：`full-access`

### 请求头

- Authorization: Bearer TOKEN
- Content-Type: application/json

### 请求体字段

- `permissions` (object, optional)
  - `read_attach` (object, optional)
    - `databases` (array[string])
      - 允许该令牌执行 ATTACH 操作的数据库列表

### 示例请求

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens?expiration=2w&authorization=full-access' \
  -H 'Authorization: Bearer TOKEN'
```

### 返回

成功返回 JSON 对象，包含 `jwt` 字段。

```json
{
  "jwt": "TOKEN"
}
```

### 常见错误

- `400 Bad Request`
  - `expiration` 格式不正确
  - 请求体字段不合法
- `404 Not Found`
  - 指定数据库不存在

## 3. List Databases

列出组织或用户下的数据库。

### 请求

GET /v1/organizations/{organizationSlug}/databases

### 用途

- 验证新数据库是否已创建
- 发现当前可用数据库名
- 为同步或管理操作提供数据库列表

## 4. Retrieve Database

获取单个数据库的元信息。

### 请求

GET /v1/organizations/{organizationSlug}/databases/{databaseName}

### 用途

- 检查数据库是否存在
- 获取数据库名称、ID 及状态

## 5. Retrieve Database Configuration

获取数据库配置详情。

### 请求

GET /v1/organizations/{organizationSlug}/databases/{databaseName}/configuration

### 用途

- 验证数据库所在组与区域配置
- 检查当前数据库大小限制与其他配置项

## 6. Delete Database

删除指定数据库。

### 请求

DELETE /v1/organizations/{organizationSlug}/databases/{databaseName}

### 用途

- 清理测试数据库
- 重新创建失败的数据库实例

## 7. Invalidate All Database Auth Tokens

使指定数据库的所有授权令牌失效。

### 请求

POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens/invalidate

### 用途

- 当发现令牌泄露或权限错误时强制撤销
- 保护数据库访问安全

## 8. Upload Database

将本地 SQLite 数据库上传为 Turso 数据库源。

### 请求

POST /v1/organizations/{organizationSlug}/databases/{databaseName}/upload

### 用途

- 迁移现有本地 SQLite 数据库到 Turso
- 缩短新数据库初始化时间

## 9. Create API Token

生成用户级 API Token，可选限制到特定组织。

### 请求

POST /v1/api-tokens

### 用途

- 通过脚本或 CLI 访问 Turso API
- 为项目中不同环境创建隔离 Token

## 10. Validate API Token

验证当前 API Token 是否有效。

### 请求

POST /v1/api-tokens/validate

### 用途

- 确认 `TURSO_AUTH_TOKEN` 有效
- 在配置加载时做自检

## 11. 项目中使用方式

- 当前实现：`core/config_wizard.py` 可选调用 `Create Database` 接口为新用户创建数据库
- 建议存储字段：
  - `TURSO_ORG_SLUG`
  - `TURSO_DB_NAME`
  - `TURSO_DB_HOSTNAME`
  - `TURSO_DB_URL`
  - `TURSO_AUTH_TOKEN`

## 12. 说明

- 如果系统只提供 `TURSO_DB_HOSTNAME`，项目会自动补全为 `https://{hostname}`。
- `TURSO_AUTH_TOKEN` 必须与 Turso API 调用保持一致，用于 `libsql.connect(url, auth_token=...)`。
- 当前用户配置向导暂时只实现基础创建，不会自动处理 `seed` 或 `remote_encryption` 的复杂场景。
