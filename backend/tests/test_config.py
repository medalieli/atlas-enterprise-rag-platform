from app.core.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_NAME", "Configured App")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db/test")
    monkeypatch.setenv("POSTGRES_DB", "test")
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pass")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.app_name == "Configured App"
    assert settings.api_port == 9000
    assert settings.database_url == "postgresql+asyncpg://user:pass@db/test"
    assert settings.postgres_db == "test"
    assert settings.postgres_user == "user"
    assert settings.postgres_password.get_secret_value() == "pass"
    assert settings.openai_api_key is None


def test_empty_optional_secret_is_unset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.openai_api_key is None
