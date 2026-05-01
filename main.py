from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import engine, Base
from app.core.database import SessionLocal
from app.core.auth import get_password_hash
from app.section.user.repositories.user_repository import UserRepository
from app.section.user.models import User
from app.section.user.routes import auth, preprocess, jobs, inference, files
from app.section.user.routes.files import dicom_router
from app.section.admin.routes import dataset_preprocess as admin_dataset_preprocess
from app.middleware import add_exception_handlers
from app.core.constants import APIEndpoints, UserRoles
from sqlalchemy import text
import os

# Create database tables
Base.metadata.create_all(bind=engine)


def ensure_rbac_columns() -> None:
    """Backfill schema for environments without migrations.

    `create_all()` does not add new columns to existing tables, so add RBAC
    columns safely if they are missing.
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

# Create directories
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="MRI Super-Resolution Pipeline API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Add global exception handlers (middleware for error handling)
add_exception_handlers(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix=APIEndpoints.API_PREFIX)
app.include_router(preprocess.router, prefix=APIEndpoints.API_PREFIX)
app.include_router(jobs.router, prefix=APIEndpoints.API_PREFIX)
app.include_router(inference.router, prefix=APIEndpoints.API_PREFIX)
app.include_router(files.router, prefix=APIEndpoints.API_PREFIX)
app.include_router(dicom_router, prefix=APIEndpoints.API_PREFIX)
app.include_router(admin_dataset_preprocess.router, prefix=APIEndpoints.API_PREFIX)

# Mount static files for serving outputs
if os.path.exists(settings.OUTPUT_DIR):
    app.mount("/api/files", StaticFiles(directory=settings.OUTPUT_DIR), name="files")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "MRI Super-Resolution API",
        "version": "1.0.0",
        "docs": "/api/docs"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "mri-sr-api"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )


# Bootstrap super admin from environment if enabled
if getattr(settings, "SUPER_ADMIN_ENABLED", False):
    db = SessionLocal()
    try:
        repo = UserRepository(db)
        admin_email = getattr(settings, "SUPER_ADMIN_EMAIL", None)
        admin_password = getattr(settings, "SUPER_ADMIN_PASSWORD", None)
        admin_name = getattr(settings, "SUPER_ADMIN_NAME", "superadmin")

        if admin_email and admin_password and not repo.email_exists(admin_email):
            new_admin = User(
                id=__import__("uuid").uuid4().hex,
                email=admin_email,
                name=admin_name,
                hashed_password=get_password_hash(admin_password),
                role=UserRoles.SUPER_ADMIN,
            )
            repo.create(new_admin)
    finally:
        db.close()
