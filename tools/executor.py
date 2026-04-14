import asyncio, time
from collections import defaultdict
from tools.registry import get_tool
from tools.sandbox import check_permission
from tools.schemas import ToolCallRequest, ToolCallResult, ToolError
from core.config import settings
from core.errors import ToolNotFoundError
from core.observability import get_logger

log = get_logger(__name__)
RETRY_DELAYS = [1, 5]

# In-memory sliding window rate limiter
# Key format: "user_id:tool_name" → list of call timestamps (monotonic)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = asyncio.Lock()


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

    retry_count = 0
    while True:
        start = time.monotonic()
        try:
            raw     = await asyncio.wait_for(tool_fn(**req.parameters),
                                             timeout=spec.timeout_seconds)
            latency = int((time.monotonic() - start) * 1000)
            log.info("tool.success", tool=req.tool_name,
                     latency_ms=latency, trace_id=req.trace_id)
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
