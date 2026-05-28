# SYNC_OPTIMIZATION_PLAYBOOK.md

## 目的

记录同步优化的路线选择、历史约束和阶段依赖。执行层细节请直接看 [SYNC_PRIORITY_MATRIX.md](SYNC_PRIORITY_MATRIX.md)，当前完成情况看 [REFACTOR_PROGRESS.md](REFACTOR_PROGRESS.md)。

## 路线摘要

- A1：API 查询降重，是同步优化的前置基石。
- A4：运行期 Kill Switch，归入配置现代化。
- B1/B2：优先队列与 per-profile 暂停，是当前调度主干。
- B3：闲时引擎，依赖指标层。
- B4：前端协同，独立 web_ui 工作区。
- B5：可观测性，作为闲时引擎与后续治理的基础。

## 使用方式

- 想看“当前任务怎么排、怎么抢占、怎么降级”时，读 [SYNC_PRIORITY_MATRIX.md](SYNC_PRIORITY_MATRIX.md)。
- 想看“这些路线为什么这么定”时，读 `docs/dev/DECISIONS.md` 和本文件的历史背景。
- 想看“已完成到什么程度”时，读 [REFACTOR_PROGRESS.md](REFACTOR_PROGRESS.md)。

## 历史定位

本文件保留的是路线层信息，不再承载执行细节。任何新实现细节应落在矩阵、进度文档或代码本身，避免这里重复维护。
