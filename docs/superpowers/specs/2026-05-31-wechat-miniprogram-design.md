# 微信小程序 MVP 设计文档

> 日期：2026-05-31
> 状态：Draft — 待用户确认

## 1. 产品定位

MOMO Study Agent 的微信小程序版本，与现有 Web 前端并存（独立分支/仓库开发）。

- **定位**：移动端轻量版，覆盖核心学习流程
- **不替代**：Web 端的运维监控、高级配置、多用户管理等功能
- **首期范围**：今日任务（AI 生成 + 墨墨推送）+ 墨墨同步

## 2. 技术方案

| 维度 | 选择 |
|------|------|
| 前端框架 | 微信原生（WXML + WXSS + TypeScript） |
| 后端 | 微信云开发（云函数 + 云数据库） |
| 数据库 | 微信云数据库（MongoDB-like NoSQL） |
| 用户识别 | 微信 openid 自动关联 |
| AI 接入 | 多 provider（DeepSeek / Gemini / OpenAI 等），云函数直接 HTTP 调用 |
| 项目位置 | 当前仓库 `miniprogram/` 子目录 |

选择原生小程序的理由：
- 性能最优，包体积最小
- 微信 API（登录、订阅消息）原生支持，零兼容问题
- 云开发一体化，`wx.cloud` 开箱即用
- 首期只有 2 个功能模块，不需要跨端框架

## 3. 项目结构

```
miniprogram/
├── cloudfunctions/
│   ├── user-init/              # 用户初始化（openid 自动注册）
│   ├── today-tasks/            # 今日任务查询
│   ├── ai-generate-and-push/   # AI 生成 + 推送墨墨（一步完成）
│   ├── momo-sync/              # 墨墨数据同步
│   └── word-ops/               # 单词搜索/详情
├── miniprogram/
│   ├── pages/
│   │   ├── today/              # 今日任务页（Tab 1 / 首页）
│   │   ├── sync-log/           # 同步记录页（二级页面）
│   │   ├── settings/           # 设置页（Tab 2）
│   │   └── index/              # 入口（tabBar 容器）
│   ├── components/
│   │   ├── word-card/          # 单词卡片（展开查看 AI 内容）
│   │   ├── word-item/          # 单词列表行
│   │   └── sync-badge/         # 同步状态徽标
│   ├── services/
│   │   ├── cloud.js            # 云函数调用封装
│   │   └── auth.js             # openid 获取与用户初始化
│   ├── app.js / app.json / app.wxss
│   └── utils/
│       └── format.js
├── project.config.json
└── cloudfunctions/package.json
```

## 4. 云函数设计

| 云函数 | 触发方式 | 职责 | 外部 API 调用 |
|--------|----------|------|---------------|
| `user-init` | 进入小程序自动调用 | 查/建 users 记录，返回用户配置状态 | 无 |
| `today-tasks` | 进入今日页 / 下拉刷新 | 查墨墨 API 获取今日复习词表，写入/更新 today_tasks 集合 | 墨墨 API |
| `ai-generate-and-push` | 点击「开始处理」 | AI 生成助记内容 → 写入 words → 调用墨墨 Notes API 推送 | AI Provider + 墨墨 API |
| `momo-sync` | 点击「同步」按钮 | 拉取墨墨词汇全量数据，批量 upsert 到 words，写 sync_logs | 墨墨 API |
| `word-ops` | 点击单词查看详情 | 查询 words 集合返回 AI 内容 | 无 |

### ai-generate-and-push 详细流程

```
输入: { word, provider?, force_regenerate? }
    ↓
1. 查 words 集合，已有 ai_content 且未 force → 跳过生成
2. 读取用户配置（ai_provider, ai_api_key, ai_model）
3. 调用 AI HTTP API 生成内容（词根/例句/助记/记忆技巧）
4. 写入 words.ai_content
5. 调用墨墨 create_note / update_note 推送助记
6. 更新 words.sync_status = 'synced'
    ↓
返回: { ok: true, data: { word, ai_content, note_id } }
```

此云函数将 Python 端 `core/study_workflow.py` 中的 `_process_results` 逻辑移植为 Node.js 实现。

## 5. 云数据库 Schema

### users 集合

```javascript
{
  _openid: "oXXXXXXX",           // 微信自动注入
  nickname: "用户昵称",
  avatar_url: "https://...",
  momo_token: "encrypted",       // 墨墨 API token（AES 加密）
  ai_provider: "deepseek",       // 默认 AI provider
  ai_api_key: "encrypted",       // AI API key（AES 加密）
  ai_model: "deepseek-chat",
  created_at: Date,
  updated_at: Date
}
// 索引: _openid (唯一，微信自动创建)
```

### words 集合

