# Jarvis — AI Agent

A production-grade autonomous AI agent built on Google Gemini. Understands natural language, reasons across multiple steps, executes real tools, and returns structured responses — not just chat.

---

## What it does

Jarvis accepts a plain English message and autonomously decides how to answer it — including using tools, chaining multiple steps, and handling failures gracefully. It is not a wrapper around a chatbot. It is a ReAct-loop agent with full observability, timeout protection, and a sandboxed tool execution model.

**Example interactions:**

- `"What is the square root of 1764?"` → uses calculator tool, returns 42
- `"Search for what FastAPI is and summarize it"` → searches the web, synthesizes an answer
- `"Write a Python script that prints fibonacci numbers to hello.py"` → writes the file to disk
- `"Execute this code: print([x**2 for x in range(10)])"` → runs in sandbox, returns output

---

## Architecture overview

```
User message
     │
     ▼
Interface layer (FastAPI)
     │
     ▼
Task runner  ──── global timeout (200s)
     │
     ▼
ReAct loop
  ├── THINK  (LLM reasons, produces JSON action)
  ├── ACT    (tool executor runs the chosen tool)
  └── OBSERVE (result injected back into context)
     │
     ▼
Response returned with steps_taken, tools_used, status
```

**Key design properties:**

- Loop is bounded: max 12 steps, max 2 retries per tool
- Loop is observable: every step is logged with trace_id
- Loop is safe: stuck loops detected via LoopGuard (identical calls, no-progress, same-tool streak)
- Tools are sandboxed: read / write / destructive permission tiers
- Context is managed: message history truncated to fit token budget

---

## Project structure

```
JARVIS/
├── api/
│   ├── app.py                  # FastAPI app, middleware, startup
│   ├── middleware/
│   │   └── logger.py           # Structured request/response logging
│   └── routes/
│       ├── chat.py             # POST /chat, the main endpoint
│       └── tools.py            # GET /tools, POST /tools/{name}/approve
│
├── orchestration/
│   ├── task_runner.py          # Entry point, global timeout wrapper
│   ├── react_loop.py           # Think → Act → Observe loop
│   ├── context_assembler.py    # Builds prompt from history + tools
│   ├── llm_router.py           # Model selection + Gemini API call
│   ├── loop_guard.py           # Stuck loop detection
│   └── message_window.py      # Message history truncation
│
├── tools/
│   ├── registry.py             # @register_tool decorator + lookup
│   ├── executor.py             # Permission check + execution + retry
│   ├── sandbox.py              # Permission tier enforcement
│   ├── schemas.py              # ToolSpec, ToolCallRequest, ToolCallResult
│   └── definitions/
│       ├── calculator.py       # Math expression evaluator (sympy)
│       ├── web_search.py       # DuckDuckGo search
│       ├── file_ops.py         # file_read + file_write (sandboxed to /tmp/jarvis_files)
│       └── python_exec.py      # Python code execution (subprocess sandbox)
│
├── core/
│   ├── config.py               # All constants, reads from .env
│   ├── schemas.py              # Shared Pydantic models
│   ├── observability.py        # Structured JSON logger
│   ├── errors.py               # Exception hierarchy
│   └── llm_parser.py           # Robust JSON parsing for LLM output
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── .env                        # API keys and config (never commit this)
├── setup_project.py            # One-time scaffold script
└── README.md
```

---

## Quickstart

### Prerequisites

