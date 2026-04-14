import time, uuid
from fastapi import Request
from core.observability import get_logger

log = get_logger("api")

async def logging_middleware(request: Request, call_next):
    trace_id = uuid.uuid4().hex[:12]
    start    = time.monotonic()
    request.state.trace_id = trace_id
    response = await call_next(request)
    latency  = round((time.monotonic() - start) * 1000)
    log.info("api.request", method=request.method, path=request.url.path,
             status=response.status_code, latency_ms=latency, trace_id=trace_id)
    return response
