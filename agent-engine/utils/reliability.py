"""
Reliability & Error Handling Functions
One-liners that turn cascading failures into graceful degradation.
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Awaitable
import asyncio

T = TypeVar('T')
logger = logging.getLogger(__name__)


# =============================================================================
# 2.1 retry_with_backoff — Generic exponential backoff wrapper
# =============================================================================
async def retry_with_backoff(
    fn: Callable[..., Awaitable[T]],
    *args,
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """
    Generic exponential-backoff wrapper for any flaky call.
    One function, reused everywhere — cuts transient-failure incidents drastically.
    
    Args:
        fn: Async function to call
        retries: Max number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Cap on delay
        exponential_base: Multiplier per retry
        jitter: Add random jitter to prevent thundering herd
        retry_exceptions: Exception types to catch and retry
        *args, **kwargs: Passed to fn
    
    Returns:
        Result of successful call
    
    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None
    delay = base_delay
    
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retry_exceptions as e:
            last_exception = e
            if attempt < retries:
                actual_delay = delay
                if jitter:
                    import random
                    actual_delay = delay * (0.5 + random.random())  # 0.5x to 1.5x
                
                logger.warning(
                    f"Retry {attempt + 1}/{retries} for {fn.__name__} "
                    f"after {actual_delay:.1f}s: {e}"
                )
                await asyncio.sleep(actual_delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"All retries exhausted for {fn.__name__}: {e}")
                raise
    
    raise last_exception  # Should never reach here


