"""通用模型配置的来源与优先级测试。"""

from pathlib import Path

from app.core.config import Settings


def test_model_configuration_reads_dotenv_and_environment(monkeypatch) -> None:
    """`.env` 提供默认值，系统环境变量覆盖同名密钥。"""
    dotenv_path = Path(__file__).parent / "fixtures" / "model.env"

    # 先确认 .env 可作为本地开发默认配置。
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    dotenv_settings = Settings(_env_file=dotenv_path)
    assert dotenv_settings.model_api_key is not None
    assert dotenv_settings.model_api_key.get_secret_value() == "from-dotenv"
    assert dotenv_settings.chat_model == "dotenv-chat"

    # 再确认部署环境注入的变量拥有更高优先级。
    monkeypatch.setenv("MODEL_API_KEY", "from-environment")
    environment_settings = Settings(_env_file=dotenv_path)
    assert environment_settings.model_api_key is not None
    assert environment_settings.model_api_key.get_secret_value() == "from-environment"
    assert environment_settings.has_model_credentials


def test_dotenv_can_reference_an_existing_system_variable(monkeypatch) -> None:
    """`.env` 可以引用已有系统变量，无需把真实密钥写入项目文件。"""
    dotenv_path = Path(__file__).parent / "fixtures" / "model-indirection.env"
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_MODEL_API_KEY", "from-system-variable")

    settings = Settings(_env_file=dotenv_path)

    assert settings.model_api_key is not None
    assert settings.model_api_key.get_secret_value() == "from-system-variable"
    assert settings.has_model_credentials
