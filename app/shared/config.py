from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path
from typing import Dict, Set


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore", env_prefix="")

    # Configuration
    HOST_PATH: Path = (
        "."  # This is used to fully qualify relative paths for Docker code execution container volume mounts
    )
    HOST_CONFIG_PATH: Path = Path("config")  # Base directory for configuration files
    LOG_LEVEL: str = "INFO"  # Log level for logging
    LOG_SERIALIZE: bool = False  # Whether to serialize log messages to JSON

    @property
    def CONFIG_PATH_ABS(self) -> Path:
        """Full path to the configuration directory."""
        return self.HOST_CONFIG_PATH if self.HOST_CONFIG_PATH.is_absolute() else self.HOST_PATH / self.HOST_CONFIG_PATH

    # API settings
    PORT: int = 8000  # Port exposed from the container
    API_PREFIX: str = "/v1"  # API prefix

    # Code execution sandbox settings
    SANDBOX_MAX_EXECUTION_TIME: int = 300  # Docker container execution time limit in seconds

    # File management
    FILE_MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    FILE_MAX_BATCH_COUNT: int = 20  # Maximum number of files per upload request
    FILE_ALLOWED_EXTENSIONS: Set[str] = {
        # Programming languages
        "py",
        "c",
        "cpp",
        "java",
        "php",
        "rb",
        "js",
        "ts",
        # Documents
        "txt",
        "md",
        "html",
        "css",
        "tex",
        "json",
        "csv",
        "xml",
        "docx",
        "xlsx",
        "pptx",
        "pdf",
        # Data formats
        "ipynb",
        "yml",
        "yaml",
        # Archives
        "zip",
        "tar",
        # Images
        "jpg",
        "jpeg",
        "png",
        "gif",
    }

    HOST_FILE_UPLOAD_PATH: Path = Path("uploads")  # Base directory for uploaded files

    @property
    def HOST_FILE_UPLOAD_PATH_ABS(self) -> Path:
        """Full path to the file upload directory. Absolute path is required for Docker volume mounts."""
        return (
            self.HOST_FILE_UPLOAD_PATH
            if self.HOST_FILE_UPLOAD_PATH.is_absolute()
            else self.HOST_PATH / self.HOST_FILE_UPLOAD_PATH
        )

    # File cleanup settings
    CLEANUP_RUN_INTERVAL: int = 3600  # How often to run the cleanup in seconds
    CLEANUP_FILE_MAX_AGE: int = 86400  # How old files can be before they are deleted in seconds

    PY_CONTAINER_IMAGE: str = "jupyter/scipy-notebook:latest"
    R_CONTAINER_IMAGE: str = "jupyter/r-notebook:latest"
    BASH_CONTAINER_IMAGE: str = "jupyter/scipy-notebook:latest"
    # Node 24 (LTS) runs TypeScript natively via type stripping, so one image covers both
    JS_CONTAINER_IMAGE: str = "node:24-slim"
    TS_CONTAINER_IMAGE: str = "node:24-slim"

    @property
    def LANGUAGE_CONTAINERS(self) -> Dict[str, str]:
        """Map language codes to container images."""
        return {
            "py": self.PY_CONTAINER_IMAGE,
            "r": self.R_CONTAINER_IMAGE,
            "bash": self.BASH_CONTAINER_IMAGE,
            "js": self.JS_CONTAINER_IMAGE,
            "ts": self.TS_CONTAINER_IMAGE,
        }

    # Docker execution settings
    MAX_CONCURRENT_CONTAINERS: int = 10  # Maximum number of concurrent Docker containers
    CONTAINER_MEMORY_LIMIT_MB: int = 512  # Memory limit for Docker containers in MB
    CONTAINER_CPU_LIMIT: float = 1.0  # CPU limit for Docker containers (number of cores)
    CONTAINER_PIDS_LIMIT: int = 256  # Max processes per container (fork bomb protection)

    # Docker network settings
    DOCKER_NETWORK_ENABLED: bool = False  # Whether Docker containers have network access


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    logger.info(f"Settings: {settings.HOST_FILE_UPLOAD_PATH_ABS}")
    return settings
