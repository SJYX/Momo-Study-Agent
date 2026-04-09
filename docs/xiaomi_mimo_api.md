# Xiaomi Mimo API Documentation

这份文档汇集了最新的 Xiaomi Mimo API 官方结构指南，作为我们 `feature/mvp-script` 以及未来自动化工程中的核心对接参考。

---

## 1. OpenAI API 兼容规范

完全兼容标准 OpenAI Client 生态。你可以无缝使用 `requests` 或是官方 `openai` Python SDK。

### **核心请求端点 (Endpoint)**
- **接口地址**: `https://api.xiaomimimo.com/v1/chat/completions`
- **请求方法**: `POST`

### **身份认证 (Headers)**
支持以下两种主流认证方式，二选一即可：
**方式一：指定 API-Key 字段认证**
```http
api-key: $MIMO_API_KEY
Content-Type: application/json
```
**方式二：标准的 Bearer Token 认证**
```http
Authorization: Bearer $MIMO_API_KEY
Content-Type: application/json
```

### **请求参数列表 (Request Body)**

| 参数 | 类型 | 必选 | 默认值 | 描述简介 |
| :--- | :--- | :--- | :--- | :--- |
| `model` | string | **✅ 是** | - | 模型名称。可选：`mimo-v2-pro` / `mimo-v2-omni` / `mimo-v2-tts` / `mimo-v2-flash`。 |
| `messages` | array | **✅ 是** | - | 对话历史。支持的角色：`system` (不建议取代 `developer`), `developer`, `user`, `assistant`, `tool`。 |
| `max_completion_tokens` | integer | 否 | 见下文 | 对话补全最大生成 token 限制（包含推理时间 token）。范围 `[0, 131072]`。`mimo-v2-flash` 默认 65536，`mimo-v2-pro` 默认 131072。 |
| `temperature` | number | 否 | 见下文 | 输出随机度 `[0, 1.5]`。`flash` 默认 0.3（较稳定），`pro`/`omni` 默认 1.0（更富创造性）。 |
| `top_p` | number | 否 | 0.95 | 核采样阈值 `[0.01, 1.0]`。（注意：不建议与 `temperature` 同时调整） |
| `thinking` | object | 否 | 见下文 | **高度重要**：控制是否开启思维链。例如：`{"type": "enabled"}`。`pro`/`omni` 默认开启，`flash` 默认关闭。 |
| `response_format` | object | 否 | text | 指定模型输出格式。可用 `{"type": "json_object"}` 强制输出 JSON。不支持 tts。 |
| `stream` | boolean | 否 | false | 是否启用流式输出 (Server-Sent Events) 实效打字机效果。 |
| `tools` | array | 否 | - | 支持 `function` 函数调用或 `web_search` 形式的外部工具列表。 |
| `tool_choice` | string | 否 | auto | 控制工具调用的激进程度（目前仅支持 `auto` 等同规则）。 |
| `stop` | str/array | 否 | null | 停止词序列数组，最多设置 4 个屏蔽或切断触发词。 |
| `audio` | object | 否 | - | 语音生成参数。目前仅 `mimo-v2-tts` 模型可用，比如指定 `{"format": "wav", "voice": "default_zh"}`。 |
| `frequency_penalty` | number | 否 | 0 | 频率惩罚参数 `[-2.0, 2.0]`。 |
| `presence_penalty` | number | 否 | 0 | 存在惩罚参数 `[-2.0, 2.0]`。 |

---

## 2. 响应体解析对象

### **非流式输出对象 (Stream = false)**
一次性完整回传结果的 JSON 结构规范：

```json
{
  "id": "响应的唯一UUID",
  "object": "chat.completion",
  "created": 1713210332,
  "model": "mimo-v2-pro",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "模型生成的最终纯文本内容...",
        "reasoning_content": "这里是模型大段的深层推理和思考过程（如果开启了 thinking）...",
        "tool_calls": [],
        "annotations": [] // 如果用了 web_search 或者联网功能，这里会有来源链接
      },
      "finish_reason": "stop" // 停止原因，如 stop, length (过长), tool_calls (主动调用函数了)
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 60,
    "total_tokens": 72,
    "completion_tokens_details": {
      "reasoning_tokens": 30 // 模型花了多少字去思考 (不展现在最终content里)
    },
    "web_search_usage": {
        "tool_usage": 1,
        "page_usage": 5
    }
  }
}
```

### **流式分块输出对象 (Stream = true)**
随着网络逐步传回的数据块格式，使用 `chunk` 对象：

- `object` 会变为 `"chat.completion.chunk"`。
- 不再返回完整的 `message` 对象，而是使用 `choices.delta`。
- `delta` 中同样包含被切片的 `content` 核心字符以及 `reasoning_content` 推理过程流。
- 直到最后一块 Chunk 送达前，`finish_reason` 都是 `null`。

---

> [!IMPORTANT] 
> **研发与多轮记忆注意提示 (Reasoning Memory)**
> 
> 在“思考模式 (thinking=enabled)”下的多轮工具调用过程中，模型返回 `tool_calls` 的前提是它在脑内做了深度推演，即同时返回了 `reasoning_content`。**若要在下一次请求时继续这段具有记忆的对话上下文，必须在下次发出的 `messages` 数组里，原封不动地保留所有历史回合的 `reasoning_content` 作为助理消息发过去**，否则上下文表现会降级。
