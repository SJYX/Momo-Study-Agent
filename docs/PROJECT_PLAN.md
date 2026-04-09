# 墨墨背单词自动化助记脚本 (MVP 版本) 规划

**执行版本：V1.0 最小可行性脚本 (CLI & SQLite)**

这份文档约束了当前分支 (`feature/mvp-script`) 的核心目标与设计架构。当前阶段不包含复杂的 Web 界面、Vite 前端、FastAPI 等服务端组件。当前首要目标是构建一个**全自动、终端控制、支持多模型切换的最小可行性数据闭环脚本 (MVP)**。

## 一、 系统架构 (MVP)

- **控制展现层**：基于命令行的 Python 自动执行流，使用标准输出打印执行进度。
- **业务中枢层**：
  - **模型引擎**：支持多 AI 提供商切换（Google Gemini / 小米 Mimo）。
  - **调度协同**：负责墨墨 OpenAPI 拉取生词、AI 生成助记、自动化回写等任务的批处理（Batch）调度。
- **数据持久层**：引入本地 `SQLite3` 作为底层固化设施，避免由于网络问题导致接口重复调用、额度浪费，同时保留每次 AI 生成的神仙笔记。

## 二、 后端核心数据流构建范式 (Database Logic)

利用 SQLite 部署本地数据库。基础包括两张关联表（具体字段可根据后续迭代演进）：

### `Tbl_Momo_Words` (墨墨源数据表)
| 字段名 | 类型 | 简述 |
| :--- | :--- | :--- |
| id | INTEGER | PK 自增主键 |
| voc_id | TEXT | 墨墨应用官方索引键 |
| spelling | TEXT | 真实需要背诵的英文单词拼写 |
| is_new | BOOLEAN | 是否是生词类型 |
| date_pulled | DATETIME | 当日该批次拉取并建立入库跟踪的时间 |

### `Tbl_AI_Notes` (AI 模型知识资产落库表)
| 字段名 | 类型 | 简述 |
| :--- | :--- | :--- |
| id | INTEGER | PK 自增主键 |
| voc_id | TEXT | 用于和文字大表链接 (外键) |
| model_used | TEXT | 生成当次选用来源 (例如: `gemini-2.0-flash` 或 `mimo-v2-flash`) |
| mnemonic | TEXT | 模型生成的助记法纯文本内容 |
| note_type | TEXT | 被挂载的名义与分类 |
| created_at | DATETIME | 成功落库的时间戳 |

## 三、 MVP 核心执行流 (CLI Flow)

1. **环境与配置加载**：读取 `.env` 配置文件以初始化 `mimo_client.py` 或 `gemini_client.py`，决定当前的 `AI_PROVIDER`。
2. **生词拉取**：调用墨墨接口，获取当日需学习的词汇列表。
3. **AI 并行解析**：剔除本地 SQLite 已处理的单词，根据 `BATCH_SIZE` 将新的生词打包投递给 AI 生成专属记忆法。
4. **数据落库与同步**：将最新产出的助记保存至本地 DB，并通过 Maimemo API 推送同步至墨墨服务端。在控制台上呈现同步进度。

## 四、 工程合规目录界定
```
/e/MOMO_Script/
├── main.py (主流程业务挂载入口，负责启动与编排)
├── db_manager.py (SQLite 数据库维护底座)
├── config.py (安全过滤与变量读取)
├── maimemo_api.py (核心 SDK 墨墨组件)
├── gemini_client.py (Google Gemini 请求类)
├── mimo_client.py (小米 Mimo 请求类)
├── gem_prompt.txt (AI 系统角色设定和 Prompt 本地保存)
├── .env.template (环境变量样本文件)
├── tests/ 
│   └── experiments/test_model_switch.py (多模型实验验证)
└── PROJECT_PLAN.md (项目主线依据，即本文档)
```
