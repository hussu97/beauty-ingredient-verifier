import * as Sentry from "@sentry/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initSentry, parseSentrySampleRate, resolveSentryDsn } from "../lib/sentry";

vi.mock("@sentry/react", () => ({
  init: vi.fn(),
}));

describe("sentry setup", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not initialize outside production", () => {
    const enabled = initSentry({
      dsn: "https://example.invalid/1",
      environment: "local",
    });

    expect(enabled).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it("initializes production with explicit config", () => {
    const enabled = initSentry({
      dsn: "https://example.invalid/1",
      environment: "production",
      release: "frontend@abc123",
      tracesSampleRate: "0.25",
    });

    expect(enabled).toBe(true);
    expect(Sentry.init).toHaveBeenCalledWith({
      dsn: "https://example.invalid/1",
      environment: "production",
      release: "frontend@abc123",
      tracesSampleRate: 0.25,
      sendDefaultPii: false,
    });
  });

  it("falls back to the production frontend DSN", () => {
    expect(resolveSentryDsn({ environment: "production" })).toContain(
      "4511591614644224",
    );
  });

  it("clamps invalid sample rates", () => {
    expect(parseSentrySampleRate("-1", 0.1)).toBe(0);
    expect(parseSentrySampleRate("2", 0.1)).toBe(1);
    expect(parseSentrySampleRate("nope", 0.1)).toBe(0.1);
  });
});
