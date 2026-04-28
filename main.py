from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import engine, Base
from app.api.routes import auth, preprocess, jobs, inference, files
from app.api.routes.files import dicom_router
from app.middleware import add_exception_handlers
from app.core.constants import APIEndpoints
import os

# Create database tables
Base.metadata.create_all(bind=engine)

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
