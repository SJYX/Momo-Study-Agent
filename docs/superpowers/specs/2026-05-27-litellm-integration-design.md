# LiteLLM Integration — 统一 AI 供应商抽象层

**Date:** 2026-05-27
**Status:** Draft (pending user review)

## Goal

用 LiteLLM 替换手写的 MimoClient/GeminiClient，实现统一 AI 供应商切换。前端在 `/users` 页面添加 AI 设置卡片，支持 10 家主流中英文供应商。

## Approach: 完全替换 (Approach A)

删除旧客户端，用单一 `LiteLLMClient` 包装 `litellm.completion()`。保持 `generate_with_instruction(prompt, instruction)` 接口不变，业务层零改动。

---

## 1. Backend Architecture

### 1.1 新增 `core/litellm_client.py`

```python
class LiteLLMClient:
    def __init__(self, model: str, api_key: str, base_url: str = None):
        self.model = model          # e.g. "gemini/gemini-2.0-flash"
        self.api_key = api_key
        self.base_url = base_url    # OpenAI 兼容端点用
        self.prompt_file = PROMPT_FILE

    def generate_with_instruction(self, prompt: str, instruction: str = None) -> Tuple[str, dict]:
        """调用 litellm.completion()，返回 (text, usage_dict)"""

    def close(self):
        """清理资源"""
```

接口与现有 `MimoClient`/`GeminiClient` 完全一致。

### 1.2 修改 `core/factories.py`

```python
def build_ai_client():
    from core.litellm_client import LiteLLMClient
    return LiteLLMClient(
        model=f"{AI_PROVIDER}/{AI_MODEL}",
        api_key=AI_API_KEY,
        base_url=AI_BASE_URL,
    )
```

### 1.3 修改 `config.py`

统一 AI 配置变量：
- `AI_PROVIDER` — 供应商名（`gemini`、`openai`、`anthropic`、`mimo`、`deepseek`、`qwen`、`zhipu`、`moonshot`、`yi`、`mistral`）
- `AI_API_KEY` — 统一 API key
- `AI_MODEL` — 模型名（如 `gemini-2.0-flash`、`mimo-v2-flash`）
- `AI_BASE_URL` — 可选，OpenAI 兼容端点

### 1.4 删除旧客户端

- 删除 `core/mimo_client.py`
- 删除 `core/gemini_client.py`

### 1.5 修改 `core/profile_loader.py`

`USER_SCOPED_KEYS` 更新：
```python
USER_SCOPED_KEYS = [
    "MOMO_TOKEN",
    "AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL",
    # ... Turso DB keys ...
]
```

### 1.6 旧配置迁移

启动时自动映射：
- `MIMO_API_KEY` → `AI_API_KEY`（如果 `AI_API_KEY` 未设置）
- `GEMINI_API_KEY` → `AI_API_KEY`（如果 `AI_API_KEY` 未设置）
- `AI_PROVIDER=mimo` → `AI_PROVIDER=openai` + `AI_BASE_URL=https://api.xiaomimimo.com/v1`
- `MIMO_MODEL` → `AI_MODEL`（如果 `AI_MODEL` 未设置）
- `GEMINI_MODEL` → `AI_MODEL`（如果 `AI_MODEL` 未设置）

---

## 2. Frontend Design

### 2.1 AI 设置卡片

在 `/users` 页面每个用户信息下方添加 AI 设置卡片：

```
┌─────────────────────────────────────────────┐
│  AI 供应商设置                               │
│                                             │
│  供应商    [gemini              ▼]          │
│  模型      [gemini-2.0-flash    ▼]          │
│  API Key   [••••••••••••••••]  [显示]       │
│  Base URL  [https://...] (可选)             │
│                                             │
│  [测试连接]  [保存]                          │
│  ✓ 连接成功 / ✗ 连接失败: ...               │
└─────────────────────────────────────────────┘
```

### 2.2 供应商列表（10 家）

| 供应商 | LiteLLM prefix | 需要 base_url |
|--------|---------------|---------------|
| Mimo | `openai/` | 是 |
| Gemini | `gemini/` | 否 |
| OpenAI | `openai/` | 否 |
| Claude | `claude/` | 否 |
| DeepSeek | `deepseek/` | 否 |
| Qwen | `openai/` | 是 |
| Zhipu | `openai/` | 是 |
| Moonshot | `openai/` | 是 |
| Yi | `openai/` | 是 |
| Mistral | `mistral/` | 否 |

### 2.3 交互流程

1. 选择供应商 → 加载预设模型列表
2. 填写 API Key → 可选 Base URL
3. 「测试连接」→ 后端 test call → 显示结果
4. 「保存」→ 写入 profile `.env`

### 2.4 后端 API 扩展

| Endpoint | Method | 说明 |
|----------|--------|------|
| `/api/users/{username}/ai-config` | POST | 保存 AI 配置到 profile .env |
| `/api/users/{username}/ai-test` | POST | 测试 AI 连接 |
| `/api/users/{username}/ai-models` | GET | 获取供应商预设模型列表 |

### 2.5 设计语言对齐

- 输入框：`border-border-default rounded-button focus:border-accent`
- 按钮：主按钮「保存」(`bg-accent`) + 次按钮「测试连接」(`bg-accent-soft`)
- 状态：Badge 组件（`success-soft` / `error-soft`）
- 卡片：`bg-surface-card rounded-card shadow-card p-5`

---

## 3. Error Handling

- `litellm.AuthenticationError` → API key 无效
- `litellm.APIError` → 服务端错误
- `litellm.NotFoundError` → 模型不存在
- 网络超时 → 重试 1 次后报错
- 前端测试连接：显示具体错误信息

---

## 4. Testing

- 单元测试：`LiteLLMClient` mock `litellm.completion`
- 集成测试：对测试 profile 做真实 API 调用
- 前端：Vitest 组件测试

---

## Files to create/modify

| File | Action | Notes |
|------|--------|------|
| `core/litellm_client.py` | CREATE | 统一 AI 客户端 |
| `core/factories.py` | MODIFY | 返回 LiteLLMClient |
| `config.py` | MODIFY | 统一 AI 变量 |
| `core/profile_loader.py` | MODIFY | 更新 USER_SCOPED_KEYS |
| `core/mimo_client.py` | DELETE | 被 LiteLLM 替换 |
| `core/gemini_client.py` | DELETE | 被 LiteLLM 替换 |
| `web/backend/routers/users.py` | MODIFY | 添加 AI 配置 API |
| `web/backend/schemas.py` | MODIFY | 添加 AI 配置 schema |
| `web/frontend/src/pages/Users.tsx` | MODIFY | 添加 AI 设置卡片 |
| `web/frontend/src/api/types.ts` | MODIFY | 添加 AI 配置类型 |
