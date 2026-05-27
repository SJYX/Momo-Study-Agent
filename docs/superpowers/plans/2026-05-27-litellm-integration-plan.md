# LiteLLM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hand-crafted MimoClient/GeminiClient with a unified LiteLLM client, and add a frontend AI settings card supporting 10 providers.

**Architecture:** Single `LiteLLMClient` class wraps `litellm.completion()`, exposing the same `generate_with_instruction(prompt, instruction)` interface. The factory (`build_ai_client`) returns this client for all providers. Frontend adds an `AIConfigCard` component on the `/users` page with provider dropdown, model presets, API key, base URL, and test-connection functionality.

**Tech Stack:** Python `litellm`, FastAPI, React 18, TypeScript 5.6, TanStack React Query v5, Tailwind CSS v4

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `core/litellm_client.py` | CREATE | Unified AI client wrapping `litellm.completion()` |
| `core/litellm_presets.py` | CREATE | Provider/model preset data (10 providers, model lists) |
| `config.py` | MODIFY | Add `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`; legacy migration |
| `core/profile_loader.py` | MODIFY | Update `USER_SCOPED_KEYS` |
| `core/factories.py` | MODIFY | Return `LiteLLMClient` |
| `core/mimo_client.py` | DELETE | Replaced by LiteLLM |
| `core/gemini_client.py` | DELETE | Replaced by LiteLLM |
| `web/backend/schemas.py` | MODIFY | Add AI config schemas |
| `web/backend/routers/users.py` | MODIFY | Add AI config/test/models endpoints |
| `web/frontend/src/api/types.ts` | MODIFY | Add AI config types |
| `web/frontend/src/components/AIConfigCard.tsx` | CREATE | AI settings card component |
| `web/frontend/src/pages/Users.tsx` | MODIFY | Mount AIConfigCard |
| `tests/unit/core/test_litellm_client.py` | CREATE | Unit tests for LiteLLMClient |
| `tests/unit/core/test_litellm_presets.py` | CREATE | Unit tests for presets |
| `tests/unit/core/test_factories.py` | CREATE | Unit tests for factory |

---

## Task 1: Add `litellm` dependency

**Files:**
- Modify: `requirements.txt` (or `pyproject.toml`)

- [ ] **Step 1: Add litellm to requirements**

Check which dependency file exists:

```bash
ls requirements.txt pyproject.toml 2>$null
```

If `requirements.txt` exists, append:

```
litellm>=1.40.0
```

If `pyproject.toml` exists, add to dependencies section.

- [ ] **Step 2: Install and verify**

```bash
pip install litellm>=1.40.0
python -c "import litellm; print(litellm.__version__)"
```

Expected: prints version number without error.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add litellm for unified AI provider abstraction"
```

---

## Task 2: Create provider/model presets

**Files:**
- Create: `core/litellm_presets.py`
- Test: `tests/unit/core/test_litellm_presets.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_litellm_presets.py`:

```python
"""tests/unit/core/test_litellm_presets.py"""
import pytest
from core.litellm_presets import PROVIDERS, get_models_for_provider, get_default_base_url


def test_providers_has_ten_entries():
    assert len(PROVIDERS) == 10


def test_each_provider_has_required_fields():
    for p in PROVIDERS:
        assert "id" in p
        assert "name" in p
        assert "prefix" in p
        assert "models" in p
        assert "needs_base_url" in p
        assert len(p["models"]) >= 1


def test_get_models_for_provider_valid():
    models = get_models_for_provider("gemini")
    assert "gemini-2.0-flash" in models


def test_get_models_for_provider_unknown():
    models = get_models_for_provider("nonexistent")
    assert models == []


def test_get_default_base_url_mimo():
    url = get_default_base_url("mimo")
    assert url == "https://api.xiaomimimo.com/v1"


def test_get_default_base_url_gemini():
    url = get_default_base_url("gemini")
    assert url is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/core/test_litellm_presets.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.litellm_presets'`

- [ ] **Step 3: Write the implementation**

Create `core/litellm_presets.py`:

