# J.A.R.V.I.S. V4 — Complete Project Implementation Status

> **Last Updated:** April 15, 2026  
> **Server:** FastAPI + Uvicorn (`uvicorn api.app:app --reload --port 8000`)  
> **DB:** SQLite (`jarvis.db`) + ChromaDB (in-memory/on-disk vector store)  
> **LLM:** Google Gemini 2.5 (via `google-genai`)  
> **Status:** ✅ Live & Operational

---

## Project Directory Structure

```
JARVIS/
├── api/                        # FastAPI server, routes, middleware
│   ├── app.py                  # Application entry point, startup, /api/stats
│   ├── middleware/
│   │   └── logger.py           # Request/response logging middleware
│   └── routes/
│       ├── chat.py             # /chat POST endpoint (user → agent loop)
│       └── tools.py            # /tools GET endpoint (list available tools)
├── core/                       # Low-level infrastructure utilities
│   ├── cache.py                # LRU LLM response cache + tool result cache
│   ├── config.py               # Pydantic BaseSettings (.env loader)
│   ├── errors.py               # AgentError, ConfigurationError classes
│   ├── llm_parser.py           # Structured output parser for Gemini responses
│   ├── observability.py        # Timing/performance hooks
│   ├── schemas.py              # Pydantic models for request/response contracts
│   ├── state_backend.py        # In-memory or Redis ephemeral state manager
│   └── tokenizer.py            # Token counting for context window management
├── orchestration/              # The "Brain" — agent loop and planning
│   ├── context_assembler.py    # Merges memory, facts, tools into LLM prompt
│   ├── llm_router.py           # Routes requests to the correct Gemini API call
│   ├── loop_guard.py           # Prevents infinite loops (max iterations, cost)
│   ├── message_window.py       # Sliding window of recent messages for context
│   ├── planner.py              # High-level task decomposition into steps
│   ├── react_loop.py           # Core ReAct (Reason + Act) iterative agent loop
│   ├── semantic_extractor.py   # Extracts user facts from conversation text
│   └── task_runner.py          # Async task executor with status tracking
├── tools/                      # All tool plugins JARVIS can execute
│   ├── registry.py             # @tool() decorator, auto-schema generation
│   ├── executor.py             # Safe execution wrapper with timeout + sandbox
│   ├── sandbox.py              # Subprocess isolation for code execution
│   ├── schemas.py              # ToolCall, ToolResult Pydantic models
│   └── definitions/            # Individual tool implementations
│       ├── calculator.py       # Arithmetic & math evaluation tool
│       ├── calendar.py         # Google Calendar API integration stub
│       ├── email.py            # Email composition/send stub
│       ├── file_ops.py         # File read/write/list/delete operations
│       ├── notion.py           # Notion API integration stub
│       ├── python_exec.py      # Sandboxed Python execution engine
│       ├── slack.py            # Slack messaging integration stub
│       └── web_search.py       # Web search and URL scraping tool
├── models/                     # Persistence layer
│   ├── database.py             # SQLite async init, connection lifecycle
│   ├── embeddings.py           # ChromaDB vector storage for semantic memory
│   ├── session_store.py        # Episodic session serialization (SQLite)
│   └── user_facts.py           # Persistent user fact CRUD (SQLite)
├── dashboard/
│   └── index.html              # Full single-page Tactile Futurism UI
├── tests/                      # Unit & integration test suite
├── .env                        # API keys, feature flags
├── jarvis.db                   # SQLite persistent database
├── setup_project.py            # One-shot project scaffolding script
├── README.md                   # Original project documentation
├── QUICK_REFERENCE.md          # CLI/API usage quick reference
└── IMPLEMENTATION_COMPLETE.md  # Phase completion checklist
```

---

## 1. Entry Point: `api/app.py`

The root of the server. Handles the full ASGI lifecycle.

| Feature | Detail |
|---|---|
| **Framework** | FastAPI with Uvicorn ASGI runner |
| **CORS** | Wildcard allowed for local dashboard access |
| **Middleware** | `BaseHTTPMiddleware` wrapping the custom logger |
| **Startup Hook** | Loads all tools from registry, initializes SQLite DB, initializes state backend |
| **Error Handlers** | `ConfigurationError` → 503, `AgentError` → 500 |
| **`/api/stats`** | Serves live `psutil` CPU, RAM, uptime, and thermal data to the dashboard |
| **`/dashboard`** | Serves `dashboard/index.html` as a `FileResponse` |
| **Static Assets** | Mounts `/assets` from `dashboard/assets/` |
| **Telemetry** | `_START_TIME = time.time()` captured at import to power dashboard uptime clock |