def retry_with_backoff_sync(
    fn: Callable[..., T],
    *args,
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """Synchronous version of retry_with_backoff."""
    last_exception = None
    delay = base_delay
    
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except retry_exceptions as e:
            last_exception = e
            if attempt < retries:
                actual_delay = delay
                if jitter:
                    import random
                    actual_delay = delay * (0.5 + random.random())
                
                logger.warning(
                    f"Retry {attempt + 1}/{retries} for {fn.__name__} "
                    f"after {actual_delay:.1f}s: {e}"
                )
                time.sleep(actual_delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"All retries exhausted for {fn.__name__}: {e}")
                raise
    
    raise last_exception


# =============================================================================
# 2.2 safe_tool_call — Structured error returns for agent tools
# =============================================================================
@dataclass
class ToolResult:
    """Structured result from a tool call."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    should_retry: bool = False
    fallback_message: Optional[str] = None


async def safe_tool_call(
    tool_fn: Callable[..., Awaitable[T]],
    *args,
    fallback_message: str = "I encountered an issue with that action. Let me try a different approach.",
    **kwargs,
) -> ToolResult:
    """
    Wraps every tool call in try/except, returns structured error to the agent.
    Stops one bad tool call from crashing the whole conversation turn.
    
    Args:
        tool_fn: Async tool function to call
        fallback_message: Message to show agent when tool fails
        *args, **kwargs: Passed to tool_fn
    
    Returns:
        ToolResult with success flag, data, or structured error
    """
    try:
        result = await tool_fn(*args, **kwargs)
        return ToolResult(success=True, data=result)
    except asyncio.TimeoutError:
        return ToolResult(
            success=False,
            error="Tool call timed out",
            error_code="TIMEOUT",
            should_retry=True,
            fallback_message=fallback_message,
        )
    except ConnectionError as e:
        return ToolResult(
            success=False,
            error=f"Connection failed: {e}",
            error_code="CONNECTION_ERROR",
            should_retry=True,
            fallback_message=fallback_message,
        )
    except ValueError as e:
        return ToolResult(
            success=False,
            error=f"Invalid input: {e}",
            error_code="INVALID_INPUT",
            should_retry=False,
            fallback_message=fallback_message,
        )
    except Exception as e:
        logger.exception(f"Tool call failed: {tool_fn.__name__}")
        return ToolResult(
            success=False,
            error=f"Tool error: {str(e)}",
            error_code="TOOL_ERROR",
            should_retry=False,
            fallback_message=fallback_message,
        )


# =============================================================================
# 2.3 circuit_breaker — Stops hammering dead services
# =============================================================================
@dataclass
class CircuitBreakerState:
    failures: int = 0
    last_failure: Optional[datetime] = None
    state: str = "closed"  # closed, open, half-open
    last_success: Optional[datetime] = None


class CircuitBreaker:
    """
    Trips after N consecutive failures, short-circuits calls for a cooldown window.
    Stops hammering a dead downstream service and burning retries/cost.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitBreakerState()
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
    
    async def is_available(self) -> bool:
        async with self._lock:
            if self._state.state == "closed":
                return True
            
            if self._state.state == "open":
                # Check if recovery timeout has passed
                if (self._state.last_failure and 
                    datetime.now() - self._state.last_failure > timedelta(seconds=self.recovery_timeout)):
                    self._state.state = "half-open"
                    self._half_open_calls = 0
                    return True
                return False
            
            # half-open: allow limited calls
            return self._half_open_calls < self.half_open_max_calls
    
    async def record_success(self):
        async with self._lock:
            self._state.failures = 0
            self._state.last_success = datetime.now()
            if self._state.state == "half-open":
                self._state.state = "closed"
                logger.info(f"Circuit breaker '{self.name}' closed after recovery")
    
    async def record_failure(self):
        async with self._lock:
            self._state.failures += 1
            self._state.last_failure = datetime.now()
            
            if self._state.state == "half-open":
                # Any failure in half-open goes back to open
                self._state.state = "open"
                self._half_open_calls = 0
                logger.warning(f"Circuit breaker '{self.name}' reopened after half-open failure")
            elif self._state.failures >= self.failure_threshold:
                self._state.state = "open"
                logger.warning(f"Circuit breaker '{self.name}' opened after {self._state.failures} failures")
            
            if self._state.state == "half-open":
                self._half_open_calls += 1
    
    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if not await self.is_available:
            raise CircuitBreakerOpenError(f"Circuit breaker '{self.name}' is open")
        
        try:
            result = await fn(*args, **kwargs)
            await self.record_success()
            return result
        except Exception as e:
            await self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# Global circuit breaker registry
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker for a service.
    
    Args:
        name: Service name (e.g., "llm_provider", "payment_gateway")
        failure_threshold: Failures before opening
        recovery_timeout: Seconds before trying half-open
    
    Returns:
        CircuitBreaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
    return _circuit_breakers[name]


# =============================================================================
# 2.4 idempotency_key — Prevents double-execution
# =============================================================================
async def idempotency_key(
    job_type: str,
    entity_id: str,
    window_seconds: int = 3600,
    redis_client: Optional[redis.Redis] = None,
) -> bool:
    """
    Generates a dedup key so a scheduled job can't fire twice.
    Prevents double-charging or double-messaging on scheduler race conditions.
    
    Args:
        job_type: Type of job (e.g., "send_reminder", "charge_payment")
        entity_id: Unique entity identifier (lead_id, appointment_id, payment_id)
        window_seconds: Deduplication window (default 1 hour)
        redis_client: Optional Redis client
    
    Returns:
        True if this is the first execution (proceed), False if duplicate (skip)
    """
    if redis_client is None:
        redis_client = _get_redis()
    
    key = f"idempotent:{job_type}:{entity_id}"
    # SET NX with expiry = atomic check-and-set
    was_new = await redis_client.set(
        key, "1", nx=True, ex=window_seconds
    )
    return was_new is not False  # True = first execution, False = duplicate


def generate_idempotency_key(job_type: str, entity_id: str) -> str:
    """Generate a deterministic idempotency key string."""
    return f"{job_type}:{entity_id}"


# =============================================================================
# 2.5 heartbeat_ping — Turns silent outages into 30-second alerts
# =============================================================================
async def heartbeat_ping(
    service_name: str,
    check_fn: Callable[[], Awaitable[bool]],
    redis_client: Optional[redis.Redis] = None,
    ttl_seconds: int = 60,
) -> bool:
    """
    Lightweight health check called every N seconds.
    The one function that turns 'silent 6-hour outage' into 'alert in 30 seconds'.
    
    Args:
        service_name: Name of service (e.g., "whatsapp_bridge", "llm_provider")
        check_fn: Async function returning True if healthy
        redis_client: Optional Redis client
        ttl_seconds: How long to consider heartbeat valid
    
    Returns:
        True if healthy, False if unhealthy
    """
    if redis_client is None:
        redis_client = _get_redis()
    
    key = f"heartbeat:{service_name}"
    
    try:
        is_healthy = await check_fn()
        now = time.time()
        
        if is_healthy:
            # Store heartbeat with timestamp
            await redis_client.set(
                key,
                str(now),
                ex=ttl_seconds * 2,  # Keep 2x TTL for staleness detection
            )
        else:
            # Mark unhealthy
            await redis_client.set(key, f"unhealthy:{now}", ex=ttl_seconds * 2)
        
        return is_healthy
    except Exception as e:
        logger.error(f"Heartbeat check failed for {service_name}: {e}")
        await redis_client.set(key, f"error:{time.time()}", ex=ttl_seconds * 2)
        return False


async def is_heartbeat_healthy(
    service_name: str,
    max_age_seconds: int = 60,
    redis_client: Optional[redis.Redis] = None,
) -> bool:
    """Check if a service's heartbeat is recent and healthy."""
    if redis_client is None:
        redis_client = _get_redis()
    
    key = f"heartbeat:{service_name}"
    value = await redis_client.get(key)
    
    if not value:
        return False
    
    if value.startswith("unhealthy:") or value.startswith("error:"):
        return False
    
    try:
        timestamp = float(value)
        return (time.time() - timestamp) < max_age_seconds
    except ValueError:
        return False


# =============================================================================
# 2.6 graceful_shutdown_handler — Clean deploy handling
# =============================================================================
class GracefulShutdown:
    """
    Finishes in-flight jobs before process exit on deploy.
    Prevents a deploy from silently dropping a message mid-send.
    """
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._shutdown_requested = False
        self._in_flight_tasks: set = set()
        self._original_sigterm = None
        self._original_sigint = None
    
    def register_task(self, task: asyncio.Task):
        """Register an in-flight task to track."""
        self._in_flight_tasks.add(task)
        task.add_done_callback(self._in_flight_tasks.discard)
    
    def request_shutdown(self):
        """Signal that shutdown has been requested."""
        self._shutdown_requested = True
        logger.info("Graceful shutdown requested")
    
    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_requested
    
    async def wait_for_tasks(self):
        """Wait for in-flight tasks to complete (with timeout)."""
        if not self._in_flight_tasks:
            return
        
        logger.info(f"Waiting for {len(self._in_flight_tasks)} in-flight tasks...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._in_flight_tasks, return_exceptions=True),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Shutdown timeout ({self.timeout}s) reached, {len(self._in_flight_tasks)} tasks may be incomplete")
    
    def install_signal_handlers(self):
        """Install SIGTERM/SIGINT handlers."""
        import signal
        loop = asyncio.get_running_loop()
        
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.request_shutdown()
        
        self._original_sigterm = signal.signal(signal.SIGTERM, signal_handler)
        self._original_sigint = signal.signal(signal.SIGINT, signal_handler)


# Global instance
_graceful_shutdown = GracefulShutdown()


def get_graceful_shutdown() -> GracefulShutdown:
    return _graceful_shutdown


async def graceful_shutdown_handler():
    """Global graceful shutdown handler for FastAPI lifespan."""
    _graceful_shutdown.request_shutdown()
    await _graceful_shutdown.wait_for_tasks()


# =============================================================================
# Utility: time import
# =============================================================================
import time