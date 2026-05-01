# Database Tables and Connections

This document summarizes the backend database schema and how the application connects its tables together.

## Database Connection Flow

The backend uses SQLAlchemy with a PostgreSQL database.

1. `backend/app/core/config.py` reads `DATABASE_URL` from the environment.
2. `backend/app/core/database.py` creates the SQLAlchemy engine using that URL.
3. `SessionLocal` provides database sessions for request handlers and services.
4. `Base.metadata.create_all(bind=engine)` in `backend/main.py` creates the tables when the application starts.
5. All routes and services access the database through `Depends(get_db)` or repository classes.

In Docker production, the database URL is injected through `docker-compose.prod.yml` and points to the `postgres` service.

## Tables

### 1. `users`

Defined in `backend/app/section/user/models/user.py`.

Columns:
- `id` - primary key
- `email` - unique login identifier
- `name` - display name
- `hashed_password` - password hash
- `created_at` - timestamp when the user was created
- `updated_at` - timestamp when the user record changes
- `role` - RBAC role such as user or admin

Purpose:
- Stores authentication and authorization data
- Acts as the parent table for jobs and uploaded/generated files

### 2. `jobs`

Defined in `backend/app/section/user/models/job.py`.

Columns:
- `id` - primary key
- `user_id` - foreign key to `users.id`
- `status` - job state such as pending, processing, completed, failed
- `progress` - numeric job progress percentage
- `job_type` - logical type such as `preprocess` or `inference`
- `job_scope` - separates dataset/admin jobs from inference/user jobs
- `error_message` - failure reason if the job fails
- `input_files` - JSON list of input file paths
- `output_files` - JSON list of output file paths
- `lr_file_url` - low-resolution output or reference file path
- `hr_file_url` - high-resolution output file path
- `metrics` - JSON object for values such as PSNR or SSIM
- `created_at` - created timestamp
- `updated_at` - last modified timestamp
- `started_at` - processing start time
- `completed_at` - processing completion time

Purpose:
- Tracks preprocessing and inference jobs
- Stores progress, status, and generated outputs
- Provides the main audit trail for user uploads and admin dataset preprocessing

### 3. `files`

Defined in `backend/app/section/user/models/file.py`.

Columns:
- `id` - primary key
- `user_id` - foreign key to `users.id`
- `job_id` - foreign key to `jobs.id` and nullable
- `filename` - stored filename
- `original_filename` - source filename from upload
- `file_path` - filesystem path on disk
- `file_size` - size in bytes
- `file_type` - file category such as `input`, `output_lr`, `output_hr`
- `created_at` - creation timestamp

Purpose:
- Stores metadata for uploaded and generated files
- Links files to both the user who owns them and the job that produced them

## Relationships

### `users` to `jobs`

- One user can own many jobs.
- Relationship is defined with `User.jobs` and `Job.user`.
- The foreign key is `jobs.user_id -> users.id`.

### `users` to `files`

- One user can own many files.
- `files.user_id -> users.id`.
- This lets the system keep a per-user record of uploads and outputs.

### `jobs` to `files`

- One job can be associated with many files.
- `files.job_id -> jobs.id`.
- This connects job records to their inputs and generated outputs.

## Data Separation

The application uses `job_scope` to separate workflows:

- `dataset` - admin dataset preprocessing jobs
- `inference` - user inference jobs

This allows the frontend and backend to query the same `jobs` table while still showing different views for admin and user workflows.

## Schema Initialization

`backend/main.py` also includes a small bootstrap step for existing databases:

- It creates tables with `Base.metadata.create_all(bind=engine)`.
- It backfills RBAC-related columns when needed.
- It adds `role` to `users` and `job_scope` to `jobs` if they are missing.

## Summary

The schema is intentionally small and centered around three tables:

- `users` for identity and roles
- `jobs` for preprocessing and inference tracking
- `files` for upload/output metadata

The `users -> jobs -> files` chain is the main connection path used by the backend services and API routes.
