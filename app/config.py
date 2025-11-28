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
    audio_sample_rate: int = 16000
    chunk_max_duration: float = 30.0
    frame_interval_seconds: float = 2.0
    embedding_dimension: int = 1024
    pipeline_version: str = "v1.0.0"
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

    raw_storage_dir: Path = BASE_DIR / "data" / "raw"
    audio_intermediate_dir: Path = BASE_DIR / "data" / "intermediate" / "audio"
    video_intermediate_dir: Path = BASE_DIR / "data" / "intermediate" / "video"
    final_instances_dir: Path = BASE_DIR / "data" / "final_instances"
    logs_dir: Path = BASE_DIR / "data" / "logs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
