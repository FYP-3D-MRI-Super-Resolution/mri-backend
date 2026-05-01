"""Celery application configuration."""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "mri_sr_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.section.user.tasks.preprocess_tasks",
        "app.section.user.tasks.inference_tasks"
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    task_soft_time_limit=3300,  # 55 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=10,
)

# Task routes
celery_app.conf.task_routes = {
    "app.tasks.preprocess_tasks.*": {"queue": "preprocessing"},
    "app.tasks.inference_tasks.*": {"queue": "inference"},
}
