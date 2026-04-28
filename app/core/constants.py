"""Application constants and configuration values."""


class APIEndpoints:
    """API endpoint path constants."""
    
    # Base prefixes
    API_PREFIX = "/api"
    
    # Auth endpoints
    AUTH_PREFIX = "/auth"
    AUTH_REGISTER = "/register"
    AUTH_LOGIN = "/login"
    AUTH_ME = "/me"
    
    # Job endpoints
    JOBS_PREFIX = "/jobs"
    JOBS_LIST = ""
    JOBS_DETAIL = "/{job_id}"
    JOBS_DELETE = "/{job_id}"
    JOBS_TRIGGER = "/{job_id}/trigger"
    
    # Preprocessing endpoints
    PREPROCESS_PREFIX = "/preprocess"
    PREPROCESS_UPLOAD = "/upload"
    
    # Inference endpoints
    INFERENCE_PREFIX = "/infer"
    INFERENCE_RUN = ""
    INFERENCE_PREPROCESS_UPLOAD = "/preprocess-upload"


class HTTPStatusMessages:
    """Standard HTTP status messages."""
    
    # Success messages
    CREATED = "Resource created successfully"
    UPDATED = "Resource updated successfully"
    DELETED = "Resource deleted successfully"
    
    # Auth messages
    REGISTRATION_SUCCESS = "User registered successfully"
    LOGIN_SUCCESS = "Login successful"
    LOGOUT_SUCCESS = "Logout successful"
    
    # Job messages
    JOB_CREATED = "Job created successfully"
    JOB_STARTED = "Job started successfully"
    JOB_COMPLETED = "Job completed successfully"
    
    # Upload messages
    UPLOAD_SUCCESS = "Files uploaded successfully"
    PREPROCESSING_STARTED = "Preprocessing started"
    INFERENCE_STARTED = "Inference started"


class ErrorMessages:
    """Standard error messages."""
    
    # Auth errors
    INVALID_CREDENTIALS = "Incorrect email or password"
    EMAIL_ALREADY_EXISTS = "Email already registered"
    UNAUTHORIZED = "Authentication required"
    FORBIDDEN = "Access forbidden"
    
    # Resource errors
    RESOURCE_NOT_FOUND = "{resource} not found"
    RESOURCE_ALREADY_EXISTS = "{resource} already exists"
    
    # Job errors
    JOB_NOT_FOUND = "Job not found"
    INVALID_JOB_STATE = "Job is in invalid state"
    NO_INPUT_FILES = "No input files found"
    PREPROCESSING_NOT_COMPLETE = "Preprocessing must be completed before running inference"
    
    # File errors
    NO_FILES_PROVIDED = "No files provided"
    INVALID_FILE_TYPE = "Invalid file type"
    FILE_TOO_LARGE = "File size exceeds maximum allowed size"
    
    # Validation errors
    VALIDATION_ERROR = "Validation error"
    INVALID_INPUT = "Invalid input provided"


class FileConstants:
    """File-related constants."""
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS = ['.nii', '.nii.gz', '.gz']
    
    # File types
    FILE_TYPE_INPUT = "input"
    FILE_TYPE_OUTPUT_LR = "output_lr"
    FILE_TYPE_OUTPUT_HR = "output_hr"
    
    # Chunk size for file uploads
    UPLOAD_CHUNK_SIZE = 8192  # 8KB


class JobConstants:
    """Job-related constants."""
    
    # Job types
    JOB_TYPE_PREPROCESS = "preprocess"
    JOB_TYPE_INFERENCE = "inference"
    
    # Celery queues
    QUEUE_PREPROCESSING = "preprocessing"
    QUEUE_INFERENCE = "inference"


class ValidationRules:
    """Validation rule constants."""
    
    # User validation
    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 128
    MIN_NAME_LENGTH = 2
    MAX_NAME_LENGTH = 100
    
    # Job validation
    MIN_JOB_NAME_LENGTH = 3
    MAX_JOB_NAME_LENGTH = 50


class EndpointDocs:
    """API endpoint documentation (summaries and descriptions)."""
    
    # Auth endpoints
    AUTH_REGISTER_SUMMARY = "Register new user"
    AUTH_REGISTER_DESC = "Create a new user account with email and password"
    AUTH_LOGIN_SUMMARY = "User login"
    AUTH_LOGIN_DESC = "Authenticate user and return access token"
    AUTH_ME_SUMMARY = "Get current user"
    AUTH_ME_DESC = "Get information about the currently authenticated user"
    
    # Job endpoints
    JOBS_LIST_SUMMARY = "List jobs"
    JOBS_LIST_DESC = "Get all jobs for the authenticated user"
    JOBS_GET_SUMMARY = "Get job details"
    JOBS_GET_DESC = "Get details of a specific job by ID"
    JOBS_DELETE_SUMMARY = "Delete job"
    JOBS_DELETE_DESC = "Delete a job and its associated files"
    JOBS_TRIGGER_SUMMARY = "Trigger job"
    JOBS_TRIGGER_DESC = "Manually trigger a job that's stuck in PENDING status"
    
    # Preprocessing endpoints
    PREPROCESS_UPLOAD_SUMMARY = "Upload and preprocess MRI files"
    PREPROCESS_UPLOAD_DESC = "Upload NIfTI MRI files and start preprocessing pipeline"
    
    # Inference endpoints
    INFERENCE_RUN_SUMMARY = "Run inference"
    INFERENCE_RUN_DESC = "Run super-resolution inference on preprocessed low-resolution files"
    INFERENCE_PREPROCESS_UPLOAD_SUMMARY = "Upload low-resolution MRI for inference preprocessing"
    INFERENCE_PREPROCESS_UPLOAD_DESC = "Upload a low-resolution NIfTI MRI scan and run inference preprocessing pipeline"
