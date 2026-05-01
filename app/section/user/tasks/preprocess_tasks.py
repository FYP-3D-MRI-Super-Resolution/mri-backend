"""
BACKWARD-COMPAT SHIM — user/tasks/preprocess_tasks.py

Dataset preprocessing tasks have been moved to:
  app/section/admin/tasks/preprocess_tasks.py

This shim re-exports the task function under both the old Celery task
name (kept as an alias on the task) and a Python import alias so that
any code that does:

    from app.section.user.tasks.preprocess_tasks import preprocess_pipeline_task

continues to work without modification.

The Celery task is also registered under the old task name via the
``name`` alias so that jobs queued before the migration are still
routed and executed correctly.

TODO: Remove this file entirely in the next release cycle once:
  1. All in-flight Celery tasks have completed or been drained.
  2. All direct Python imports have been updated to the new path.
"""

from app.section.admin.tasks.preprocess_tasks import (  # noqa: F401
    preprocess_pipeline_task,
)

__all__ = ["preprocess_pipeline_task"]
