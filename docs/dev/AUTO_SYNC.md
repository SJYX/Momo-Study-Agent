# 自动同步机制

## 概述

本系统实现了程序退出时的自动同步功能，确保所有数据都能及时保存到云端数据库。

## 同步时机

### 1. 程序正常退出
- 用户选择选项 4（同步并退出）
- 程序捕获 `KeyboardInterrupt`（Ctrl+C）
- 程序正常执行完毕

### 2. 异常退出
- 程序崩溃或意外错误
- 系统中断

## 同步内容

### 1. 用户数据库同步 (`sync_databases`)
同步以下表到云端：
- `ai_word_notes`：AI 生成的助记笔记
- `processed_words`：已处理的单词记录
- `word_progress_history`：单词进度历史
- `ai_batches`：AI 批处理记录
- `system_config`：系统配置

### 2. 中央 Hub 数据库同步 (`sync_hub_databases`)
同步以下表到云端：
- `users`：用户信息
- `user_stats`：用户统计信息
- `user_sessions`：用户会话记录
- `admin_logs`：管理日志

## 实现代码

### 主程序退出处理 (`main.py`)

```python
finally:
    # 自动同步数据到云端
    try:
        from core.logger import get_logger
        logger = get_logger()
        logger.info("正在执行退出前自动同步...", module="main")

        # 同步用户数据库
        sync_stats = sync_databases(dry_run=False)
        logger.info(f"用户数据库同步完成: 上传 {sync_stats['upload']}, 下载 {sync_stats['download']}", module="main")

        # 同步中央 Hub 数据库
        hub_stats = sync_hub_databases(dry_run=False)
        logger.info(f"中央 Hub 数据库同步完成: 上传 {hub_stats['upload']}, 下载 {hub_stats['download']}", module="main")

        print("\n✅ 数据已自动同步到云端。")
    except Exception as e:
        try:
            from core.logger import get_logger
            logger = get_logger()
            logger.warning(f"退出时自动同步失败: {e}", module="main")
        except:
            print(f"\n⚠️  自动同步失败: {e}")

    print("\n程序已安全退出。")
```

## 同步逻辑

### 1. 双向同步
- **上传**：本地新增或更新的数据 → 云端
- **下载**：云端新增或更新的数据 → 本地

### 2. 时间戳比较
- 比较本地和云端记录的时间戳
- 只同步时间戳较新的记录
- 避免重复同步

### 3. 冲突处理
- 如果本地和云端都有更新，以时间戳较新的为准
- 不会覆盖对方的数据

## 配置要求

### 强制云端模式
```python
# .env 文件
FORCE_CLOUD_MODE=True
```

### 云端数据库配置
```python
# 用户数据库
TURSO_DB_URL=https://history-ddy-ashershi.aws-us-east-1.turso.io
TURSO_AUTH_TOKEN=your_token_here

# 中央 Hub 数据库
TURSO_HUB_DB_URL=https://momo-users-hub-ashershi.aws-us-east-1.turso.io
TURSO_HUB_AUTH_TOKEN=your_token_here
```

## 使用示例

### 1. 程序正常退出
```
用户选择选项 4：同步并退出
↓
程序执行最后的数据同步...
↓
数据已自动同步到云端。
↓
程序已安全退出。
```

### 2. Ctrl+C 退出
```
用户按 Ctrl+C
↓
捕获 KeyboardInterrupt
↓
执行退出前自动同步...
↓
数据已自动同步到云端。
↓
程序已安全退出。
```

### 3. 程序崩溃
```
程序发生异常
↓
捕获异常并记录日志
↓
执行退出前自动同步...
↓
数据已自动同步到云端（如果可能）
↓
程序已安全退出。
```

## 注意事项

### 1. 网络连接
- 自动同步需要网络连接
- 如果网络不通，同步会失败但程序仍会退出
- 失败信息会记录到日志

### 2. 数据一致性
- 自动同步确保数据最终一致性
- 不保证同步过程中的实时一致性
- 建议在网络稳定时使用程序

### 3. 性能影响
- 同步过程可能需要几秒钟
- 程序退出时会等待同步完成
- 如果同步失败，程序仍会正常退出

## 故障排除

### 1. 同步失败
检查以下内容：
- 网络连接是否正常
- 云端数据库配置是否正确
- 认证令牌是否有效

### 2. 数据不一致
如果发现数据不一致：
1. 手动运行同步函数
2. 检查本地和云端数据库的时间戳
3. 必要时联系管理员

### 3. 日志查看
同步日志保存在：
- 程序日志文件中
- 控制台输出中
- 系统日志中

## 未来改进

1. **增量同步**：只同步变化的数据，提高性能
2. **断点续传**：网络中断后继续同步
3. **同步状态显示**：显示同步进度和状态
4. **同步历史**：记录同步历史和结果
