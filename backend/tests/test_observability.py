from unittest.mock import Mock

from app.config import Settings
from app.observability import configure_sentry


def test_sentry_is_disabled_outside_production(monkeypatch):
    init = Mock()
    monkeypatch.setattr("app.observability.sentry_sdk.init", init)
    settings = Settings(env="local", sentry_dsn="https://example.invalid/1")

    assert configure_sentry(settings) is False
    init.assert_not_called()


def test_sentry_uses_configured_production_dsn(monkeypatch):
    init = Mock()
    monkeypatch.setattr("app.observability.sentry_sdk.init", init)
    settings = Settings(
        env="production",
        sentry_dsn="https://example.invalid/1",
        sentry_release="api@abc123",
        sentry_traces_sample_rate=0.25,
        sentry_profiles_sample_rate=0.05,
    )

    assert configure_sentry(settings) is True
    init.assert_called_once()
    kwargs = init.call_args.kwargs
    assert kwargs["dsn"] == "https://example.invalid/1"
    assert kwargs["environment"] == "production"
    assert kwargs["release"] == "api@abc123"
    assert kwargs["traces_sample_rate"] == 0.25
    assert kwargs["profiles_sample_rate"] == 0.05
    assert kwargs["send_default_pii"] is False
