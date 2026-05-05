"""Admin dashboard service.

This service contains the dashboard aggregation and health-check logic
for the admin section. Routes should only orchestrate HTTP concerns and
delegate all data fetching / computation here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import time
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

    def _read_proc_cpu_snapshot(self) -> tuple[float, float] | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as stat_file:
                first_line = stat_file.readline().strip()

            parts = first_line.split()
            if len(parts) < 5 or parts[0] != "cpu":
                return None

            values = [float(part) for part in parts[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0.0)
            total = sum(values)
            return total, idle
        except Exception:
            return None

    def _cpu_percent_from_proc(self) -> float | None:
        first = self._read_proc_cpu_snapshot()
        if first is None:
            return None

        time.sleep(0.1)

        second = self._read_proc_cpu_snapshot()
        if second is None:
            return None

        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]
        if total_delta <= 0:
            return None

        usage = (1.0 - (idle_delta / total_delta)) * 100.0
        return max(0.0, min(100.0, usage))

    def _memory_from_proc(self) -> tuple[float, float, float] | None:
        try:
            info: dict[str, float] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as meminfo_file:
                for line in meminfo_file:
                    if ":" not in line:
                        continue
                    key, raw_val = line.split(":", 1)
                    parts = raw_val.strip().split()
                    if not parts:
                        continue
                    info[key] = float(parts[0]) * 1024.0

            total = info.get("MemTotal")
            available = info.get("MemAvailable", info.get("MemFree"))
            if total is None or available is None or total <= 0:
                return None

            used = total - available
            usage_percent = (used / total) * 100.0
            return usage_percent, total, available
        except Exception:
            return None

    def _resource_metrics(self) -> tuple[bool, dict[str, float | int]]:
        cpu_percent: float | None = None
        memory_percent: float | None = None

        if psutil is not None:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory_percent = psutil.virtual_memory().percent
            except Exception:
                cpu_percent = None
                memory_percent = None

        if cpu_percent is None:
            cpu_percent = self._cpu_percent_from_proc()
        if memory_percent is None:
            proc_memory = self._memory_from_proc()
            if proc_memory is not None:
                memory_percent = proc_memory[0]

        cpu_usage = cpu_percent if cpu_percent is not None else 0.0
        memory_usage = memory_percent if memory_percent is not None else 0.0
        resources_ok = cpu_usage < 80 and memory_usage < 85
        return resources_ok, {"cpu_usage": cpu_usage, "memory_usage": memory_usage}

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
            memory_percent = 0.0
            memory_total = 0.0
            memory_available = 0.0
            cpu_count = 0
            if psutil is not None:
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                memory_total = float(memory.total)
                memory_available = float(memory.available)
                cpu_count = psutil.cpu_count(logical=True) or 0
            else:
                proc_memory = self._memory_from_proc()
                if proc_memory is not None:
                    memory_percent, memory_total, memory_available = proc_memory
                cpu_count = os.cpu_count() or 0
        except Exception:
            resource_metrics = {"cpu_usage": 0, "memory_usage": 0}
            memory_percent = 0.0
            memory_total = 0.0
            memory_available = 0.0
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
                    "usage_percent": memory_percent,
                    "total_gb": round(memory_total / (1024**3), 2) if memory_total else 0,
                    "available_gb": round(memory_available / (1024**3), 2) if memory_available else 0,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
