from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    """Global application configuration."""

    es_host: str = Field("http://localhost:9200", env="ES_HOST")
    es_user: str | None = Field(None, env="ES_USER")
    es_password: str | None = Field(None, env="ES_PASSWORD")
    es_index: str = Field("rag-mm-segments", env="ES_INDEX")
    es_skip_tls: bool = Field(False, env="ES_SKIP_TLS")
    es_enabled: bool = Field(True, env="ES_ENABLED")
    embedding_model: str = Field("mock-text-embedding", env="EMBEDDING_MODEL")
    embedding_provider: str = Field("bailian", env="EMBEDDING_PROVIDER")
    audio_sample_rate: int = 16000
    chunk_max_duration: float = 30.0
    frame_interval_seconds: float = 2.0
    embedding_dimension: int = 1024
    pipeline_version: str = "v0.1.0"
    whisper_model: str = Field("base", env="WHISPER_MODEL")
    asr_language: str | None = Field(None, env="ASR_LANGUAGE")
    bailian_api_key: str | None = Field(None, env="BAILIAN_API_KEY")
    bailian_base_url: str = Field("https://dashscope.aliyuncs.com", env="BAILIAN_BASE_URL")
    bailian_asr_model: str = Field("paraformer-v1", env="BAILIAN_ASR_MODEL")
    bailian_embedding_model: str = Field("text-embedding-v1", env="BAILIAN_EMBEDDING_MODEL")
    bailian_multimodal_model: str = Field("qwen-vl-plus", env="BAILIAN_MULTIMODAL_MODEL")
    bailian_llm_model: str = Field("qwen3", env="BAILIAN_LLM_MODEL")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    video_max_keyframes: int = Field(60, env="VIDEO_MAX_KEYFRAMES")
    ollama_base_url: str = Field("http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_embedding_model: str = Field("nomic-embed-text", env="OLLAMA_EMBEDDING_MODEL")
    ollama_timeout: int = Field(60, env="OLLAMA_TIMEOUT")

    api_auth_required: bool = Field(True, env="API_AUTH_REQUIRED")
    api_secrets_path: str | None = Field("app_secrets.json", env="API_SECRETS_PATH")
    upload_max_files: int = Field(4, env="UPLOAD_MAX_FILES")
    upload_max_batch_mb: float = Field(4096.0, env="UPLOAD_MAX_BATCH_MB")
    audio_max_size_mb: float = Field(2048.0, env="AUDIO_MAX_SIZE_MB")
    video_max_size_mb: float = Field(4096.0, env="VIDEO_MAX_SIZE_MB")
    audio_max_duration_sec: float | None = Field(21600.0, env="AUDIO_MAX_DURATION_SEC")
    video_max_duration_sec: float | None = Field(10800.0, env="VIDEO_MAX_DURATION_SEC")

    celery_broker_url: str = Field("redis://localhost:6379/0", env="CELERY_BROKER_URL")
    celery_result_backend: str = Field("redis://localhost:6379/1", env="CELERY_RESULT_BACKEND")
    celery_default_queue: str = Field("ingest_cpu", env="CELERY_DEFAULT_QUEUE")
    celery_io_queue: str = Field("ingest_io", env="CELERY_IO_QUEUE")
    celery_cpu_queue: str = Field("ingest_cpu", env="CELERY_CPU_QUEUE")
    flower_address: str = Field("0.0.0.0", env="FLOWER_ADDRESS")
    flower_port: int = Field(5555, env="FLOWER_PORT")
    flower_health_retries: int = Field(30, env="FLOWER_HEALTH_RETRIES")
    flower_strict: bool = Field(False, env="FLOWER_STRICT")

    minio_enabled: bool = Field(False, env="MINIO_ENABLED")
    minio_endpoint: str = Field("http://localhost:9000", env="MINIO_ENDPOINT")
    minio_access_key: str | None = Field("minioadmin", env="MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field("minioadmin", env="MINIO_SECRET_KEY")
    minio_bucket: str = Field("mm-rag", env="MINIO_BUCKET")

    data_root: Path = DATA_DIR
    raw_storage_dir: Path = BASE_DIR / "data" / "raw"
    audio_intermediate_dir: Path = BASE_DIR / "data" / "intermediate" / "audio"
    video_intermediate_dir: Path = BASE_DIR / "data" / "intermediate" / "video"
    final_instances_dir: Path = BASE_DIR / "data" / "final_instances"
    logs_dir: Path = BASE_DIR / "data" / "logs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
