"""Application configuration."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "MRI Super-Resolution API"
    DEBUG: bool = True
    SECRET_KEY: str
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database
    DATABASE_URL: str
    
    # Redis
    REDIS_URL: str
    
    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    
    # File Storage
    UPLOAD_DIR: str = "./data/uploads"
    OUTPUT_DIR: str = "./data/outputs"
    MAX_UPLOAD_SIZE: int = 524288000  # 500MB
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",  # Vite dev server (default)
        "http://localhost:3000",  # Alternative port
        "http://127.0.0.1:5173",  # Alternative localhost
    ]
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Model
    MODEL_PATH: str = "./models/best_model.pth"

    # mri_sr_pipeline integration
    PIPELINE_DIR: str = "../mri_sr_pipeline"
    PIPELINE_CONFIG: str = "../mri_sr_pipeline/configs/config.yaml"
    TEMPLATE_DIR: str = "../mri_sr_pipeline/data/templates"

    # Processing
    MAX_CONCURRENT_JOBS: int = 2
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
