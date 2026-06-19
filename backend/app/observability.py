import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.config import Settings


def configure_sentry(settings: Settings) -> bool:
    if settings.env != "production":
        return False

    dsn = settings.resolved_sentry_dsn
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.env,
        release=settings.sentry_release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        integrations=[FastApiIntegration(transaction_style="endpoint")],
    )
    return True
