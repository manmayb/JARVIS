from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from api.middleware.logger import logging_middleware
from api.routes.chat import router as chat_router
from api.routes.tools import router as tools_router
from core.errors import AgentError, ConfigurationError
from models.database import init_db, close_db
from tools.registry import load_all_tools

app = FastAPI(title="Jarvis", version="0.1.0")

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

@app.on_event("shutdown")
async def shutdown():
    await close_db()

app.include_router(chat_router)
app.include_router(tools_router)

@app.get("/health")
async def health():
    from tools.registry import list_tools
    return {"status": "ok", "tools_loaded": len(list_tools())}
