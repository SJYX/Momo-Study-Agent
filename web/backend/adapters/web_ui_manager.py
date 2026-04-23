"""
web/backend/adapters/web_ui_manager.py — Web UI Manager 适配器。

兼容 CLIUIManager 接口的空实现。
Web 后端通过 LoggerBridge 捕获进度，不依赖 UI 方法；
此类仅为 StudyWorkflow 构造签名兼容而提供。

如果未来需要 render_sync_progress 转发到 task 队列，
可以在这里扩展实现。
"""


class WebUIManager:
    """空 UI 实现 — Web 后端不需要 CLI 交互。"""

    def __getattr__(self, name: str):
        """所有方法调用均为空操作。"""
        return lambda *args, **kwargs: None