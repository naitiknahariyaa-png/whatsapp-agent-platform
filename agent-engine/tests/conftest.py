"""
Shared pytest fixtures for the WhatsApp Agent Platform test-suite.

Keeps tests hermetic: a throwaway SQLite DB and in-memory metric/usage stores
so nothing touches Postgres or Redis during the run.
"""
import os
import sys
import tempfile

# Point the app at an isolated SQLite database BEFORE any module imports db.py.
_TMP_DB = os.path.join(tempfile.gettempdir(), "wap_test.db")
if os.path.exists(_TMP_DB):
    try:
        os.remove(_TMP_DB)
    except OSError:
        pass
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB}")
# Force in-memory metric/usage backends (no Redis needed for tests).
os.environ["REDIS_URL"] = "redis://127.0.0.1:9/0"
os.environ["ALERT_DRY_RUN"] = "true"

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset in-memory metric/usage stores between tests for isolation."""
    from metrics import metrics_collector
    from usage_metering import usage_meter
    metrics_collector._redis = None
    usage_meter._redis = None
    metrics_collector.reset_memory()
    usage_meter.reset_memory()
    yield
    metrics_collector.reset_memory()
    usage_meter.reset_memory()


@pytest.fixture
async def db_session():
    """Yield an async DB session against the test SQLite database."""
    from db import async_session, init_db
    await init_db()
    async with async_session() as session:
        yield session
