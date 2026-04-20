# MoMo Study Agent

高并发英语学习智能体，融合 AI 助记、云端同步与多用户管理，专为极致稳定与高性能场景设计。

---

## 架构目录树（单一职责标注）

```
.
├── core/         # 业务核心：AI、同步、主流程、日志、用户与迭代引擎
│   ├── config_wizard.py         # 首次配置引导与交互
│   ├── constants.py             # 全局常量定义
│   ├── db_manager.py            # 旧版数据库管理（已拆分，兼容保留）
│   ├── exceptions.py            # 业务异常类型
│   ├── gemini_client.py         # Gemini AI 客户端
│   ├── iteration_manager.py     # 智能迭代与批处理调度
│   ├── logger.py                # 日志封装与适配
│   ├── log_archiver.py          # 日志归档与清理
│   ├── log_config.py            # 日志配置加载
│   ├── maimemo_api.py           # 墨墨 API 封装
│   ├── mimo_client.py           # Mimo AI 客户端
│   ├── preflight.py             # 启动前环境体检
│   ├── profile_manager.py       # 用户配置与多账号管理
│   ├── study_workflow.py        # 主学习流程与任务编排
│   ├── sync_manager.py          # 云端同步与冲突处理
│   ├── ui_manager.py            # CLI/交互界面
│   ├── utils.py                 # 通用工具函数
│   ├── weak_word_filter.py      # 易错词过滤与标记
│   └── __init__.py
├── database/    # 数据持久化：连接、业务分层、单例与 WAL 防御
│   ├── connection.py            # 全局 libsql 单例连接与锁、后台守护线程
│   ├── hub_users.py             # Hub 用户业务与加密存储
│   ├── legacy.py                # 兼容旧版数据结构
│   ├── momo_words.py            # 单词/助记业务与同步快照
│   ├── schema.py                # 表结构与迁移、初始化入口
│   ├── utils.py                 # 加密、清洗、哈希等底层工具
│   └── README.md
├── config/      # 配置文件：日志、测试等 YAML 配置
│   ├── logging.yaml
│   └── test_config.yaml
├── main.py      # 入口：进程锁、主菜单、全局调度
├── requirements.txt  # 依赖声明
├── docs/        # 技术文档与开发规范
└── ...          # 其他辅助目录（data, logs, scripts, tests, tools, etc.）
```

---

## 并发与同步机制说明

### 1. 本地写线程 + 云端同步线程（双活架构）

- **本地写线程（_writer_daemon）**  
  负责所有写入请求的串行化与批量提交，确保 WAL 文件无竞争写锁，极大降低并发死锁与冲突概率。

- **云端同步线程（_sync_daemon）**  
  定时将本地变更通过 libsql 的 conn.sync() 增量同步到云端副本。同步前强制 gc.collect()，彻底清理悬空游标，确保同步安全。

- **双守护线程协作**  
  写线程与同步线程均为全局单例，互斥调度，保证本地与云端状态一致且无 WAL 冲突。

### 2. 进程级防多开锁（process.lock）

- **主入口 main.py**  
  启动时抢占物理 .process.lock 文件（Windows 用 msvcrt，Unix 用 fcntl），防止同一副本被多进程同时操作。
- **锁抢占失败即退出**  
  若检测到已有进程持有锁，立即 sys.exit(1)，杜绝一切跨进程 WAL 冲突根源。

---

请参考本文件进行架构理解与开发协作。