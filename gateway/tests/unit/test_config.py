from app.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_env in ["dev", "test", "prod"]
    assert settings.admin_token != ""
    assert settings.max_retries == 2
    assert settings.log_raw_payloads is False
