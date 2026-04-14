"""FastAPI application — startup/shutdown lifecycle, middleware, routes,
and static file serving for the Phase 3 web dashboard.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path

from api.middleware.logger import logging_middleware
from api.routes.chat import router as chat_router
from api.routes.tools import router as tools_router
from core.errors import AgentError, ConfigurationError
from models.database import init_db, close_db
from tools.registry import load_all_tools

app = FastAPI(title="Jarvis", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(BaseHTTPMiddleware, dispatch=logging_middleware)


@app.exception_handler(ConfigurationError)
async def configuration_error_handler(request: Request, exc: ConfigurationError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )


@app.on_event("startup")
async def startup():
    load_all_tools()
    await init_db()

    # Initialise the state backend (Redis or in-memory)
    from core.state_backend import get_backend
    await get_backend()


@app.on_event("shutdown")
async def shutdown():
    await close_db()

    from core.state_backend import close_backend
    await close_backend()


# ── API routes ──
app.include_router(chat_router)
app.include_router(tools_router)


# ── Dashboard API routes ──
@app.get("/api/stats")
async def api_stats():
    """Return live system stats for the dashboard."""
    from tools.registry import list_tools
    from core.cache import llm_cache, tool_cache
    from core.config import settings
    return {
        "tools_loaded": len(list_tools()),
        "llm_cache":    llm_cache.stats(),
        "tool_cache":   tool_cache.stats(),
        "settings": {
            "max_steps":               settings.max_steps,
            "global_timeout_seconds":  settings.global_timeout_seconds,
            "enable_episodic_memory":  settings.enable_episodic_memory,
            "enable_semantic_memory":  settings.enable_semantic_memory,
            "enable_planner":          settings.enable_planner,
            "redis_url":              "configured" if settings.redis_url else None,
        },
    }


@app.get("/api/sessions")
async def api_sessions():
    """List all sessions (most recent first)."""
    from models.database import get_db
    db = await get_db()
    async with db.execute(
        "SELECT session_id, user_id, created_at, updated_at, message_count "
        "FROM sessions ORDER BY updated_at DESC LIMIT 50"
    ) as cur:
        rows = await cur.fetchall()
    return {"sessions": [dict(r) for r in rows]}


@app.get("/api/memory/episodes")
async def api_episodes():
    """List recent episodic memories."""
    from models.database import get_db
    db = await get_db()
    try:
        async with db.execute(
            "SELECT task_id, session_id, summary, created_at "
            "FROM episodic_memory ORDER BY created_at DESC LIMIT 30"
        ) as cur:
            rows = await cur.fetchall()
        return {"episodes": [dict(r) for r in rows]}
    except Exception:
        return {"episodes": [], "note": "Episodic memory table not initialized"}


@app.get("/api/memory/facts/{user_id}")
async def api_user_facts(user_id: str):
    """List facts for a user."""
    from models.user_facts import get_all_facts
    facts = await get_all_facts(user_id)
    return {"user_id": user_id, "facts": facts}


@app.get("/health")
async def health():
    from tools.registry import list_tools
    from core.cache import llm_cache, tool_cache
    return {
        "status": "ok",
        "tools_loaded": len(list_tools()),
        "llm_cache": llm_cache.stats(),
        "tool_cache": tool_cache.stats(),
    }


# ── Dashboard static files ──
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if _DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=_DASHBOARD_DIR / "assets"),
              name="dashboard-assets")

    @app.get("/dashboard")
    async def serve_dashboard():
        return FileResponse(_DASHBOARD_DIR / "index.html")