```python
"""core/litellm_presets.py: 供应商/模型预设数据。

10 家主流中英文 AI 供应商的 LiteLLM prefix、预设模型列表、是否需要 base_url。
"""
from __future__ import annotations

from typing import Optional

PROVIDERS: list[dict] = [
    {
        "id": "mimo",
        "name": "Mimo",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2-flash", "mimo-v2-pro"],
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "prefix": "gemini/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "prefix": "openai/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1-nano"],
    },
    {
        "id": "anthropic",
        "name": "Claude",
        "prefix": "claude/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["claude-sonnet-4-20250514", "claude-haiku-4-20250414"],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "prefix": "deepseek/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "qwen",
        "name": "Qwen",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
    },
    {
        "id": "zhipu",
        "name": "Zhipu",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4-long"],
    },
    {
        "id": "moonshot",
        "name": "Moonshot",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    {
        "id": "yi",
        "name": "Yi",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-lightning", "yi-large", "yi-medium"],
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "prefix": "mistral/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["mistral-small-latest", "mistral-large-latest", "codestral-latest"],
    },
]

_PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


def get_models_for_provider(provider_id: str) -> list[str]:
    """返回供应商的预设模型列表，未知供应商返回空列表。"""
    p = _PROVIDER_MAP.get(provider_id)
    return list(p["models"]) if p else []


def get_default_base_url(provider_id: str) -> Optional[str]:
    """返回供应商的默认 base_url，不需要则返回 None。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["default_base_url"] if p else None


def get_provider_prefix(provider_id: str) -> str:
    """返回供应商的 LiteLLM prefix，如 'openai/'、'gemini/'。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["prefix"] if p else "openai/"


def needs_base_url(provider_id: str) -> bool:
    """返回供应商是否需要 base_url。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["needs_base_url"] if p else False


__all__ = [
    "PROVIDERS",
    "get_models_for_provider",
    "get_default_base_url",
    "get_provider_prefix",
    "needs_base_url",
]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/core/test_litellm_presets.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/litellm_presets.py tests/unit/core/test_litellm_presets.py
git commit -m "feat(core): add provider/model presets for 10 AI providers"
```

---

## Task 3: Create LiteLLMClient

**Files:**
- Create: `core/litellm_client.py`
- Test: `tests/unit/core/test_litellm_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_litellm_client.py`:

```python
"""tests/unit/core/test_litellm_client.py"""
import pytest
from unittest.mock import patch, MagicMock


def test_init_requires_api_key():
    from core.litellm_client import LiteLLMClient
    with pytest.raises(ValueError, match="API key"):
        LiteLLMClient(model="openai/mimo-v2-flash", api_key="")


def test_init_stores_params():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(
        model="openai/mimo-v2-flash",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    assert client.model == "openai/mimo-v2-flash"
    assert client.api_key == "test-key"
    assert client.base_url == "https://example.com/v1"


def test_generate_with_instruction_returns_text_and_usage():
    from core.litellm_client import LiteLLMClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"results": []}'
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30

    client = LiteLLMClient(model="openai/test", api_key="key")

    with patch("core.litellm_client.litellm.completion", return_value=mock_response) as mock_call:
        text, metadata = client.generate_with_instruction("test prompt")

    assert text == '{"results": []}'
    assert metadata["prompt_tokens"] == 10
    assert metadata["completion_tokens"] == 20
    assert metadata["total_tokens"] == 30
    mock_call.assert_called_once()


def test_generate_with_instruction_passes_system_instruction():
    from core.litellm_client import LiteLLMClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 5
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 10

    client = LiteLLMClient(model="openai/test", api_key="key")

    with patch("core.litellm_client.litellm.completion", return_value=mock_response) as mock_call:
        client.generate_with_instruction("prompt", instruction="custom system")

    call_kwargs = mock_call.call_args
    messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "custom system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "prompt"


def test_generate_with_instruction_retries_on_failure():
    from core.litellm_client import LiteLLMClient

    fail_response = MagicMock()
    fail_response.choices = [MagicMock()]
    fail_response.choices[0].message.content = ""
    fail_response.choices[0].finish_reason = "error"
    fail_response.usage = MagicMock()
    fail_response.usage.prompt_tokens = 0
    fail_response.usage.completion_tokens = 0
    fail_response.usage.total_tokens = 0

    success_response = MagicMock()
    success_response.choices = [MagicMock()]
    success_response.choices[0].message.content = "success"
    success_response.choices[0].finish_reason = "stop"
    success_response.usage = MagicMock()
    success_response.usage.prompt_tokens = 5
    success_response.usage.completion_tokens = 5
    success_response.usage.total_tokens = 10

    client = LiteLLMClient(model="openai/test", api_key="key")

    with patch("core.litellm_client.litellm.completion", side_effect=[Exception("timeout"), success_response]):
        with patch("core.litellm_client.time.sleep"):
            text, metadata = client.generate_with_instruction("prompt")

    assert text == "success"


def test_generate_with_instruction_returns_empty_on_all_failures():
    from core.litellm_client import LiteLLMClient

    client = LiteLLMClient(model="openai/test", api_key="key")

    with patch("core.litellm_client.litellm.completion", side_effect=Exception("fail")):
        with patch("core.litellm_client.time.sleep"):
            text, metadata = client.generate_with_instruction("prompt")

    assert text == ""
    assert "error" in metadata
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/core/test_litellm_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.litellm_client'`

