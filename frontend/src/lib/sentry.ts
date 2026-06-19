import * as Sentry from "@sentry/react";

const DEFAULT_PRODUCTION_DSN =
  "https://4321d8269749044df11524e167d5f267@o4511214385364992.ingest.us.sentry.io/4511591614644224";

export type SentryRuntimeConfig = {
  dsn?: string;
  environment?: string;
  release?: string;
  tracesSampleRate?: string | number;
};

export function readSentryConfig(): SentryRuntimeConfig {
  return {
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment:
      import.meta.env.VITE_SENTRY_ENVIRONMENT ??
      import.meta.env.VITE_APP_ENV ??
      import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE,
    tracesSampleRate: import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE,
  };
}

export function parseSentrySampleRate(value: string | number | undefined, fallback: number): number {
  if (value === undefined || value === "") {
    return fallback;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(1, Math.max(0, parsed));
}

export function resolveSentryDsn(config: SentryRuntimeConfig): string | undefined {
  if (config.dsn) {
    return config.dsn;
  }
  if (config.environment === "production") {
    return DEFAULT_PRODUCTION_DSN;
  }
  return undefined;
}

export function initSentry(config: SentryRuntimeConfig = readSentryConfig()): boolean {
  if (config.environment !== "production") {
    return false;
  }

  const dsn = resolveSentryDsn(config);
  if (!dsn) {
    return false;
  }

  Sentry.init({
    dsn,
    environment: config.environment,
    release: config.release,
    tracesSampleRate: parseSentrySampleRate(config.tracesSampleRate, 0.1),
    sendDefaultPii: false,
  });
  return true;
}
