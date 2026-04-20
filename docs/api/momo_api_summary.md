# 墨墨开放 API (v1) 开发手册 (精简整理版)

这份文档基于 `document (1).yaml` 的原始 OpenAPI 定义进行了精简和分类，旨在为您提供最直观的开发参考。

---

## 🔒 鉴权与频控

### 1. 认证方式
所有请求需在 Header 中添加 `Authorization`：
```bash
Authorization: Bearer <您的TOKEN>
```

### 2. 频率限制 (Rate Limiting)
- **短周期**: 10 秒 20 次 / 60 秒 40 次
- **长周期**: 5 小时 2000 次

---

## 1. 单词搜索 (Vocabulary)
用于通过单词拼写换取获取唯一的 `voc_id`（后续所有操作的核心 ID）。

| 接口 | 方法 | 说明 | 关键参数 |
| :--- | :--- | :--- | :--- |
| `/api/v1/vocabulary` | `GET` | **获取单词 ID** | `spelling` (拼写) |
| `/api/v1/vocabulary/query` | `POST` | 批量查询单词 | `spellings` 或 `ids` (数组) |

---

## 2. 核心释义 (Interpretations)
**[您的核心需求]** 用于接管和美化单词主页显示的核心翻译。

| 接口 | 方法 | 说明 | 关键请求体字段 |
| :--- | :--- | :--- | :--- |
| `/api/v1/interpretations` | `POST` | **创建新释义** | `voc_id`, `interpretation` (文本), `tags`, `status` |
| `/api/v1/interpretations/{id}` | `POST` | **更新旧释义** | `interpretation`, `tags`, `status` |
| `/api/v1/interpretations` | `GET` | 获取自己的释义列表 | `voc_id` |
| `/api/v1/interpretations/{id}` | `DELETE`| 删除指定释义 | `id` (释义ID) |

---

## 3. 学习数据 & 流程 (Study - 公测中)
用于自动化获取每日任务、添加新词到规划、查看进度。

| 接口 | 方法 | 说明 | 关键参数/逻辑 |
| :--- | :--- | :--- | :--- |
| `/api/v1/study/get_today_items` | `POST` | **获取今日待学/待复习单词** | `limit` (最大1000), `is_new`, `is_finished` |
| `/api/v1/study/add_words` | `POST` | **添加单词到学习规划** | `words` (ID数组), `advance` (是否提前复习) |
| `/api/v1/study/get_study_progress` | `POST` | 查看今日进度 | 返回 `total`, `finished`, `study_time` |
| `/api/v1/study/query_study_records`| `POST` | 查询历史/未来学习记录 | 可按 `next_study_date` 筛选 |
| `/api/v1/study/advance_study` | `POST` | 提前复习(需等级解锁) | `voc_ids` |

---

## 4. 助记管理 (Notes)
用于管理单词下方的“助记”笔记板块。

| 接口 | 方法 | 说明 | 关键字段 |
| :--- | :--- | :--- | :--- |
| `/api/v1/notes` | `POST` | 创建助记 | `voc_id`, `note_type`, `note` |
| `/api/v1/notes/{id}` | `POST` | 更新助记 | `note_type`, `note` |
| `/api/v1/notes` | `GET` | 获取自己的助记列表 | `voc_id` |

---

## 5. 原生例句 (Phrases)
用于向单词添加原生的例句支持。

| 接口 | 方法 | 说明 | 关键字段 |
| :--- | :--- | :--- | :--- |
| `/api/v1/phrases` | `POST` | 创建原生例句 | `voc_id`, `phrase`, `interpretation` |
| `/api/v1/phrases/{id}` | `POST` | 更新例句 | `phrase`, `interpretation` |
| `/api/v1/phrases` | `GET` | 获取自己的例句列表 | `voc_id` |

---

## 6. 云词本 (Notepads)
管理用户的个人词单/文件夹。

| 接口 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/notepads` | `GET` | 查询云词本列表 |
| `/api/v1/notepads` | `POST` | 创建新词本 (带标题、内容、简介) |
| `/api/v1/notepads/{id}` | `GET` | **获取特定词本内的所有单词** |
| `/api/v1/notepads/{id}` | `POST` | 更新词本内容 |

---

## 💡 开发 Tip
- **状态值**: 释义与例句通常使用 `PUBLISHED`。
- **ID 混淆**: 注意 `voc_id` (单词ID) 与 `interpretation_id` / `note_id` (内容条目ID) 的区别。
- **自动同步**: 公测接口（Study 类）通常要求在 App 中开启“自动同步”开关。
- **API 限制处理**:
  - **429 错误** (频率限制): 使用指数退避重试机制
  - **400 错误** (创建限制): 检测 `interpretation_create_limitation` 错误码，标记限制状态
  - **重试机制**: 最大重试 3 次，等待时间 [10, 25, 60] 秒