- [ ] **Step 3: Write the implementation**

Create `core/litellm_client.py`:

```python
"""core/litellm_client.py: 统一 AI 客户端，封装 litellm.completion()。

替换 MimoClient / GeminiClient，接口保持 generate_with_instruction(prompt, instruction)。
"""
from __future__ import annotations

import os
import time
from typing import Tuple

import litellm

from config import MAX_RETRIES, PROMPT_FILE, RETRY_WAIT_S

# 抑制 litellm 自身的重试日志（我们自己管理重试）
litellm.suppress_debug_info = True


class LiteLLMClient:
    """统一 AI 客户端，支持 10+ 供应商。"""

    def __init__(self, model: str, api_key: str, base_url: str = None):
        if not api_key:
            raise ValueError("API key is required")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.prompt_file = PROMPT_FILE

    def _load_instruction(self) -> str:
        """加载系统提示词。"""
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_with_instruction(
        self, prompt: str, instruction: str = None
    ) -> Tuple[str, dict]:
        """调用 litellm.completion()，返回 (text, usage_dict)。"""
        system_instr = instruction or self._load_instruction()
        messages = [
            {"role": "system", "content": system_instr},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "api_key": self.api_key,
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = litellm.completion(**kwargs)
                choice = response.choices[0]
                text = choice.message.content or ""
                usage = response.usage

                metadata = {
                    "request_id": getattr(response, "id", None),
                    "finish_reason": choice.finish_reason,
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                }
                return text.strip(), metadata
            except Exception as e:
                last_error = str(e)
                try:
                    from core.logger import get_logger
                    get_logger().warning(
                        "LiteLLM 请求失败，准备重试",
                        module="litellm_client",
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        error=last_error,
                    )
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_S[attempt - 1])
                    continue

        return "", {
            "error": last_error,
            "error_type": "request",
            "stage": "request",
        }

    def close(self):
        """清理资源（litellm 无状态，保留接口兼容）。"""
        pass


__all__ = ["LiteLLMClient"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/core/test_litellm_client.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/litellm_client.py tests/unit/core/test_litellm_client.py
git commit -m "feat(core): add LiteLLMClient wrapping litellm.completion()"
```

---

## Task 4: Update config.py — unified AI variables + legacy migration

**Files:**
- Modify: `config.py:74-88` (AI config section)
- Modify: `config.py:139-174` (switch_user function)

- [ ] **Step 1: Add unified AI config variables**

In `config.py`, replace the AI config section (lines 74–88) with:

```python
# API Keys
MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")

# 模型设置 (AI Settings) — Legacy
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2-flash")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))

# 当前使用的 AI 提供商
AI_PROVIDER = os.getenv("AI_PROVIDER", "mimo")

# 统一 AI 配置（LiteLLM）
AI_API_KEY = os.getenv("AI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL")
AI_BASE_URL = os.getenv("AI_BASE_URL")

# 旧配置自动迁移（如果 AI_API_KEY 未设置，从旧 key 映射）
if not AI_API_KEY:
    if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
        AI_API_KEY = GEMINI_API_KEY
    elif MIMO_API_KEY:
        AI_API_KEY = MIMO_API_KEY

if not AI_MODEL:
    if AI_PROVIDER == "gemini" and GEMINI_MODEL:
        AI_MODEL = GEMINI_MODEL
    elif MIMO_MODEL:
        AI_MODEL = MIMO_MODEL

# mimo → openai 兼容映射
if AI_PROVIDER == "mimo" and not AI_BASE_URL:
    AI_BASE_URL = "https://api.xiaomimimo.com/v1"
```

- [ ] **Step 2: Update switch_user to export new variables**

In `config.py`, update the `switch_user` function's global declarations and assignments:

