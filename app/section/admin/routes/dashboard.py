"""Admin dashboard routes.

Thin controller layer that delegates business logic to the admin
dashboard service and serialises responses with Pydantic schemas.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.core.database import get_db
from app.section.admin.schemas import (
    CountResponse,
    DashboardHealthResponse,
    DashboardMetricsResponse,
    DashboardStatsResponse,
)
from app.section.admin.services.admin_dashboard_service import AdminDashboardService
from app.shared.guards.rbac import require_role
from app.shared.models import User

router = APIRouter(
    prefix="/admin",
    tags=["Admin — Dashboard"],
)


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Get dashboard statistics",
    description="Fetch real-time dashboard statistics including user count, active jobs, and system status",
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> DashboardStatsResponse:
    service = AdminDashboardService(db)
    return DashboardStatsResponse(**service.get_dashboard_stats())


@router.get(
    "/jobs/active/count",
    response_model=CountResponse,
    summary="Get active jobs count",
    status_code=status.HTTP_200_OK,
)
async def get_active_jobs_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> CountResponse:
    service = AdminDashboardService(db)
    return CountResponse(**service.get_active_jobs_count())


@router.get(
    "/users/count",
    response_model=CountResponse,
    summary="Get total users count",
    status_code=status.HTTP_200_OK,
)
async def get_total_users_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> CountResponse:
    service = AdminDashboardService(db)
    return CountResponse(**service.get_total_users_count())


@router.get(
    "/health",
    response_model=DashboardHealthResponse,
    summary="Check system health",
    status_code=status.HTTP_200_OK,
)
async def check_system_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> DashboardHealthResponse:
    service = AdminDashboardService(db)
    return DashboardHealthResponse(**service.get_system_health())


@router.get(
    "/metrics",
    response_model=DashboardMetricsResponse,
    summary="Get detailed system metrics",
    status_code=status.HTTP_200_OK,
)
async def get_system_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> DashboardMetricsResponse:
    service = AdminDashboardService(db)
    return DashboardMetricsResponse(**service.get_system_metrics())