---

## 2. Orchestration Engine (`orchestration/`)

The most sophisticated layer — the "Brain" of the system.

### `react_loop.py` — Core Agent Loop
The primary inference engine. Implements the **ReAct (Reason + Act)** pattern:
1. Assembles context from memory, facts, and conversation window.
2. Sends to Gemini via `llm_router.py`.
3. Parses the response: either a **text reply** or a **tool call**.
4. If a tool call: dispatches to `executor.py`, captures the result, appends to context, and loops.
5. Terminates on `FINAL_ANSWER` signal or max iteration limit (enforced by `loop_guard.py`).

### `planner.py` — Task Decomposition
Breaks complex user goals (e.g., "Schedule a meeting and notify the team on Slack") into sequential, trackable sub-tasks before entering the ReAct loop.

### `context_assembler.py` — Prompt Construction
Merges all memory layers, recent messages, and available tool schemas into the final structured prompt sent to Gemini.

### `semantic_extractor.py` — Fact Mining
After every conversation turn, analyses the exchange and extracts persistent facts about the user (e.g., "prefers Python", "based in India") for long-term personalization.

### `message_window.py` — Context Management
Maintains a rolling window of the last N messages, preventing context window overflow during long sessions.

### `loop_guard.py` — Safety Circuit
Tracks iteration count and estimated token consumption, halting the agent loop if dangerous thresholds are reached.

### `task_runner.py` — Async Execution
Wraps `react_loop` invocations as background async tasks with status tracking for long-running operations.

---

## 3. Core Infrastructure (`core/`)

| File | Purpose |
|---|---|
| `config.py` | Loads all settings from `.env` using **Pydantic `BaseSettings`**. Variables include: `GEMINI_API_KEY`, `enable_episodic_memory`, `enable_semantic_memory`, Redis settings, etc. |
| `cache.py` | Dual LRU cache: `llm_cache` (caches identical LLM prompts → responses) and `tool_cache` (caches deterministic tool results). Reports hit rates to `/api/stats`. |
| `state_backend.py` | Pluggable backend: in-memory dict by default, Redis if configured. Stores ephemeral agent state (current task, tool call count). |
| `errors.py` | Two clean exception classes: `AgentError` (agent-level failures) and `ConfigurationError` (missing keys, wrong config). |
| `llm_parser.py` | Parses raw Gemini API responses into structured `ToolCall` or `TextReply` Pydantic objects. Handles malformed JSON gracefully. |
| `tokenizer.py` | Estimates token count for messages to enforce context window limits. |
| `schemas.py` | Shared Pydantic models for API contracts: `ChatRequest`, `ChatResponse`, `AgentState`. |
| `observability.py` | Performance timing decorators and hooks for profiling bottlenecks. |

---

## 4. Memory System (`models/`)

A three-tier persistent memory pipeline.

### Semantic Memory — `embeddings.py` (ChromaDB)
- Stores semantically encoded **user facts** in a vector database.
- On each query, performs **cosine similarity search** to surface the most relevant facts.
- Facts are extracted by `semantic_extractor.py` after each conversation turn.
- Example facts stored: `"User works in Python"`, `"User prefers dark mode"`.

### Episodic Memory — `session_store.py` (SQLite)
- Serializes complete session records (full request → reasoning → tool calls → response chain) to `jarvis.db`.
- Allows JARVIS to recall the exact history of past sessions on demand.

### Persistent User Facts — `user_facts.py` (SQLite)
- CRUD layer for user fact storage.
- Separate from embeddings — provides a structured relational view of extracted facts.

### Database Lifecycle — `database.py`
- Manages the async SQLite connection pool using `aiosqlite`.
- `init_db()` creates all tables on startup; `close_db()` tears down cleanly on shutdown.

---

## 5. Tool System (`tools/`)

A fully extensible plugin architecture with sandboxed execution.

### `registry.py` — Tool Registry
- The `@tool()` decorator auto-generates a **JSON schema** from Python function signatures and docstrings in the format expected by the Gemini function-calling API.
- `load_all_tools()` called at startup scans all `definitions/` and registers them globally.
- `list_tools()` returns all registered schemas for the `/tools` API and the `/api/stats` tool count.

### `executor.py` — Safe Execution Wrapper
- Wraps every tool call with: timeout enforcement, exception catching, and result normalization into `ToolResult` objects.