- macOS or Linux
- Python 3.11+
- A Google Gemini API key ([get one at aistudio.google.com](https://aistudio.google.com))

### Setup

```bash
# Clone or create the project folder
cd JARVIS

# Activate virtual environment
source .venv/bin/activate

# Install dependencies (if not already done)
pip install fastapi uvicorn google-genai httpx pydantic-settings \
            sympy aiofiles pytest pytest-asyncio

# Add your API key to .env
echo 'GEMINI_API_KEY=AIzaSy...' > .env
echo 'APP_ENV=development' >> .env
echo 'LOG_LEVEL=INFO' >> .env

# Start the server
uvicorn api.app:app --reload --port 8000
```

You should see:

```
INFO: Application startup complete.
INFO: Uvicorn running on http://127.0.0.1:8000
```

---

## API reference

### `POST /chat`

Send a message to the agent.

**Request:**
```json
{
  "message": "What is 17 multiplied by 23?",
  "session_id": "optional-session-id"
}
```

**Response:**
```json
{
  "response": "17 multiplied by 23 is 391.",
  "session_id": "sess_a1b2c3d4",
  "trace_id": "tr_e5f6a7b8c9d0",
  "steps_taken": 1,
  "tools_used": ["calculator"],
  "status": "completed"
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `completed` | Agent reached a final answer normally |
| `timeout` | Task exceeded 200s global limit |
| `max_steps_exceeded` | Loop hit 12-step ceiling |
| `no_progress` | 4 consecutive steps with no useful output |
| `identical_calls` | Same tool+params repeated 3 times |
| `same_tool_streak` | Same tool called 5 times in a row |
| `auth_failure` | Tool authentication failed, escalated |

---

### `GET /tools`

List all registered tools and their permission tiers.

```bash
curl http://localhost:8000/tools
```

---

### `POST /tools/{tool_name}/approve`

Approve a write-tier tool for a user (required before first use).

```bash
curl -X POST http://localhost:8000/tools/file_write/approve \
  -H "Content-Type: application/json" \
  -d '{"user_id": "default_user"}'
```

---

### `GET /health`

```bash
curl http://localhost:8000/health
# {"status": "ok", "tools_loaded": 5}
```

---

## Tools

### calculator
- **Tier:** read (no approval needed)
- **What it does:** Evaluates math expressions using sympy
- **Examples:** `sqrt(144)`, `integrate(x**2, x)`, `2**10`

### web_search
- **Tier:** read (no approval needed)
- **What it does:** Searches DuckDuckGo, returns up to 5 results
- **Rate limit:** 20 requests/minute

### file_read
- **Tier:** read (no approval needed)
- **What it does:** Reads a text file from `/tmp/jarvis_files/`
- **Safety:** Path traversal blocked

### file_write
- **Tier:** write (requires one-time approval per user)
- **What it does:** Writes text to a file in `/tmp/jarvis_files/`
- **Approve:** `POST /tools/file_write/approve`

### python_exec
- **Tier:** destructive (requires confirmation every time)
- **What it does:** Executes a Python snippet in a sandboxed subprocess
- **Restrictions:**
  - No file I/O (`open()` blocked)
  - No network (`import requests`, `import socket` blocked)
  - No OS access (`import os`, `import sys` blocked)
  - No meta-execution (`eval()`, `exec()`, `compile()` blocked)
  - 10s timeout, 4000 char output cap
  - Must use `print()` to return results

---

## Configuration

All values are set in `.env` and read by `core/config.py`.

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | required | Your Google Gemini API key |
| `APP_ENV` | `development` | Environment name |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `TOOL_TIMEOUT_SECONDS` | `10` | Per-tool execution timeout |
| `MAX_RETRIES_PER_TOOL` | `2` | Max retries on tool failure |
| `MAX_STEPS` | `12` | Max ReAct loop iterations |
| `GLOBAL_TIMEOUT_SECONDS` | `200` | Hard task time limit |
| `RETRY_BUDGET_THRESHOLD` | `0.80` | Disable retries at 80% of global budget |

**Timeout hierarchy:**

```
tool call        ≤ 10s     hard cap per execution
retry delays     1s, 5s    between retries
react loop       ≤ 12 steps
global task      ≤ 200s    asyncio.wait_for in task_runner
```

Worst case with retries: `10s × 3 × 12 + 72s backoff = 432s` — but the 80% budget guard disables retries at 160s, capping real-world worst case well under 200s.

---

## Model routing

Jarvis routes between two Gemini models based on task complexity:

| Model | Used when |
|-------|-----------|
| `gemini-2.0-flash` | Prompt < 15,000 tokens AND task type is general/math/simple |
| `gemini-2.0-pro-exp` | Prompt ≥ 15,000 tokens OR task type is research/coding/analysis |

This cuts API costs by ~90% on simple tasks without sacrificing quality on hard ones.

---

## Observability

Every event is logged as structured JSON to stdout. Each task gets a `trace_id` that ties all events together.

**Example log stream for a single task:**

```json
{"ts":"2026-04-14T10:32:01Z","level":"INFO","event":"api.request","method":"POST","path":"/chat","trace_id":"tr_abc123"}
{"ts":"2026-04-14T10:32:01Z","level":"INFO","event":"llm.call_start","model":"gemini-2.0-flash","trace_id":"tr_abc123"}
{"ts":"2026-04-14T10:32:02Z","level":"INFO","event":"llm.call_done","latency_ms":820,"tokens_in":312,"tokens_out":64}
{"ts":"2026-04-14T10:32:02Z","level":"INFO","event":"loop.tool_call","tool":"calculator","step":1}
{"ts":"2026-04-14T10:32:02Z","level":"INFO","event":"tool.success","tool":"calculator","latency_ms":3}
{"ts":"2026-04-14T10:32:03Z","level":"INFO","event":"loop.final_answer","steps":1}
```

To debug any failed task, filter logs by `trace_id`. You get the full execution trace: every LLM call, every tool invocation, every retry, and the exact exit reason.

---

## Safety model

### Permission tiers

| Tier | Examples | Behaviour |
|------|---------|-----------|
| `read` | web_search, calculator, file_read | Always allowed, no confirmation |
| `write` | file_write, calendar_create | Blocked until user approves once |
| `destructive` | python_exec, file_delete | Blocked, always requires confirmation |

### Loop safety

The `LoopGuard` detects and terminates stuck loops:

- **IDENTICAL_CALLS** — same tool + same parameters 3 times in a row
- **NO_PROGRESS** — 4 consecutive steps with failed or empty tool output
- **SAME_TOOL_STREAK** — same tool called 5 times in a row regardless of params
- **MAX_STEPS** — hard ceiling of 12 steps

### Subprocess safety (python_exec)

- Static analysis blocks dangerous imports before execution
- Runs in a separate process with a stripped environment
- `SIGTERM` → 1s grace period → `SIGKILL` on timeout or cancellation
- Zombie process prevention via `proc.communicate()` after kill

---

## Smoke tests

Run these after starting the server to verify everything works:

```bash
# 1. Health
curl http://localhost:8000/health

# 2. Calculator (read tool, no approval)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the square root of 1764?"}'

# 3. Web search (read tool, no approval)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for what Python asyncio is"}'

# 4. File write (approve first, then write)
curl -X POST http://localhost:8000/tools/file_write/approve \
  -H "Content-Type: application/json" \
  -d '{"user_id": "default_user"}'

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Write hello world to a file called test.txt"}'

# Verify the file was created
cat /tmp/jarvis_files/test.txt
```

---

## Roadmap

### MVP (current)
- [x] ReAct loop with full safety guards
- [x] 4 tools: calculator, web_search, file_read, file_write, python_exec
- [x] Structured logging with trace_id
- [x] Global + per-tool timeout hierarchy
- [x] Permission tier model
- [x] Robust JSON parsing with repair fallback
- [x] Message history truncation

### V2 — Memory
- [ ] SQLite session persistence
- [ ] Episodic memory (pgvector similarity search)
- [ ] Semantic memory (user facts, preferences)
- [ ] Post-session memory consolidation

### V3 — Breadth
- [ ] LLM response caching (Redis)
- [ ] Tool output caching
- [ ] Proactive insight generation
- [ ] Voice interface (Whisper STT + ElevenLabs TTS)
- [ ] Web dashboard for task history

### V4 — Advanced
- [ ] Task planner (goal → subtask DAG)
- [ ] Parallel tool execution
- [ ] Multi-user support with isolated memory
- [ ] Real-time data source subscriptions

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI |
| ASGI server | Uvicorn |
| LLM | Google Gemini (2.0 Flash + 2.0 Pro) |
| Math | SymPy |
| HTTP client | HTTPX |
| Config | Pydantic Settings |
| File I/O | aiofiles |
| Testing | pytest + pytest-asyncio |

---

## Contributing

1. Always activate the venv before working: `source .venv/bin/activate`
2. Run from the project root so imports resolve correctly
3. Every new tool goes in `tools/definitions/` and registers via `@register_tool`
4. Every change to timeout constants must satisfy the invariant in `core/config.py`
5. Logs go to stdout as JSON — never use `print()` for debugging in production code, use `get_logger(__name__)`

---

## License

MIT