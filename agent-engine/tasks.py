"""
Redis task queue for background jobs (broadcasts, reminders)
"""
import redis
import json
from typing import Callable, Any
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL)


def enqueue_task(queue_name: str, task_data: Dict[str, Any]):
    """Add task to Redis queue"""
    r.lpush(queue_name, json.dumps(task_data))


def process_queue(queue_name: str, handler: Callable[[Dict], Any]):
    """Process tasks from queue (run in background)"""
    while True:
        _, task_json = r.brpop(queue_name)
        task_data = json.loads(task_json)
        handler(task_data)


# Usage:
# enqueue_task("broadcasts", {"message": "...", "recipients": [...]})
# enqueue_task("reminders", {"phone": "...", "time": "2024-01-01 10:00"})