### `sandbox.py` — Code Isolation
- Used specifically by `python_exec.py` to run untrusted Python code in a subprocess with restricted imports and resource limits.

### Implemented Tools

| Tool File | Tool Name | Status | Description |
|---|---|---|---|
| `calculator.py` | `calculate` | ✅ Live | Evaluates arithmetic and math expressions safely |
| `python_exec.py` | `execute_python` | ✅ Live | Runs sandboxed Python snippets, captures stdout/stderr |
| `file_ops.py` | `read_file`, `write_file`, `list_directory`, `delete_file` | ✅ Live | Full filesystem CRUD within allowed paths |
| `web_search.py` | `web_search`, `scrape_url` | ✅ Live | DuckDuckGo search and URL content fetching |
| `calendar.py` | `create_event`, `list_events` | 🔧 Stub | Google Calendar API — requires OAuth token |
| `email.py` | `send_email` | 🔧 Stub | SMTP email composition — requires credentials |
| `slack.py` | `send_slack_message` | 🔧 Stub | Slack SDK — requires Bot Token + Channel ID |
| `notion.py` | `create_notion_page` | 🔧 Stub | Notion API — requires Integration Token |

---

## 6. API Routes (`api/routes/`)

### `chat.py` — `/chat` (POST)
- Accepts `{"message": "..."}` from the dashboard.
- Invokes the agent via `task_runner` → `react_loop`.
- Returns `{"response": "..."}` to the UI.

### `tools.py` — `/tools` (GET)
- Returns a JSON list of all registered tool names and descriptions.
- Used for developer reference and diagnostics.

---

## 7. Dashboard UI (`dashboard/index.html`)

A fully self-contained, production-ready single-page application.

### Theme Engine
A zero-flicker CSS variable system with two fully separated palettes:

| Token | Day (Cream/Beige) | Night (Charcoal Obsidian) |
|---|---|---|
| `--bg-main` | `#F5EFE6` | `#0a0a0a` |
| `--bg-panel` | `#EDE3D2` | `#121212` |
| `--bg-input` | `#F8F2E8` | `#161616` |
| `--accent` | `#2563eb` | `#3b82f6` |
| `--text-primary` | `#3E3A36` | `#f8fafc` |
| `--border` | `#DDD2C3` | `rgba(255,255,255,0.05)` |

### UI Components

| Component | Description |
|---|---|
| **Top Navigation** | JARVIS logo, PRO_CORE 2.2 badge, Neural Link status dot, live clock, Day/Night toggle |
| **Left Dock** | Icon-strip sidebar with Reload, History, Download, Settings icons |
| **Hardware Telemetry Cards** | 4 cards: Control Load (CPU %), Kernel Thermal (°C), Memory Logic (GB), Cycle Uptime |
| **Synchronicity Core** | Multi-layered kinetic SVG orbital rings, volumetric glowing core, orbiting data satellite |
| **Overlay Toggles** | 3 iOS-style toggles: DEF_PROT, NAV_SYNC, NLP_LINK |
| **Activity Stream** | Auto-scrolling log of all system events with timestamps |
| **Chat Engine** | Full messaging interface with typewriter-effect responses and pulse indicator |
| **Execute Bar** | Styled input with a tactile command button |

### Live Telemetry Engine (JavaScript)
- **5-second API polling loop** pulls fresh data from `/api/stats`.
- **1-second client-side clock** client-interpolates the Cycle Uptime between polls for smooth display.
- **Server drift correction** re-syncs the local clock from backend truth every 5 seconds.
- **Dynamic progress bars** animate CPU/Memory bars and apply color classes (`accent-amber`, `accent-red`) at thresholds.
- **Bit-Rate flanks** and **latency counter** in the Synchronicity Core randomize per poll cycle.

---

## 8. Pending / Next Phase

| Area | Status | Notes |
|---|---|---|
| Calendar integration | 🔧 Stub | Needs Google OAuth flow |
| Slack integration | 🔧 Stub | Needs Slack Bot Token |
| Notion integration | 🔧 Stub | Needs Notion API key |
| Email tool | 🔧 Stub | Needs SMTP credentials |
| FastAPI `lifespan` migration | ⚠️ Pending | `on_event` is deprecated in FastAPI 0.95+ |
| Real M1 thermal reading | ⚠️ Partial | Uses jittered proxy; `powermetrics` integration possible |
| Activity Stream → real tool events | ⚠️ Pending | Currently logs link interrupts; should stream tool execution in real-time |
| Test coverage | ⚠️ Partial | `tests/` directory exists; coverage needs expansion |
