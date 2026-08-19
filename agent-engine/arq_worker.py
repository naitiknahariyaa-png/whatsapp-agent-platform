"""
ARQ Worker — async task queue for automation loops.

Tasks registered:
  - process_funnel: every 15 minutes
  - process_nurture: every 10 minutes
  - process_consent: every 30 minutes
  - process_reengagement: weekly (cron)
  - nightly_reindex: daily at 2 AM

Requires Redis running. Falls back gracefully if Redis is unavailable.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from config import settings
from logging_setup import get_logger

logger = get_logger("arq_worker")

try:
    from arq import create_pool, ArqRedis
    from arq.connections import RedisSettings
    HAS_ARQ = True
except ImportError:
    HAS_ARQ = False
    logger.warning("[!] arq not installed, background loops will use asyncio fallback")


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

async def send_whatsapp_message(ctx: Dict[str, Any], phone_number: str, message: str, idempotency_key: str = "") -> Dict[str, Any]:
    """Send a WhatsApp message via the bridge."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.whatsapp_bridge_url}/send",
                json={"to": phone_number, "message": message},
            )
            if resp.status_code == 200:
                logger.info(f"[v] ARQ WhatsApp sent to {phone_number}")
                return {"status": "sent", "phone_number": phone_number}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
    except Exception as e:
        logger.error(f"ARQ WhatsApp send failed for {phone_number}: {e}")
        return {"status": "error", "phone_number": phone_number, "error": str(e)}


async def send_appointment_reminder(ctx: Dict[str, Any], appointment_id: int) -> Dict[str, Any]:
    """Send an appointment reminder via WhatsApp."""
    from db import async_session, Appointment
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(Appointment).where(Appointment.id == appointment_id))
        appt = result.scalar_one_or_none()
        if not appt:
            return {"status": "not_found"}
        msg = (f"Reminder: you have an appointment"
               f"{' — ' + appt.title if appt.title else ''} "
               f"at {appt.appointment_time} today.")
        return await send_whatsapp_message(ctx, appt.phone_number, msg)


