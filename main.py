"""
MRI Super-Resolution Pipeline — FastAPI application entry point.

Router registration order:
  1. Auth          — shared authentication endpoints
  2. User routes   — inference preprocessing + job management (regular users)
  3. Admin routes  — dataset preprocessing + admin job management (SUPER_ADMIN)
  4. File routes   — NIfTI download + DICOM conversion (both roles)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
import os

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.core.auth import get_password_hash
from app.core.constants import APIEndpoints, UserRoles
from app.middleware import add_exception_handlers

# ── Model & repository imports (ensure SQLAlchemy sees all tables) ───────────
from app.shared.models import User  # noqa: F401
from app.section.user.repositories.user_repository import UserRepository

# ── Route imports ─────────────────────────────────────────────────────────────
# Auth (shared)
from app.section.user.routes import auth

# User-facing routes
from app.section.user.routes import inference, jobs as user_jobs
from app.section.user.routes.files import router as files_router
from app.section.user.routes.files import dicom_router

# Admin-facing routes
from app.section.admin.routes import dataset_preprocess as admin_dataset_preprocess
from app.section.admin.routes import jobs as admin_jobs
from app.section.admin.routes import dashboard as admin_dashboard

# ── Database bootstrap ────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)


def ensure_rbac_columns() -> None:
    """
    Back-fill RBAC columns for environments without Alembic migrations.

    ``create_all()`` does not add new columns to existing tables, so
    we add the role and job_scope columns safely with IF NOT EXISTS.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE IF EXISTS users "
                f"ADD COLUMN IF NOT EXISTS role VARCHAR NOT NULL DEFAULT '{UserRoles.USER}'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE IF EXISTS jobs "
                "ADD COLUMN IF NOT EXISTS job_scope VARCHAR"
            )
        )


ensure_rbac_columns()

# ── Directory bootstrap ───────────────────────────────────────────────────────
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    description="MRI Super-Resolution Pipeline API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Global exception handlers (converts domain exceptions to HTTP responses)
add_exception_handlers(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router registration ───────────────────────────────────────────────────────
_api = APIEndpoints.API_PREFIX  # "/api"

# Authentication
app.include_router(auth.router, prefix=_api)

# User endpoints
app.include_router(user_jobs.router,   prefix=_api)   # GET/DELETE /api/jobs/...
app.include_router(inference.router,   prefix=_api)   # POST /api/infer/...
app.include_router(files_router,       prefix=_api)   # GET /api/download/...
app.include_router(dicom_router,       prefix=_api)   # GET /api/dicom/...

# Admin endpoints
app.include_router(
    admin_dataset_preprocess.router, prefix=_api
)  # POST /api/admin/dataset-preprocess/upload
app.include_router(
    admin_dashboard.router, prefix=_api
)  # GET /api/admin/stats, /api/admin/jobs/active/count, etc.
app.include_router(
    admin_jobs.router, prefix=_api
)  # GET/DELETE/POST /api/admin/jobs/...

# Static file mount — serves pipeline output files
if os.path.exists(settings.OUTPUT_DIR):
    app.mount(
        "/api/files",
        StaticFiles(directory=settings.OUTPUT_DIR),
        name="files",
    )


# ── Health / root endpoints ───────────────────────────────────────────────────
@app.get("/")
async def root():
    """Root endpoint — API identification."""
    return {
        "message": "MRI Super-Resolution API",
        "version": "1.0.0",
        "docs": "/api/docs",
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint used by Docker / load-balancer probes."""
    return {
        "status": "healthy",
        "service": "mri-sr-api",
    }


# ── Super-admin bootstrap ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

if getattr(settings, "SUPER_ADMIN_ENABLED", False):
    db = SessionLocal()
    try:
        repo = UserRepository(db)
        admin_email = getattr(settings, "SUPER_ADMIN_EMAIL", None)
        admin_password = getattr(settings, "SUPER_ADMIN_PASSWORD", None)
        admin_name = getattr(settings, "SUPER_ADMIN_NAME", "superadmin")

        if admin_email and admin_password and not repo.email_exists(admin_email):
            import uuid as _uuid

            new_admin = User(
                id=_uuid.uuid4().hex,
                email=admin_email,
                name=admin_name,
                hashed_password=get_password_hash(admin_password),
                role=UserRoles.SUPER_ADMIN,
            )
            repo.create(new_admin)
    finally:
        db.close()
