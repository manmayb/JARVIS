import asyncio, time
from collections import defaultdict
from tools.registry import get_tool
from tools.sandbox import check_permission
from tools.schemas import ToolCallRequest, ToolCallResult, ToolError
from core.config import settings
from core.errors import ToolNotFoundError
from core.logging import get_logger
from core.cache import tool_cache, TTLCache

log = get_logger(__name__)
RETRY_DELAYS = [1, 5]

# In-memory sliding window rate limiter
# Key format: "user_id:tool_name" → list of call timestamps (monotonic)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = asyncio.Lock()


def _extract_api_error(raw_result: object) -> str | None:
    """Return a tool-defined API error message if one is present."""
    if not isinstance(raw_result, dict):
        return None

    status = str(raw_result.get("status", "")).lower()
    if status != "error":
        return None

    detail = raw_result.get("detail") or raw_result.get("message") or raw_result.get("error")
    if detail is None:
        detail = str(raw_result)
    return str(detail)


async def _check_rate_limit(tool_name: str, user_id: str,
                             limit_per_minute: int) -> bool:
    """
    Sliding window rate limiter.
    Returns True if the call is allowed, False if limit exceeded.
    """
    key = f"{user_id}:{tool_name}"
    now = time.monotonic()
    window_start = now - 60.0

    async with _rate_limit_lock:
        # Drop timestamps older than 60 seconds
        _rate_limit_store[key] = [
            t for t in _rate_limit_store[key] if t > window_start
        ]
        if len(_rate_limit_store[key]) >= limit_per_minute:
            return False
        _rate_limit_store[key].append(now)
        return True


async def execute(req: ToolCallRequest,
                  max_retries: int = settings.max_retries_per_tool) -> ToolCallResult:
    try:
        spec, tool_fn = get_tool(req.tool_name)
    except ToolNotFoundError:
        return ToolCallResult(
            success=False,
            error=ToolError(code="VALIDATION_ERROR",
                            message=f"Unknown tool: {req.tool_name}",
                            retryable=False),
            tool_name=req.tool_name, step_number=req.step_number)

    if req.allowed_tool_names is not None and req.tool_name not in req.allowed_tool_names:
        return ToolCallResult(
            success=False,
            error=ToolError(code="forbidden",
                            message=f"Agent restricted access: '{req.tool_name}' not in allowed tools list.",
                            retryable=False),
            tool_name=req.tool_name, step_number=req.step_number)

    perm = check_permission(spec, req.user_id)
    if not perm.allowed:
        return ToolCallResult(
            success=False,
            error=ToolError(code="PERMISSION_DENIED",
                            message=perm.reason, retryable=False),
            tool_name=req.tool_name, step_number=req.step_number)

    # Enforce rate limit
    rate_ok = await _check_rate_limit(
        req.tool_name, req.user_id, spec.rate_limit_per_minute
    )
    if not rate_ok:
        log.warning("tool.rate_limited",
                    tool=req.tool_name,
                    user=req.user_id,
                    limit=spec.rate_limit_per_minute,
                    trace_id=req.trace_id)
        return ToolCallResult(
            success=False,
            error=ToolError(
                code="RATE_LIMITED",
                message=(f"Tool '{req.tool_name}' exceeded rate limit "
                         f"({spec.rate_limit_per_minute} calls/min)"),
                retryable=False,
            ),
            tool_name=req.tool_name,
            step_number=req.step_number,
        )

    if spec.cache_ttl_seconds > 0:
        cache_key = TTLCache._make_key(req.tool_name, req.parameters)
        cached = await tool_cache.get(cache_key)
        if cached is not None:
            log.info("tool.cache_hit", tool=req.tool_name, trace_id=req.trace_id)
            return ToolCallResult(success=True, output=cached, latency_ms=0,
                                  from_cache=True, tool_name=req.tool_name,
                                  step_number=req.step_number)

    retry_count = 0
    while True:
        start = time.monotonic()
        try:
            raw     = await asyncio.wait_for(tool_fn(**req.parameters),
                                             timeout=spec.timeout_seconds)
            latency = int((time.monotonic() - start) * 1000)

            api_error = _extract_api_error(raw)
            if api_error is not None:
                message = f"[{req.tool_name}] returned an API error: {api_error}"
                log.warning("tool.api_error", tool=req.tool_name,
                            trace_id=req.trace_id, message=message)
                return ToolCallResult(
                    success=False,
                    output=raw if isinstance(raw, dict) else None,
                    error=ToolError(
                        code="EXTERNAL_API_ERROR",
                        message=message,
                        retryable=False,
                    ),
                    latency_ms=latency,
                    tool_name=req.tool_name,
                    step_number=req.step_number,
                )

            log.info("tool.success", tool=req.tool_name,
                     latency_ms=latency, trace_id=req.trace_id)
            if spec.cache_ttl_seconds > 0:
                await tool_cache.set(cache_key, raw, ttl=spec.cache_ttl_seconds)
            return ToolCallResult(success=True, output=raw, latency_ms=latency,
                                  tool_name=req.tool_name,
                                  step_number=req.step_number)

        except asyncio.CancelledError:
            log.warning("tool.cancelled", tool=req.tool_name, trace_id=req.trace_id)
            raise

        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            err = ToolError(code="TIMEOUT",
                            message=f"Exceeded {spec.timeout_seconds}s",
                            retryable=True)
            if retry_count >= max_retries:
                return ToolCallResult(success=False, error=err,
                                      latency_ms=latency,
                                      tool_name=req.tool_name,
                                      step_number=req.step_number)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            log.error("tool.error", tool=req.tool_name,
                      error=str(e), trace_id=req.trace_id)
            err = ToolError(code="EXTERNAL_API_ERROR",
                            message=str(e), retryable=True)
            if retry_count >= max_retries:
                return ToolCallResult(success=False, error=err,
                                      latency_ms=latency,
                                      tool_name=req.tool_name,
                                      step_number=req.step_number)

        retry_count += 1
        delay = RETRY_DELAYS[retry_count - 1]
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            log.warning("retry.sleep_cancelled", tool=req.tool_name,
                        retry_count=retry_count, trace_id=req.trace_id)
            raise