```python
def switch_user(username: str) -> str:
    global ACTIVE_USER, MOMO_TOKEN, GEMINI_API_KEY, GEMINI_MODEL, MIMO_API_KEY, MIMO_API_BASE, MIMO_MODEL
    global AI_PROVIDER, AI_API_KEY, AI_MODEL, AI_BASE_URL, DB_PATH, TEST_DB_PATH
    global TURSO_DB_URL, TURSO_AUTH_TOKEN
    global TURSO_CACHE_DB_URL, TURSO_CACHE_AUTH_TOKEN

    normalized, db_path, test_db_path = _switch_user_impl(
        username,
        global_env_path=global_env_path,
        profiles_dir=PROFILES_DIR,
        data_dir=DATA_DIR,
    )

    ACTIVE_USER = normalized
    MOMO_TOKEN = os.getenv("MOMO_TOKEN")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
    MIMO_API_KEY = os.getenv("MIMO_API_KEY")
    MIMO_API_BASE = os.getenv("MIMO_API_BASE") or "https://api.xiaomimimo.com/v1"
    MIMO_MODEL = os.getenv("MIMO_MODEL") or "mimo-v2-flash"
    AI_PROVIDER = os.getenv("AI_PROVIDER", "mimo")
    AI_API_KEY = os.getenv("AI_API_KEY")
    AI_MODEL = os.getenv("AI_MODEL")
    AI_BASE_URL = os.getenv("AI_BASE_URL")
    TURSO_DB_URL = os.getenv("TURSO_DB_URL")
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
    TURSO_CACHE_DB_URL = os.getenv("TURSO_CACHE_DB_URL")
    TURSO_CACHE_AUTH_TOKEN = os.getenv("TURSO_CACHE_AUTH_TOKEN")
    DB_PATH = db_path
    TEST_DB_PATH = test_db_path

    # 旧配置自动迁移
    if not AI_API_KEY:
        if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
            AI_API_KEY = GEMINI_API_KEY
        elif MIMO_API_KEY:
            AI_API_KEY = MIMO_API_KEY
    if not AI_MODEL:
        if AI_PROVIDER == "gemini" and GEMINI_MODEL:
            AI_MODEL = GEMINI_MODEL
        elif MIMO_MODEL:
            AI_MODEL = MIMO_MODEL
    if AI_PROVIDER == "mimo" and not AI_BASE_URL:
        AI_BASE_URL = "https://api.xiaomimimo.com/v1"

    return normalized
```

- [ ] **Step 3: Syntax check**

```bash
python -m py_compile config.py
```

Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat(config): add unified AI_API_KEY/AI_MODEL/AI_BASE_URL with legacy migration"
```

---

## Task 5: Update profile_loader.py — USER_SCOPED_KEYS

**Files:**
- Modify: `core/profile_loader.py:29-43`

- [ ] **Step 1: Add new keys to USER_SCOPED_KEYS**

Replace the `USER_SCOPED_KEYS` list:

```python
USER_SCOPED_KEYS: List[str] = [
    "MOMO_TOKEN",
    "AI_PROVIDER",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_BASE_URL",
    "MIMO_API_KEY",
    "MIMO_API_BASE",
    "MIMO_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "TURSO_DB_URL",
    "TURSO_AUTH_TOKEN",
    "TURSO_DB_HOSTNAME",
    "TURSO_TEST_DB_URL",
    "TURSO_TEST_AUTH_TOKEN",
    "TURSO_TEST_DB_HOSTNAME",
]
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile core/profile_loader.py
```

- [ ] **Step 3: Commit**

```bash
git add core/profile_loader.py
git commit -m "feat(profile): add AI_API_KEY/AI_MODEL/AI_BASE_URL to USER_SCOPED_KEYS"
```

---

## Task 6: Rewrite factories.py to use LiteLLMClient

**Files:**
- Modify: `core/factories.py`
- Create: `tests/unit/core/test_factories.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_factories.py`:

```python
"""tests/unit/core/test_factories.py"""
import pytest
from unittest.mock import patch


def test_build_ai_client_returns_litellm_client():
    with patch("config.AI_PROVIDER", "gemini"), \
         patch("config.AI_API_KEY", "test-key"), \
         patch("config.AI_MODEL", "gemini-2.0-flash"), \
         patch("config.AI_BASE_URL", None):
        from core.factories import build_ai_client
        client = build_ai_client()
        from core.litellm_client import LiteLLMClient
        assert isinstance(client, LiteLLMClient)


def test_build_ai_client_raises_without_api_key():
    with patch("config.AI_PROVIDER", "gemini"), \
         patch("config.AI_API_KEY", ""), \
         patch("config.AI_MODEL", "gemini-2.0-flash"), \
         patch("config.AI_BASE_URL", None):
        from core.factories import build_ai_client
        with pytest.raises(ValueError):
            build_ai_client()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/core/test_factories.py -v
```

Expected: FAIL (old factory returns MimoClient/GeminiClient, not LiteLLMClient).

- [ ] **Step 3: Rewrite factories.py**

Replace `core/factories.py` entirely:

```python
"""core/factories.py: 业务对象工厂（DI 入口）。

Phase LiteLLM：统一使用 LiteLLMClient，不再按 provider 分支。
"""
from __future__ import annotations

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_PROVIDER
from core.litellm_client import LiteLLMClient


