# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Web UI V1: Today Command Center**
  - **T1 默认视图改造**: 实现了基于价值与时间压力的智能排序，并提供“仅可执行项”过滤，提升专注度 (`ff_today_default_view`)。
  - **T2 轻量确认条**: 增加批量处理前的二次防误触确认，避免意外触发任务 (`ff_today_light_confirm`)。
  - **T3 自动跟随执行**: 任务执行期间列表自动滚动定位至当前处理项，支持暂停/恢复跟随 (`ff_today_follow_running`)。
  - **T4 摘要面板**: 任务结束后固定展示统计摘要，减少界面跳跃 (`ff_today_summary_stay`)。
  - **T5 错误分组**: 智能提取 `error_type`/`error_code`，将失败任务按特征进行手风琴式折叠分组 (`ff_today_failure_groups`)。
  - **T6 局部重试**: 支持针对单独的失败分组发起组级重试，后端扩充按 `voc_ids` 定向处理能力 (`ff_today_group_retry`)。
  - **T7 大批量门禁**: 增加大批量(>100)重试时的强阻断式警示弹窗 `BulkGuardModal`，防止性能压力引发卡顿 (`ff_today_bulk_guard`)。
  - **T8 残留高亮**: 重试后对仍然失败的项进行直观的红色视觉定位 (`ff_today_residual_highlight`)。
  - **T9 Feature Flags**: 建立统一的功能开关，支持一键切换和安全回退机制。