```javascript
{
  _openid: "oXXXXXXX",
  word: "abandon",
  phonetic: "/əˈbændən/",
  meaning_cn: "放弃；抛弃",
  momo_voc_id: "v_12345",        // 墨墨词汇 ID
  momo_data: {
    spell: 2,
    meaning: 1,
    familiar: 3,
    rating: 4
  },
  ai_content: {
    etymology: "ab- (away) + -don (give) → 放弃",
    memory_tips: "联想：一个 band（乐队）被 abandon（抛弃）",
    example_sentence: "He had to abandon his plan.",
    mnemonics: "谐音：啊笨蛋 → 笨蛋被放弃了"
  },
  momo_note_id: "n_67890",       // 墨墨助记 ID（推送后返回）
  sync_status: "synced",         // synced | local_ready | failed
  last_sync_at: Date,
  created_at: Date,
  updated_at: Date
}
// 索引: { _openid: 1, word: 1 } (复合唯一)
```

### today_tasks 集合

```javascript
{
  _openid: "oXXXXXXX",
  date: "2026-05-31",
  words: ["abandon", "brevity", "catalyst"],
  processed_words: ["abandon"],   // 已处理（AI生成+推送）
  created_at: Date
}
// 索引: { _openid: 1, date: 1 } (复合唯一)
```

### sync_logs 集合

```javascript
{
  _openid: "oXXXXXXX",
  started_at: Date,
  finished_at: Date,
  status: "success",              // success | failed
  words_synced: 150,
  words_failed: 0,
  error_msg: null
}
// 索引: { _openid: 1, started_at: -1 }
```

## 6. 前端页面设计

### Tab 1：今日任务

```
┌─────────────────────────────┐
│ 今日任务            [同步]  │
│ 2026-05-31 · 15 词待处理    │
├─────────────────────────────┤
│ ○ abandon        [开始处理] │
│   展开：词根/例句/助记      │  ← 已生成可展开
│ ● brevity        [已推送 ✓] │
│ ○ catalyst       [开始处理] │
│ ○ delineate      [处理中…] │
│ ...                         │
├─────────────────────────────┤
│ [全部开始处理]              │
│ [查看同步记录 →]            │
└─────────────────────────────┘
```

交互：
- 点击「开始处理」→ loading → 状态变为「已推送 ✓」
- 「全部开始处理」→ 逐词处理，显示进度（3/15）
- 点击已推送的词 → 展开查看 AI 生成内容
- 点击「同步」→ 调用 momo-sync，完成后刷新列表
- 点击「查看同步记录」→ navigateTo 同步记录页

### 同步记录页（二级页面）

```
┌─────────────────────────────┐
│ ← 同步记录                   │
├─────────────────────────────┤
│ 今天 10:05  成功  +15 词     │
│ 今天 08:30  成功  +3 词      │
│ 昨天 22:15  成功  +28 词     │
└─────────────────────────────┘
```

### Tab 2：设置

```
┌─────────────────────────────┐
│ 设置                         │
├─────────────────────────────┤
│ 墨墨 Token        [已配置 ✓]│
│ AI Provider       deepseek  │
│ AI API Key        [已配置 ✓]│
│ AI Model    deepseek-chat   │
├─────────────────────────────┤
│ 关于 MOMO 小程序 v1.0.0     │
└─────────────────────────────┘
```

## 7. 安全设计

| 数据 | 存储方式 | 说明 |
|------|----------|------|
| 墨墨 Token | 云数据库 AES 加密 | 密钥通过云开发环境变量 `ENCRYPT_KEY` 配置 |
| AI API Key | 云数据库 AES 加密 | 同上 |
| openid | 微信自动注入 | 无需额外处理 |

加密方案：云函数内使用 Node.js `crypto` 模块，AES-256-GCM，密钥从环境变量读取。

## 8. 与现有 Web 端的关系

| 维度 | Web 端 | 小程序端 |
|------|--------|----------|
| 后端 | FastAPI (Python) | 云函数 (Node.js) |
| 数据库 | SQLite/Turso | 云数据库 |
| 用户模型 | 多 profile（手动创建） | openid 自动关联 |
| 同步机制 | 写队列 + 守护线程 | 云函数按需触发 |
| 功能范围 | 全功能 | 今日任务 + 墨墨同步 |

两者**完全独立**，不共享后端或数据库。Web 端可以继续正常开发和使用。

## 9. 验收标准

1. 用户打开小程序 → 自动注册/登录 → 显示今日任务列表
2. 点击「开始处理」→ AI 生成内容 → 自动推送墨墨 → 状态更新
3. 点击「全部开始处理」→ 批量处理，显示进度
4. 点击「同步」→ 从墨墨拉取最新词汇 → 刷新列表
5. 点击「查看同步记录」→ 显示历史同步记录
6. 设置页可配置墨墨 Token + AI Provider/Key/Model
7. Token/Key 在云数据库中加密存储
