"""Admin dashboard service.

This service contains the dashboard aggregation and health-check logic
for the admin section. Routes should only orchestrate HTTP concerns and
delegate all data fetching / computation here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.shared.models import Job, JobStatus, User

try:
    import psutil
except ImportError:  # pragma: no cover - optional runtime dependency
    psutil = None


class AdminDashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _resource_metrics(self) -> tuple[bool, dict[str, float | int]]:
        if psutil is None:
            return True, {"cpu_usage": 0, "memory_usage": 0}

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        resources_ok = cpu_percent < 80 and memory.percent < 85
        return resources_ok, {"cpu_usage": cpu_percent, "memory_usage": memory.percent}

    def get_dashboard_stats(self) -> dict[str, Any]:
        total_users = self.db.query(func.count(User.id)).scalar() or 0
        active_jobs = self.db.query(func.count(Job.id)).filter(
            Job.status == JobStatus.PROCESSING
        ).scalar() or 0

        try:
            self.db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

        try:
            resources_ok, _ = self._resource_metrics()
        except Exception:
            resources_ok = True

        if db_ok and resources_ok:
            system_status = "online"
        elif db_ok:
            system_status = "degraded"
        else:
            system_status = "offline"

        return {
            "total_users": total_users,
            "active_jobs": active_jobs,
            "system_status": system_status,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def get_active_jobs_count(self) -> dict[str, int]:
        count = self.db.query(func.count(Job.id)).filter(
            Job.status == JobStatus.PROCESSING
        ).scalar() or 0
        return {"count": count}

    def get_total_users_count(self) -> dict[str, int]:
        count = self.db.query(func.count(User.id)).scalar() or 0
        return {"count": count}

    def get_system_health(self) -> dict[str, Any]:
        health_checks = {
            "database": False,
            "cpu": False,
            "memory": False,
            "jobs": False,
        }

        try:
            self.db.execute(text("SELECT 1"))
            health_checks["database"] = True
        except Exception as exc:
            print(f"Database health check failed: {exc}")

        try:
            _, resource_metrics = self._resource_metrics()
            health_checks["cpu"] = resource_metrics.get("cpu_usage", 0) < 80
            health_checks["memory"] = resource_metrics.get("memory_usage", 0) < 85
        except Exception as exc:
            print(f"Resource health check failed: {exc}")
            resource_metrics = {"cpu_usage": 0, "memory_usage": 0}

        try:
            processing_count = self.db.query(func.count(Job.id)).filter(
                Job.status == JobStatus.PROCESSING
            ).scalar() or 0
            health_checks["jobs"] = processing_count < 10
        except Exception as exc:
            print(f"Jobs health check failed: {exc}")
            processing_count = 0

        passed_checks = sum(1 for value in health_checks.values() if value)
        total_checks = len(health_checks)

        if passed_checks == total_checks:
            status_val = "online"
        elif passed_checks >= total_checks // 2:
            status_val = "degraded"
        else:
            status_val = "offline"

        return {
            "status": status_val,
            "db_connected": health_checks["database"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "cpu_usage": resource_metrics.get("cpu_usage", 0),
                "memory_usage": resource_metrics.get("memory_usage", 0),
                "processing_jobs": processing_count,
            },
            "health_checks": health_checks,
        }

    def get_system_metrics(self) -> dict[str, Any]:
        try:
            _resources_ok, resource_metrics = self._resource_metrics()
            memory = None
            cpu_count = 0
            if psutil is not None:
                memory = psutil.virtual_memory()
                cpu_count = psutil.cpu_count(logical=True) or 0
        except Exception:
            cpu_percent = 0
            resource_metrics = {"cpu_usage": 0, "memory_usage": 0}
            memory = None
            cpu_count = 0

        total_users = self.db.query(func.count(User.id)).scalar() or 0
        admin_users = self.db.query(func.count(User.id)).filter(
            User.role == UserRoles.SUPER_ADMIN
        ).scalar() or 0

        total_jobs = self.db.query(func.count(Job.id)).scalar() or 0
        processing_jobs = self.db.query(func.count(Job.id)).filter(
            Job.status == JobStatus.PROCESSING
        ).scalar() or 0
        completed_jobs = self.db.query(func.count(Job.id)).filter(
            Job.status == JobStatus.COMPLETED
        ).scalar() or 0
        failed_jobs = self.db.query(func.count(Job.id)).filter(
            Job.status == JobStatus.FAILED
        ).scalar() or 0

        return {
            "users": {
                "total": total_users,
                "admins": admin_users,
                "regular_users": total_users - admin_users,
            },
            "jobs": {
                "total": total_jobs,
                "processing": processing_jobs,
                "completed": completed_jobs,
                "failed": failed_jobs,
                "pending": total_jobs - processing_jobs - completed_jobs - failed_jobs,
            },
            "system": {
                "cpu": {
                    "usage_percent": resource_metrics.get("cpu_usage", 0),
                    "core_count": cpu_count,
                },
                "memory": {
                    "usage_percent": memory.percent if memory else 0,
                    "total_gb": round(memory.total / (1024**3), 2) if memory else 0,
                    "available_gb": round(memory.available / (1024**3), 2) if memory else 0,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