def build_ai_client() -> LiteLLMClient:
    """根据 config 当前配置构建统一 AI 客户端。

    Returns:
        LiteLLMClient

    Raises:
        ValueError: API key 缺失。
    """
    if not AI_API_KEY:
        raise ValueError(f"AI_API_KEY required (provider={AI_PROVIDER})")

    # 构造 LiteLLM model 格式：provider/model
    model = AI_MODEL or ""
    if "/" not in model:
        # 自动加 prefix：gemini → gemini/xxx, mimo → openai/xxx
        from core.litellm_presets import get_provider_prefix
        prefix = get_provider_prefix(AI_PROVIDER)
        model = f"{prefix}{model}"

    return LiteLLMClient(
        model=model,
        api_key=AI_API_KEY,
        base_url=AI_BASE_URL,
    )


__all__ = ["build_ai_client"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/core/test_factories.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Syntax check**

```bash
python -m py_compile core/factories.py
```

- [ ] **Step 6: Commit**

```bash
git add core/factories.py tests/unit/core/test_factories.py
git commit -m "feat(factories): rewrite build_ai_client to use LiteLLMClient"
```

---

## Task 7: Delete old AI clients

**Files:**
- Delete: `core/mimo_client.py`
- Delete: `core/gemini_client.py`

- [ ] **Step 1: Verify no remaining imports**

```bash
python -c "
import subprocess
result = subprocess.run(['grep', '-r', 'from core.mimo_client', '.'], capture_output=True, text=True)
print('mimo_client imports:', result.stdout or '(none)')
result2 = subprocess.run(['grep', '-r', 'from core.gemini_client', '.'], capture_output=True, text=True)
print('gemini_client imports:', result2.stdout or '(none)')
"
```

Expected: only `core/factories.py` has old imports (already rewritten in Task 6). If other files import them, they need updating first.

- [ ] **Step 2: Delete the files**

```bash
rm core/mimo_client.py core/gemini_client.py
```

- [ ] **Step 3: Run default test suite to verify nothing breaks**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: all tests pass (old client tests were in the deleted files).

- [ ] **Step 4: Commit**

```bash
git add -u core/mimo_client.py core/gemini_client.py
git commit -m "chore: remove MimoClient and GeminiClient (replaced by LiteLLMClient)"
```

---

## Task 8: Add backend AI config endpoints

**Files:**
- Modify: `web/backend/schemas.py` (add AI schemas)
- Modify: `web/backend/routers/users.py` (add 3 endpoints)

- [ ] **Step 1: Add schemas to schemas.py**

Append to `web/backend/schemas.py`:

```python
# ---------------------------------------------------------------------------
# /api/users/{username}/ai-config — AI 供应商配置
# ---------------------------------------------------------------------------
class AIConfigRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    base_url: Optional[str] = None


class AIConfigResponse(BaseModel):
    provider: str
    model: str
    has_api_key: bool
    base_url: Optional[str] = None


class AITestRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    base_url: Optional[str] = None


class AITestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: Optional[float] = None


class AIModelInfo(BaseModel):
    id: str
    name: str
    prefix: str
    needs_base_url: bool
    default_base_url: Optional[str] = None
    models: list[str] = Field(default_factory=list)


class AIModelsResponse(BaseModel):
    providers: list[AIModelInfo] = Field(default_factory=list)
```

- [ ] **Step 2: Add endpoints to users.py**

Add these three endpoints to `web/backend/routers/users.py`. Add the imports at the top:

```python
from web.backend.schemas import (
    # ... existing imports ...
    AIConfigRequest,
    AIConfigResponse,
    AITestRequest,
    AITestResponse,
    AIModelsResponse,
)
```

Add the endpoints after the existing routes:

```python
# ---------------------------------------------------------------------------
# AI 供应商配置
# ---------------------------------------------------------------------------

@router.get("/{username}/ai-models")
async def get_ai_models(username: str):
    """获取所有供应商及其预设模型列表。"""
    from core.litellm_presets import PROVIDERS
    from web.backend.schemas import AIModelInfo

    providers = [AIModelInfo(**p) for p in PROVIDERS]
    return ok_response(AIModelsResponse(providers=providers).model_dump())


@router.post("/{username}/ai-config")
async def save_ai_config(username: str, req: AIConfigRequest):
    """保存 AI 配置到 profile .env。"""
    profile_path = _resolve_profile_path(username)
    if not profile_path:
        return error_response("NOT_FOUND", f"Profile '{username}' not found")

    env_updates = {
        "AI_PROVIDER": req.provider,
        "AI_API_KEY": req.api_key,
        "AI_MODEL": req.model,
    }
    if req.base_url:
        env_updates["AI_BASE_URL"] = req.base_url
    else:
        # 清除 base_url（写空值或删除）
        env_updates["AI_BASE_URL"] = ""

    _update_profile_env(profile_path, env_updates)

    # 如果当前是活跃用户，热切换刷新
    from config import ACTIVE_USER
    if ACTIVE_USER == username.lower():
        from config import switch_user
        switch_user(username)

    return ok_response(
        AIConfigResponse(
            provider=req.provider,
            model=req.model,
            has_api_key=True,
            base_url=req.base_url,
        ).model_dump()
    )


@router.post("/{username}/ai-test")
async def test_ai_connection(username: str, req: AITestRequest):
    """测试 AI 连接。发送一条简单 prompt 验证 API key 和模型。"""
    import time

    from core.litellm_client import LiteLLMClient

    model = req.model
    if "/" not in model:
        from core.litellm_presets import get_provider_prefix
        prefix = get_provider_prefix(req.provider)
        model = f"{prefix}{model}"

    client = LiteLLMClient(
        model=model,
        api_key=req.api_key,
        base_url=req.base_url,
    )

    try:
        started = time.time()
        text, metadata = client.generate_with_instruction(
            "Say 'hello' in one word.",
            instruction="Reply with exactly one word, nothing else.",
        )
        latency_ms = (time.time() - started) * 1000

        if text:
            return ok_response(
                AITestResponse(ok=True, message="连接成功", latency_ms=latency_ms).model_dump()
            )
        else:
            error_msg = metadata.get("error", "未知错误")
            return ok_response(
                AITestResponse(ok=False, message=f"连接失败: {error_msg}").model_dump()
            )
    except Exception as e:
        return ok_response(
            AITestResponse(ok=False, message=f"连接失败: {str(e)}").model_dump()
        )
```

- [ ] **Step 3: Add helper functions**

Add these helper functions to `web/backend/routers/users.py` (if not already present):

```python
def _resolve_profile_path(username: str) -> Optional[str]:
    """解析用户 profile .env 路径。"""
    from config import PROFILES_DIR
    normalized = username.lower()
    path = os.path.join(PROFILES_DIR, f"{normalized}.env")
    if os.path.exists(path):
        return path
    # 兼容大小写
    for entry in os.listdir(PROFILES_DIR) if os.path.isdir(PROFILES_DIR) else []:
        if entry.lower() == f"{normalized}.env":
            return os.path.join(PROFILES_DIR, entry)
    return None


def _update_profile_env(profile_path: str, updates: dict):
    """更新 profile .env 文件中的键值对。"""
    lines = []
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    keys_written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                keys_written.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in keys_written:
            new_lines.append(f"{key}={value}\n")

    with open(profile_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
```

- [ ] **Step 4: Syntax check**

```bash
python -m py_compile web/backend/schemas.py
python -m py_compile web/backend/routers/users.py
```

- [ ] **Step 5: Commit**

```bash
git add web/backend/schemas.py web/backend/routers/users.py
git commit -m "feat(api): add AI config/save/test/models endpoints for users"
```

---

## Task 9: Add frontend AI types

**Files:**
- Modify: `web/frontend/src/api/types.ts`

- [ ] **Step 1: Add AI config types**

Append to `web/frontend/src/api/types.ts`:

```typescript
// ---------------------------------------------------------------------------
// /api/users/{username}/ai-config — AI 供应商配置
// ---------------------------------------------------------------------------
export interface AIConfigRequest {
  provider: string;
  api_key: string;
  model: string;
  base_url?: string;
}

export interface AIConfigResponse {
  provider: string;
  model: string;
  has_api_key: boolean;
  base_url?: string;
}

export interface AITestRequest {
  provider: string;
  api_key: string;
  model: string;
  base_url?: string;
}

export interface AITestResponse {
  ok: boolean;
  message: string;
  latency_ms?: number;
}

export interface AIModelInfo {
  id: string;
  name: string;
  prefix: string;
  needs_base_url: boolean;
  default_base_url?: string;
  models: string[];
}

export interface AIModelsResponse {
  providers: AIModelInfo[];
}
```

- [ ] **Step 2: Type check**

```bash
cd web/frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: no new errors (existing errors are OK).

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/api/types.ts
git commit -m "feat(frontend): add AI config types to api/types.ts"
```

---

## Task 10: Create AIConfigCard component

**Files:**
- Create: `web/frontend/src/components/AIConfigCard.tsx`

- [ ] **Step 1: Write the component**

Create `web/frontend/src/components/AIConfigCard.tsx`:

```tsx
/**
 * AIConfigCard — AI 供应商设置卡片
 * 挂载在 /users 页面，per-user 配置 AI provider/model/key/base_url。
 */
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Eye, EyeOff, CheckCircle2, XCircle } from "lucide-react";
import { apiGet, apiPost } from "../api/client";
import { queryKeys } from "../queries/queryClient";
import type {
  AIModelInfo,
  AIModelsResponse,
  AIConfigRequest,
  AIConfigResponse,
  AITestRequest,
  AITestResponse,
} from "../api/types";

// Design language tokens (Tailwind)
const inputCls =
  "w-full px-3 py-2 border border-border-default rounded-button text-sm " +
  "bg-surface-card text-text-primary placeholder-text-muted " +
  "focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20";

const btnPrimary =
  "bg-accent text-white px-4 py-2 rounded-button text-sm font-medium " +
  "hover:bg-accent-hover transition-colors disabled:opacity-50";

const btnSecondary =
  "bg-accent-soft text-accent-hover px-4 py-2 rounded-button text-sm font-medium " +
  "hover:bg-accent/20 transition-colors disabled:opacity-50";

const cardCls =
  "bg-surface-card rounded-card border border-border-default shadow-card p-5";

interface Props {
  username: string;
  currentProvider?: string;
}

export default function AIConfigCard({ username, currentProvider }: Props) {
  const queryClient = useQueryClient();

  // Form state
  const [provider, setProvider] = useState(currentProvider || "");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);

  // Test result
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; latency?: number } | null>(null);

  // Fetch provider presets
  const { data: modelsData } = useQuery({
    queryKey: ["ai-models", username],
    queryFn: () => apiGet<AIModelsResponse>(`/api/users/${username}/ai-models`),
  });

  const providers = modelsData?.providers || [];
  const selectedProvider = providers.find((p) => p.id === provider);
  const availableModels = selectedProvider?.models || [];

  // When provider changes, suggest first model; only auto-fill base_url for providers that require it
  useEffect(() => {
    if (selectedProvider) {
      if (selectedProvider.needs_base_url && selectedProvider.default_base_url) {
        setBaseUrl(selectedProvider.default_base_url);
      }
      // else: keep empty — user fills in their proxy URL
      if (selectedProvider.models.length > 0) {
        setModel(selectedProvider.models[0]);
      }
    } else {
      setModel("");
      setBaseUrl("");
    }
  }, [provider]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (req: AIConfigRequest) =>
      apiPost<AIConfigResponse>(`/api/users/${username}/ai-config`, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users() });
      setTestResult(null);
    },
  });

  // Test mutation
  const testMutation = useMutation({
    mutationFn: (req: AITestRequest) =>
      apiPost<AITestResponse>(`/api/users/${username}/ai-test`, req),
    onSuccess: (data) => {
      setTestResult({
        ok: data.ok,
        message: data.message,
        latency: data.latency_ms,
      });
    },
    onError: (err: Error) => {
      setTestResult({ ok: false, message: err.message });
    },
  });

  const handleSave = () => {
    saveMutation.mutate({ provider, api_key: apiKey, model, base_url: baseUrl || undefined });
  };

  const handleTest = () => {
    setTestResult(null);
    testMutation.mutate({ provider, api_key: apiKey, model, base_url: baseUrl || undefined });
  };

  return (
    <div className={cardCls}>
      <h3 className="text-base font-medium text-text-primary mb-4">
        AI 供应商设置
      </h3>

      <div className="space-y-3">
        {/* Provider dropdown */}
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">
            供应商
          </label>
          <select
            className={inputCls}
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="">选择供应商...</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Model — combobox: 预设下拉 + 可自由输入 */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              模型
            </label>
            <input
              type="text"
              className={inputCls}
              list="ai-model-suggestions"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={availableModels[0] || "输入模型名称..."}
            />
            <datalist id="ai-model-suggestions">
              {availableModels.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <p className="text-xs text-text-muted mt-1">
              可从预设选择，也可输入自定义模型名
            </p>
          </div>
        )}

        {/* API Key */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              API Key
            </label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                className={inputCls + " pr-10"}
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                onClick={() => setShowKey(!showKey)}
              >
                {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        )}

        {/* Base URL — 所有供应商均可自定义（支持第三方代理/中转） */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              Base URL <span className="text-text-muted">(可选，支持第三方代理)</span>
            </label>
            <input
              type="text"
              className={inputCls}
              placeholder={selectedProvider?.default_base_url || "留空使用官方端点"}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
        )}

        {/* Action buttons */}
        {provider && (
          <div className="flex gap-2 pt-2">
            <button
              className={btnPrimary}
              onClick={handleSave}
              disabled={saveMutation.isPending || !apiKey}
            >
              {saveMutation.isPending ? (
                <Loader2 size={14} className="animate-spin inline mr-1" />
              ) : null}
              保存
            </button>
            <button
              className={btnSecondary}
              onClick={handleTest}
              disabled={testMutation.isPending || !apiKey}
            >
              {testMutation.isPending ? (
                <Loader2 size={14} className="animate-spin inline mr-1" />
              ) : null}
              测试连接
            </button>
          </div>
        )}

        {/* Test result */}
        {testResult && (
          <div
            className={`flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill ${
              testResult.ok
                ? "bg-success-soft text-success"
                : "bg-error-soft text-error"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 size={14} />
            ) : (
              <XCircle size={14} />
            )}
            <span>
              {testResult.message}
              {testResult.latency != null && ` (${Math.round(testResult.latency)}ms)`}
            </span>
          </div>
        )}

        {/* Save result */}
        {saveMutation.isSuccess && (
          <div className="flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill bg-success-soft text-success">
            <CheckCircle2 size={14} />
            <span>配置已保存</span>
          </div>
        )}
        {saveMutation.isError && (
          <div className="flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill bg-error-soft text-error">
            <XCircle size={14} />
            <span>保存失败: {saveMutation.error.message}</span>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check**

```bash
cd web/frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/AIConfigCard.tsx
git commit -m "feat(frontend): add AIConfigCard component with 10-provider support"
```

---

## Task 11: Mount AIConfigCard in Users.tsx

**Files:**
- Modify: `web/frontend/src/pages/Users.tsx`

- [ ] **Step 1: Add import**

Add at the top of `Users.tsx`:

```tsx
import AIConfigCard from "../components/AIConfigCard";
```

- [ ] **Step 2: Mount the card below each user profile**

Find the user card rendering section. After the user info card (where `ai_provider`, `has_momo_token`, `has_ai_key` are displayed), add the `AIConfigCard` for the active user:

```tsx
{/* AI Config Card — only for active user */}
{user.is_active && (
  <AIConfigCard
    username={user.username}
    currentProvider={user.ai_provider}
  />
)}
```

This should be placed inside the user list rendering, after the user info card but still within the map/iteration.

- [ ] **Step 3: Verify in dev server**

```bash
cd web/frontend && npm run dev
```

Open browser, navigate to `/users`. The AI config card should appear below the active user's profile card.

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/pages/Users.tsx
git commit -m "feat(frontend): mount AIConfigCard in Users page for active user"
```

---

## Task 12: Final integration test

- [ ] **Step 1: Run full Python test suite**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: all tests pass.

- [ ] **Step 2: Syntax check all modified Python files**

```bash
python -m py_compile config.py
python -m py_compile core/profile_loader.py
python -m py_compile core/factories.py
python -m py_compile core/litellm_client.py
python -m py_compile core/litellm_presets.py
python -m py_compile web/backend/schemas.py
python -m py_compile web/backend/routers/users.py
```

Expected: no errors.

- [ ] **Step 3: Frontend type check**

```bash
cd web/frontend && npx tsc --noEmit --pretty
```

Expected: no new errors.

- [ ] **Step 4: Start web server and smoke test**

```bash
python scripts/start_web.py --dev
```

Navigate to `/users` in browser:
1. Verify AI config card appears for active user
2. Select a provider → model dropdown populates
3. Fill in API key → click "测试连接" → verify result badge appears
4. Click "保存" → verify success message
5. Switch to another user → verify card updates

- [ ] **Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: integration test fixes for LiteLLM migration"
```

---

## Self-Review Checklist

After writing the plan, verify against spec:

- [x] **Spec coverage:** All 4 spec sections covered (Backend, Frontend, Error Handling, Testing)
- [x] **10 providers:** All 10 providers from spec table implemented in `litellm_presets.py`
- [x] **Frontend design language:** CSS classes match unified design spec tokens
- [x] **3 API endpoints:** `/ai-config`, `/ai-test`, `/ai-models` all implemented
- [x] **Legacy migration:** `MIMO_API_KEY` → `AI_API_KEY`, `GEMINI_API_KEY` → `AI_API_KEY`, `mimo` → `openai/` prefix
- [x] **Per-user config:** Settings saved to profile `.env` per user
- [x] **Test connection:** Frontend "测试连接" button calls backend test endpoint
- [x] **Model flexibility:** Combobox (input + datalist) — users can pick presets OR type custom model names
- [x] **Base URL for all:** Every provider shows Base URL field (supports third-party proxies)
- [x] **No placeholders:** All steps have complete code blocks
