from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置：先读取系统环境变量，再回退到项目根目录的 .env 文件。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "tiktok-selection-agent"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/tiktok_selection"
    redis_url: str = "redis://localhost:6379/0"
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # mock 用于离线管线验证；openai_compatible 表示任意 OpenAI 兼容模型服务。
    embedding_provider: str = Field(default="mock", pattern="^(mock|openai_compatible)$")
    embedding_model: str = ""
    embedding_dim: int = Field(default=16, ge=2, le=4096)
    # 模型连接信息不绑定具体厂商，支持环境变量和 .env 两种来源。
    model_api_key: SecretStr | None = None
    model_base_url: str | None = None
    chat_model: str = ""

    max_model_calls: int = Field(default=20, ge=1, le=100)
    max_tool_calls: int = Field(default=30, ge=1, le=100)
    agent_timeout_seconds: int = Field(default=300, ge=10, le=3600)

    @property
    def milvus_uri(self) -> str:
        """返回 Milvus 的 HTTP 连接地址，供诊断或后续 SDK 适配使用。"""
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def has_model_credentials(self) -> bool:
        """判断是否已提供真实模型调用所需的密钥和聊天模型名称。"""
        return bool(
            self.model_api_key and self.model_api_key.get_secret_value() and self.chat_model.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """缓存并返回进程内唯一的配置对象，避免重复解析环境变量。"""
    return Settings()
