"""
User section tasks package.

Contains user-specific Celery tasks (inference only).
Dataset preprocessing tasks live in app/section/admin/tasks/.
The Celery app configuration lives in app/shared/tasks/.
"""

from .inference_tasks import preprocess_lr_for_inference_task, inference_task

__all__ = [
    "preprocess_lr_for_inference_task",
    "inference_task",
]