async def process_drip_enrollments(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Process drip campaign enrollments."""
    try:
        from drip_campaigns import engine as drip_engine
        await drip_engine.process_enrollments()
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"ARQ drip enrollment processing failed: {e}")
        return {"error": str(e)}


async def process_funnel(ctx: Dict[str, Any]) -> Dict[str, int]:
    """Process lead qualification funnel."""
    try:
        from lead_funnel import lead_funnel
        result = await lead_funnel.process_funnel()
        logger.info(f"[v] ARQ funnel task completed: {result}")
        return result
    except Exception as e:
        logger.error(f"ARQ funnel task failed: {e}")
        return {"error": str(e)}


async def process_nurture(ctx: Dict[str, Any]) -> Dict[str, int]:
    """Process appointment nurture loop."""
    try:
        from appointment_nurture import appointment_nurture
        result = await appointment_nurture.process_nurture()
        logger.info(f"[v] ARQ nurture task completed: {result}")
        return result
    except Exception as e:
        logger.error(f"ARQ nurture task failed: {e}")
        return {"error": str(e)}


async def process_consent(ctx: Dict[str, Any]) -> Dict[str, int]:
    """Process consent events and opt-outs."""
    try:
        from compliance_loop import compliance_loop
        result = await compliance_loop.process_consent_events()
        logger.info(f"[v] ARQ consent task completed: {result}")
        return result
    except Exception as e:
        logger.error(f"ARQ consent task failed: {e}")
        return {"error": str(e)}


async def process_reengagement(ctx: Dict[str, Any]) -> Dict[str, int]:
    """Process re-engagement nudges for qualified leads."""
    try:
        from reengagement_loop import reengagement_loop
        result = await reengagement_loop.process()
        logger.info(f"[v] ARQ reengagement task completed: {result}")
        return result
    except Exception as e:
        logger.error(f"ARQ reengagement task failed: {e}")
        return {"error": str(e)}


async def nightly_reindex(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Nightly maintenance: purge old data, reindex vectors, cleanup."""
    try:
        from compliance_loop import compliance_loop
        purge_result = await compliance_loop.auto_purge(retention_days=365)
        logger.info(f"[v] ARQ nightly reindex completed: purge={purge_result}")

        try:
            from vector_store import vector_store
            if hasattr(vector_store, "reindex"):
                await vector_store.reindex()
                logger.info("[v] Vector store reindexed")
        except Exception as e:
            logger.warning(f"Vector reindex skipped: {e}")

        return {
            "purge": purge_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"ARQ nightly reindex failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------

class ArqWorkerConfig:
    """ARQ worker configuration with schedules."""

    @staticmethod
    def get_redis_settings() -> Optional["RedisSettings"]:
        if not HAS_ARQ:
            return None
        redis_url = getattr(settings, "redis_url", "redis://localhost:6379/0")
        try:
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            return RedisSettings(
                host=parsed.hostname or "localhost",
                port=parsed.port or 6379,
                database=int(parsed.path.lstrip("/")) if parsed.path else 0,
                password=parsed.password or None,
            )
        except Exception:
            return RedisSettings(host="localhost", port=6379)

    @staticmethod
    def get_tasks() -> Dict[str, Any]:
        return {
            "send_whatsapp_message": send_whatsapp_message,
            "send_appointment_reminder": send_appointment_reminder,
            "process_drip_enrollments": process_drip_enrollments,
            "process_funnel": process_funnel,
            "process_nurture": process_nurture,
            "process_consent": process_consent,
            "process_reengagement": process_reengagement,
            "nightly_reindex": nightly_reindex,
        }

    @staticmethod
    def get_schedules() -> list:
        return [
            {"task": "process_funnel", "interval": 900},  # 15 minutes
            {"task": "process_nurture", "interval": 600},  # 10 minutes
            {"task": "process_consent", "interval": 1800},  # 30 minutes
            {"task": "process_reengagement", "cron": "0 8 * * 1"},  # Weekly Monday 8 AM
            {"task": "nightly_reindex", "cron": "0 2 * * *"},  # Daily at 2 AM
        ]


# ---------------------------------------------------------------------------
# Worker runner
# ---------------------------------------------------------------------------

async def run_worker():
    """Start the ARQ worker."""
    if not HAS_ARQ:
        logger.error("[!] Cannot start ARQ worker: arq not installed. Install with: pip install arq[redis]")
        return

    from arq.worker import create_worker, Worker

    redis_settings = ArqWorkerConfig.get_redis_settings()
    tasks = ArqWorkerConfig.get_tasks()
    schedules = ArqWorkerConfig.get_schedules()

    worker = create_worker(
        WorkerSettings(
            functions=tuple(tasks.values()),
            cron_jobs=tuple(schedules),
            redis_settings=redis_settings,
        )
    )
    logger.info("[v] Starting ARQ worker with scheduled tasks...")
    await worker.run()


class WorkerSettings:
    """ARQ worker settings container."""
    functions = ()
    cron_jobs = ()
    redis_settings = None
    max_jobs = 10
    job_timeout = 300
    keep_result = 3600


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------

async def enqueue_task(task_name: str, **kwargs) -> Optional[str]:
    """Enqueue a task for background processing."""
    if not HAS_ARQ:
        logger.warning(f"[!] Cannot enqueue {task_name}: arq not installed")
        return None

    try:
        redis_settings = ArqWorkerConfig.get_redis_settings()
        pool = await create_pool(redis_settings)
        job = await pool.enqueue_job(task_name, **kwargs)
        if job:
            logger.info(f"[v] Enqueued task {task_name} (job_id={job.job_id})")
            return job.job_id
    except Exception as e:
        logger.error(f"Failed to enqueue task {task_name}: {e}")
    return None


# ---------------------------------------------------------------------------
# Graceful fallback (asyncio-based scheduler)
# ---------------------------------------------------------------------------

class FallbackScheduler:
    """Fallback scheduler using asyncio when Redis/ARQ is unavailable."""

    def __init__(self):
        self._tasks: list = []
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        logger.info("[i] Starting fallback asyncio scheduler")

        self._tasks.append(asyncio.create_task(self._funnel_loop()))
        self._tasks.append(asyncio.create_task(self._nurture_loop()))
        self._tasks.append(asyncio.create_task(self._consent_loop()))
        self._tasks.append(asyncio.create_task(self._reengagement_loop()))
        self._tasks.append(asyncio.create_task(self._nightly_loop()))

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        logger.info("[i] Fallback scheduler stopped")

    async def _funnel_loop(self):
        while self._running:
            try:
                await process_funnel({})
            except Exception as e:
                logger.error(f"Fallback funnel error: {e}")
            await asyncio.sleep(900)

    async def _nurture_loop(self):
        while self._running:
            try:
                await process_nurture({})
            except Exception as e:
                logger.error(f"Fallback nurture error: {e}")
            await asyncio.sleep(600)

    async def _consent_loop(self):
        while self._running:
            try:
                await process_consent({})
            except Exception as e:
                logger.error(f"Fallback consent error: {e}")
            await asyncio.sleep(1800)

    async def _reengagement_loop(self):
        while self._running:
            try:
                await process_reengagement({})
            except Exception as e:
                logger.error(f"Fallback reengagement error: {e}")
            await asyncio.sleep(604800)

    async def _nightly_loop(self):
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.hour == 2:
                    await nightly_reindex({})
            except Exception as e:
                logger.error(f"Fallback nightly error: {e}")
            await asyncio.sleep(3600)


fallback_scheduler = FallbackScheduler()

enqueue_job = enqueue_task
