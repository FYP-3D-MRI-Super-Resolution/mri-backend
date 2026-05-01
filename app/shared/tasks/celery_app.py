"""
Celery application configuration — shared infrastructure.

Moved from app/section/user/tasks/celery_app.py.

The include list references the canonical task module paths after
the refactoring:
  - admin tasks  → app.section.admin.tasks.preprocess_tasks
  - user tasks   → app.section.user.tasks.inference_tasks
"""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "mri_sr_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.section.admin.tasks.preprocess_tasks",
        "app.section.user.tasks.inference_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,        # 1 hour hard limit
    task_soft_time_limit=3300,   # 55-minute soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=10,
)

# Route tasks to their respective queues.
celery_app.conf.task_routes = {
    "app.section.admin.tasks.preprocess_tasks.*": {"queue": "preprocessing"},
    "app.section.user.tasks.inference_tasks.*": {"queue": "inference"},
}
