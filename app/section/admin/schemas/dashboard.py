"""Schemas for admin dashboard endpoints."""

from pydantic import BaseModel


class DashboardStatsResponse(BaseModel):
    total_users: int
    active_jobs: int
    system_status: str
    last_updated: str


class CountResponse(BaseModel):
    count: int


class HealthMetrics(BaseModel):
    cpu_usage: float
    memory_usage: float
    processing_jobs: int


class HealthChecks(BaseModel):
    database: bool
    cpu: bool
    memory: bool
    jobs: bool


class DashboardHealthResponse(BaseModel):
    status: str
    db_connected: bool
    timestamp: str
    metrics: HealthMetrics
    health_checks: HealthChecks


class UserMetrics(BaseModel):
    total: int
    admins: int
    regular_users: int


class JobMetrics(BaseModel):
    total: int
    processing: int
    completed: int
    failed: int
    pending: int


class SystemResourceMetrics(BaseModel):
    cpu: dict[str, float | int]
    memory: dict[str, float | int]
    timestamp: str


class DashboardMetricsResponse(BaseModel):
    users: UserMetrics
    jobs: JobMetrics
    system: SystemResourceMetrics
