# Tool Calling Behavior (OpenAI-Compatible)

This document describes how the Manager API normalizes and validates tool calls for OpenAI-compatible clients (Cline, Cursor, Kilo, OpenAI SDK).

## ✅ Supported Endpoints

- `POST /proxy/chat/completions`
- `POST /proxy/responses`

## ✅ Normalization Rules

### Non‑stream responses
When tool calls are present in the upstream response:

- `tool_calls` must be a list of objects with:
  - `id` (string)
  - `type` = `function`
  - `function` with:
    - `name` (string)
    - `arguments` (JSON string)
- Valid JSON argument strings are preserved as‑is.
- Invalid argument strings are wrapped as `{"input": "..."}`.
- Tool calls with missing or invalid arguments are dropped (logged + counted).
- Empty `{}` arguments are only emitted when the model explicitly sends empty arguments.

### Streamed responses
Streaming tool call deltas are accumulated across chunks. The Manager only emits tool calls on `finish_reason=tool_calls`.

- Argument fragments are concatenated across chunks.
- When finished, arguments are validated as JSON.
- If invalid, arguments are wrapped as `{"input": "..."}`.
- Empty `{}` arguments are only emitted when the model explicitly sends empty arguments.
- Invalid tool-call structures are dropped (logged + counted).

### Kilo compatibility
The validator accepts Kilo’s flexible formats:

- `arguments` may be a JSON string or an already-parsed object.
- Kilo shorthand calls with top-level `name`/`arguments` are accepted in streaming validation.
- Mixed argument types in the same `tool_calls` array are supported.

## 🔍 Debug Endpoint

Recent raw tool-call chunks are captured for diagnosis.

- **Endpoint:** `GET /proxy/debug/tool-calls`
- **Headers:** `X-Admin-Key: <APISIX_ADMIN_KEY>`
- **Query Params:**
  - `limit` (default: 50, max: `TOOL_CALL_DEBUG_MAX`)
  - `clear` (true/false)

Example:

```
GET /proxy/debug/tool-calls?limit=20&clear=true
X-Admin-Key: vllm-platform-admin-key-2026
```

## 📊 Metrics

Prometheus counters:

- `manager_tool_calls_malformed_total{stage,reason}`
- `manager_tool_calls_fallback_total{stage,action}`

Use `GET /metrics` for scrape.

## ⚙️ Config

- `TOOL_CALL_DEBUG_MAX` (default: 200)

## ✅ Testing Checklist

Validate both stream + non‑stream responses with:

- Cline (stream + non‑stream)
- Cursor (stream + non‑stream)
- Kilo (stream + non‑stream)
- OpenAI SDK (node + python)

### Suggested Tests

1. **Simple tool call** with valid JSON args
2. **Chunked arguments** (streaming)
3. **Empty arguments** explicitly sent by model
4. **Malformed argument fragments** (expect wrapped `input`)
5. **Missing arguments** (expect tool call dropped + metric increment)

## ✅ Example (Non‑stream)

Request:

```
POST /proxy/chat/completions
{
  "model": "...",
  "messages": [...],
  "tools": [ ... ]
}
```

Response snippet:

```
"tool_calls": [
  {
    "id": "call_abc123",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"path\":\".\",\"regex\":\".*\",\"file_pattern\":\"*.*\"}"
    },
    "index": 0
  }
]
```
