"""Admin schemas package."""

from .dashboard import (
    CountResponse,
    DashboardHealthResponse,
    DashboardMetricsResponse,
    DashboardStatsResponse,
)

__all__ = [
    "CountResponse",
    "DashboardHealthResponse",
    "DashboardMetricsResponse",
    "DashboardStatsResponse",
]
