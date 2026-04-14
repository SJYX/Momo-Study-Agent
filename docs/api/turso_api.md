# Turso API 速查

> 本文档记录当前已经确认的 Turso 官方 API 参考与本项目的实际使用点。更完整的官方说明以 https://docs.turso.tech 为准。

## 快速索引

- [平台导读](#平台导读)
- [组织与身份](#组织与身份)
- [组织计费与配额](#组织计费与配额)
- [位置与区域](#位置与区域)
- [数据库管理](#数据库管理)
- [组管理](#组管理)
- [成员与邀请](#成员与邀请)
- [审计日志](#审计日志)
- [认证与令牌](#认证与令牌)
- [迁移与同步](#迁移与同步)
- [当前项目用法](#当前项目用法)
- [参考链接](#参考链接)

## 平台导读

### API Introduction

官方定义：Turso Platform API 用于管理组织、成员、组、数据库与 API token，适合平台化数据库创建与运维场景。

范围说明：

- 组织与成员管理
- 组与数据库生命周期管理
- API token 签发和撤销

### Quickstart（官方 7 步）

官方 quickstart 的主路径可以归纳为：

1. 通过 CLI 登录：`turso auth signup`
2. 获取组织 slug：`turso org list`
3. 创建平台 API token：`turso auth api-tokens mint quickstart`
4. 获取可用区域：`GET /v1/locations`
5. 创建组：`POST /v1/organizations/{organizationSlug}/groups`
6. 创建数据库：`POST /v1/organizations/{organizationSlug}/databases`
7. 使用 SDK 连接数据库

对本地镜像的意义：

- quickstart 把 API 调用顺序串联起来，适合作为 onboarding 流程骨架
- 便于对照当前项目配置向导（`core/config_wizard.py`）检查是否缺步骤

## 组织与身份

### List Organizations

返回当前认证用户拥有或加入的组织列表。

请求：

```text
GET /v1/organizations
```

认证：

```text
Authorization: Bearer <token>
```

响应要点：

- `name`：组织名称。个人账号通常是 `personal`。
- `slug`：组织标识。个人账号时，这个值就是用户名。
- `type`：`personal` 或 `team`

示例：

```json
[
  {
    "name": "personal",
    "slug": "iku",
    "type": "personal",
    "overages": false,
    "blocked_reads": false,
    "blocked_writes": false,
    "plan_id": "developer",
    "plan_timeline": "monthly",
    "platform": "vercel"
  }
]
```

### Retrieve Organization

获取单个组织信息。

请求：

```text
GET /v1/organizations/{organizationSlug}
```

### Update Organization

更新组织配置。

请求：

```text
PATCH /v1/organizations/{organizationSlug}
```

用途：

- 修改组织级开关，例如 `overages`
- 只适合管理类脚本，不建议在普通启动路径里调用

这个接口对本项目的意义：

- 便于校验用户配置里填写的 `TURSO_ORG_SLUG`
- 个人账号场景下，`slug` 和用户名一致，适合直接作为默认组织标识

## 组织计费与配额

### Organization Usage

查询组织当前账期的整体用量。

请求：

```text
GET /v1/organizations/{organizationSlug}/usage
```

用途：

- 拉取组织级 rows read/write、存储和同步流量
- 用于配额预警和计费看板

### List Plans

查询组织可用套餐及配额。

请求：

```text
GET /v1/organizations/{organizationSlug}/plans
```

### Current Subscription

查询组织当前订阅信息。

请求：

```text
GET /v1/organizations/{organizationSlug}/subscription
```

### List Invoices

查询组织账单。

请求：

```text
GET /v1/organizations/{organizationSlug}/invoices
```

可选查询参数：

- `type`：`all`、`upcoming`、`issued`

## 位置与区域

### List Locations

返回可创建或复制数据库的区域映射。

请求：

```text
GET /v1/locations
```

### Closest Region

返回调用方就近区域。

请求：

```text
GET https://region.turso.io
```

响应字段：

- `server`
- `client`

## 数据库管理

### Create Database

创建一个新的 Turso 数据库。

请求：

```text
POST /v1/organizations/{organizationSlug}/databases
```

请求头：

```text
Authorization: Bearer <token>
Content-Type: application/json
```

常用请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 数据库名，仅允许小写字母、数字、短横线，最长 64 字符 |
| `group` | string | 是 | 目标分组，必须已存在 |
| `seed` | object | 否 | 预置数据源，可为 `database` 或 `database_upload` |
| `size_limit` | string | 否 | 最大数据库大小，如 `1mb`、`256mb`、`1gb` |
| `remote_encryption` | object | 否 | 远端加密配置 |

示例：

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases' \
  -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "history_asher",
    "group": "default"
  }'
```

### List Databases

列出组织下所有数据库。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases
```

可选查询参数：

- `group`
- `schema`
- `parent`

用途：

- 验证数据库是否已经创建
- 发现当前可用数据库
- 调试组织下的数据库分布

### Retrieve Database

获取单个数据库的元信息。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}
```

用途：

- 检查数据库是否存在
- 获取数据库 ID 和状态

### Retrieve Database Configuration

获取数据库配置详情。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/configuration
```

### Update Database Configuration

更新数据库配置。

请求：

```text
PATCH /v1/organizations/{organizationSlug}/databases/{databaseName}/configuration
```

用途：

- 调整大小上限
- 开关读写阻断
- 设置删除保护

### List Database Instances

列出数据库的实例分布。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/instances
```

用途：

- 查看主实例和副本所在区域
- 排查实例拓扑与连接目标

### Retrieve Database Instance

获取单个实例详情。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/instances/{instanceName}
```

### Retrieve Database Stats

获取数据库统计信息。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/stats
```

用途：

- 查看热点查询
- 观察读写负载

### Retrieve Database Usage

查询数据库在时间范围内的用量。

请求：

```text
GET /v1/organizations/{organizationSlug}/databases/{databaseName}/usage
```

可选查询参数：

- `from`（ISO 8601）
- `to`（ISO 8601）

### Delete Database

删除指定数据库，不可恢复。

请求：

```text
DELETE /v1/organizations/{organizationSlug}/databases/{databaseName}
```

用途：

- 清理测试库
- 重建失败的数据库实例

### Invalidate All Database Auth Tokens

使指定数据库的所有认证令牌失效。

请求：

```text
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/rotate
```

用途：

- 令牌泄露后快速撤销权限
- 切换到新 token 前先清掉旧 token

## 组管理

### List Groups

列出组织下的所有组。

请求：

```text
GET /v1/organizations/{organizationSlug}/groups
```

### Create Group

创建新组。

请求：

```text
POST /v1/organizations/{organizationSlug}/groups
```

常用请求体字段：

- `name`：组名
- `location`：初始区域
- `extensions`：新数据库默认启用的扩展

### Retrieve Group

获取单个组信息。

请求：

```text
GET /v1/organizations/{organizationSlug}/groups/{groupName}
```

### Retrieve Group Configuration

查询组配置。

请求：

```text
GET /v1/organizations/{organizationSlug}/groups/{groupName}/configuration
```

### Update Group Configuration

更新组配置。

请求：

```text
PATCH /v1/organizations/{organizationSlug}/groups/{groupName}/configuration
```

用途：

- 打开或关闭删除保护

### Delete Group

删除组。

请求：

```text
DELETE /v1/organizations/{organizationSlug}/groups/{groupName}
```

### Transfer Group

将组转移到其他组织。

请求：

```text
POST /v1/organizations/{organizationSlug}/groups/{groupName}/transfer
```

用途：

- 组织重组时迁移数据库归属
- 保持既有数据库 URL 和 token 可用，但要尽快更新配置

### Unarchive Group

恢复因长期无活动而归档的组。

请求：

```text
POST /v1/organizations/{organizationSlug}/groups/{groupName}/unarchive
```

### Create Group Auth Token

为指定组生成授权 token。

请求：

```text
POST /v1/organizations/{organizationSlug}/groups/{groupName}/auth/tokens
```

查询参数：

- `expiration`
- `authorization`

### Invalidate Group Auth Tokens

使组的授权 token 失效。

请求：

```text
POST /v1/organizations/{organizationSlug}/groups/{groupName}/auth/rotate
```

## 成员与邀请

### Get Current User

获取当前认证用户信息。

请求：

```text
GET /v1/user
```

用途：

- 校验当前 token 对应的身份
- 获取用户名、邮箱和 plan 信息

### List Members

列出组织成员。

请求：

```text
GET /v1/organizations/{organizationSlug}/members
```

### Add Member

向组织添加已注册 Turso 用户。

请求：

```text
POST /v1/organizations/{organizationSlug}/members
```

请求体字段：

- `username`
- `role`：`admin`、`member`、`viewer`

### Retrieve Member

获取单个成员信息。

请求：

```text
GET /v1/organizations/{organizationSlug}/members/{username}
```

### Remove Member

按用户名移除成员。

请求：

```text
DELETE /v1/organizations/{organizationSlug}/members/{username}
```

### Update Member Role

更新成员角色。

请求：

```text
PATCH /v1/organizations/{organizationSlug}/members/{username}
```

请求体字段：

- `role`：`admin`、`member`、`viewer`

### List Invites

列出组织邀请。

请求：

```text
GET /v1/organizations/{organizationSlug}/invites
```

### Create Invite

创建组织邀请。

请求：

```text
POST /v1/organizations/{organizationSlug}/invites
```

请求体字段：

- `email`
- `role`

说明：

- 适用于邀请尚未注册 Turso 的用户
- 官方文档提示已注册用户应使用成员添加流程

### Delete Invite (v1)

按邮箱删除邀请。

请求：

```text
DELETE /v1/organizations/{organizationSlug}/invites/{email}
```

### List Invites (v2)

列出待处理邀请（v2）。

请求：

```text
GET /v2/organizations/{organizationSlug}/invites
```

### Create Invite (v2)

创建邀请（v2）。

请求：

```text
POST /v2/organizations/{organizationSlug}/invites
```

说明：

- 若同邮箱有 pending invite，会被新邀请替换

### Delete Invite (v2)

删除待处理邀请（v2）。

请求：

```text
DELETE /v2/organizations/{organizationSlug}/invites/{email}
```

## 审计日志

### List Audit Logs

列出组织审计日志（按 `created_at` 倒序）。

请求：

```text
GET /v1/organizations/{organizationSlug}/audit-logs
```

可选查询参数：

- `page`
- `page_size`

说明：

- 官方提示该能力受套餐限制（付费计划可用）

## 认证与令牌

### Generate Database Auth Token

为指定数据库生成认证令牌，供 `libsql.connect(url, auth_token=...)` 连接使用。

请求：

```text
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens
```

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `expiration` | string | `never` | 过期时间，例如 `2w1d30m` |
| `authorization` | string | `full-access` | 权限级别：`full-access` 或 `read-only` |

请求体可选字段：

```json
{
  "permissions": {
    "read_attach": {
      "databases": ["db_name1", "db_name2"]
    }
  }
}
```

示例：

```bash
curl -L -X POST 'https://api.turso.tech/v1/organizations/{organizationSlug}/databases/{databaseName}/auth/tokens?expiration=2w&authorization=full-access' \
  -H 'Authorization: Bearer TOKEN'
```

### Create API Token

创建用户级 API Token。

请求：

```text
POST /v1/auth/api-tokens/{tokenName}
```

兼容说明：

- 旧版文档和脚本常见 `POST /v1/api-tokens`
- 新版 API 参考主路径是 `/v1/auth/api-tokens/{tokenName}`

示例请求体：

```json
{
  "name": "my-token",
  "organization": "organizationSlug"
}
```

用途：

- 自动化脚本访问 Turso API
- 为不同环境隔离权限

### Validate API Token

验证 API Token 是否有效。

请求：

```text
GET /v1/auth/validate
```

用途：

- 启动前验证 `TURSO_AUTH_TOKEN`
- 做配置自检和健康检查

### List API Tokens

列出当前用户的 API token。

请求：

```text
GET /v1/auth/api-tokens
```

### Revoke API Token

撤销指定 API token。

请求：

```text
DELETE /v1/auth/api-tokens/{tokenName}
```

## 迁移与同步

### Upload Database

将本地 SQLite 数据库上传为 Turso 数据源。

请求：

```text
POST /v1/organizations/{organizationSlug}/databases/{databaseName}/upload
```

用途：

- 迁移现有本地 SQLite 到 Turso
- 作为新数据库的种子数据源

### Turso Sync

官方当前更推荐的本地优先同步方向是 Turso Sync，而不是继续把嵌入式副本当作新项目首选。

核心概念：

- 本地数据库文件路径
- 远端数据库 URL
- 认证 token
- 显式 `push()` / `pull()` 同步
- 可用 `stats()`、`checkpoint()` 做状态观察和检查点控制

对本项目的含义：

- 当前代码仍然采用本地 SQLite + Turso 云端双轨模式
- 如果后续要做更底层的同步重构，Turso Sync 比嵌入式副本更值得优先评估

### Embedded Replicas

嵌入式副本文档当前属于旧路线，适合了解历史方案，不建议作为新项目默认实现。

建议：

- 新项目优先看 Turso Sync
- 只有在明确需要兼容旧架构时，再考虑 embedded replicas 的实现细节

## 当前项目用法

### 新用户创建数据库

`core/config_wizard.py` 会在新用户初始化阶段调用 `Create Database`，为用户创建个人数据库，并把结果写入对应 `.env` 文件。

### 中央 Hub

项目里还有一个共享的中央 Hub 数据库，用于存储用户元数据、统计、审计与同步记录。

### 当前环境变量

新用户配置通常会包含：

```text
TURSO_ORG_SLUG
TURSO_DB_NAME
TURSO_DB_HOSTNAME
TURSO_DB_URL
TURSO_AUTH_TOKEN
```

### 运行时行为

1. 启动时加载用户配置
2. 如果有 `TURSO_DB_URL` 和 `TURSO_AUTH_TOKEN`，优先连接 Turso 云端
3. 否则回退到本地 SQLite
4. 双向同步仅在 Turso 连接可用时执行

### 当前实现注意点

- 如果只提供 `TURSO_DB_HOSTNAME`，项目会自动补全成 `https://{hostname}`
- 当前配置向导只处理基础创建流程，不会自动展开复杂的 `seed` 或 `remote_encryption` 场景
- 个人账号场景下，组织 `slug` 通常就是用户名

### 已确认的官方镜像范围

当前本地速查已经覆盖以下已确认页面：

- 组织：list / retrieve / update / usage / plans / subscription / invoices
- 用户：get current
- 位置：list / closest-region
- 组：list / create / retrieve / configuration / update-configuration / delete / transfer / unarchive / auth token / auth rotate
- 成员：list / add / retrieve / update / remove
- 邀请：list / create / delete / list-v2 / create-v2 / delete-v2
- 数据库：create / list / retrieve / configuration / update configuration / instances / retrieve-instance / usage / stats / delete / auth token / auth rotate / upload
- 审计：audit logs list
- API token：create / list / validate / revoke

### 官方 sitemap 覆盖清单（API Reference）

以下清单来自官方 `sitemap.xml` 的 `/api-reference/*` 路径：

- `/api-reference/audit-logs/list`：已镜像
- `/api-reference/authentication`：已镜像
- `/api-reference/databases/configuration`：已镜像
- `/api-reference/databases/create`：已镜像
- `/api-reference/databases/create-token`：已镜像
- `/api-reference/databases/delete`：已镜像
- `/api-reference/databases/invalidate-tokens`：已镜像
- `/api-reference/databases/list`：已镜像
- `/api-reference/databases/list-instances`：已镜像
- `/api-reference/databases/retrieve`：已镜像
- `/api-reference/databases/retrieve-instance`：已镜像
- `/api-reference/databases/stats`：已镜像
- `/api-reference/databases/update-configuration`：已镜像
- `/api-reference/databases/upload`：已镜像
- `/api-reference/databases/usage`：已镜像
- `/api-reference/groups/configuration`：已镜像
- `/api-reference/groups/create`：已镜像
- `/api-reference/groups/create-token`：已镜像
- `/api-reference/groups/delete`：已镜像
- `/api-reference/groups/invalidate-tokens`：已镜像
- `/api-reference/groups/list`：已镜像
- `/api-reference/groups/retrieve`：已镜像
- `/api-reference/groups/transfer`：已镜像
- `/api-reference/groups/unarchive`：已镜像
- `/api-reference/groups/update-configuration`：已镜像
- `/api-reference/introduction`：已镜像
- `/api-reference/locations/closest-region`：已镜像
- `/api-reference/locations/list`：已镜像
- `/api-reference/organizations/invites/create`：已镜像
- `/api-reference/organizations/invites/create-v2`：已镜像
- `/api-reference/organizations/invites/delete`：已镜像
- `/api-reference/organizations/invites/delete-v2`：已镜像
- `/api-reference/organizations/invites/list`：已镜像
- `/api-reference/organizations/invites/list-v2`：已镜像
- `/api-reference/organizations/invoices`：已镜像
- `/api-reference/organizations/list`：已镜像
- `/api-reference/organizations/members/add`：已镜像
- `/api-reference/organizations/members/list`：已镜像
- `/api-reference/organizations/members/remove`：已镜像
- `/api-reference/organizations/members/retrieve`：已镜像
- `/api-reference/organizations/members/update`：已镜像
- `/api-reference/organizations/plans`：已镜像
- `/api-reference/organizations/retrieve`：已镜像
- `/api-reference/organizations/subscription`：已镜像
- `/api-reference/organizations/update`：已镜像
- `/api-reference/organizations/usage`：已镜像
- `/api-reference/quickstart`：已镜像
- `/api-reference/response-codes`：已镜像
- `/api-reference/tokens/create`：已镜像
- `/api-reference/tokens/list`：已镜像
- `/api-reference/tokens/revoke`：已镜像
- `/api-reference/tokens/validate`：已镜像
- `/api-reference/user/get-current`：已镜像

## 参考链接

- [Turso API Reference](https://docs.turso.tech/api-reference/)
- [Turso Introduction](https://docs.turso.tech/api-reference/introduction)
- [Turso Quickstart](https://docs.turso.tech/api-reference/quickstart)
- [Turso Organizations List](https://docs.turso.tech/api-reference/organizations/list)
- [Turso User](https://docs.turso.tech/api-reference/user/get-current)
- [Turso Audit Logs](https://docs.turso.tech/api-reference/audit-logs/list)
- [Turso Groups](https://docs.turso.tech/api-reference/groups/list)
- [Turso Databases](https://docs.turso.tech/api-reference/databases/list)
- [Turso Tokens](https://docs.turso.tech/api-reference/tokens/list)
- [Turso Sync](https://docs.turso.tech/usage/sync)
- [Turso Authentication](https://docs.turso.tech/api-reference/authentication)
