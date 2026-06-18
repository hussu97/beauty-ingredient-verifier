import { afterEach, describe, expect, it, vi } from "vitest";
import { api, REQUEST_TIMEOUT_MS, SCAN_TIMEOUT_MS } from "../api/client";
import type { ClinicalProfile, ScanProgress } from "../api/types";

const scanResponse = {
  scan_code: "scn_1",
  upload_filename: "product.jpg",
  status: "completed",
  barcode: null,
  ocr_text: null,
  extracted_brand: null,
  extracted_product_name: null,
  extracted_ingredient_text: null,
  confidence_score: 0.9,
  matched_product_code: "prd_1",
  error_message: null,
  candidates: [],
  created_at: "2026-06-18T00:00:00Z",
  updated_at: "2026-06-18T00:00:00Z",
};

describe("api scan progress", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports exact upload progress before indeterminate analysis", async () => {
    class FakeXMLHttpRequest {
      upload: {
        onprogress?: (event: ProgressEvent) => void;
        onload?: () => void;
      } = {};
      status = 200;
      responseText = JSON.stringify(scanResponse);
      timeout = 0;
      onload?: () => void;
      onerror?: () => void;
      ontimeout?: () => void;
      onabort?: () => void;

      open = vi.fn();

      send = vi.fn(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
        this.upload.onload?.();
        this.onload?.();
      });
    }

    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    const events: ScanProgress[] = [];
    const file = new Blob(["image"], { type: "image/jpeg" }) as File;

    const scan = await api.scanWithProgress(file, (event) => events.push(event));

    expect(scan.scan_code).toBe("scn_1");
    expect(events).toEqual([
      { phase: "uploading", percent: 0, label: "Uploading image" },
      { phase: "uploading", percent: 50, label: "Uploading image" },
      { phase: "analyzing", percent: null, label: "Matching product" },
      { phase: "complete", percent: 100, label: "Scan complete" },
    ]);
  });

  it("uses a friendly timeout error when scan upload takes too long", async () => {
    const createdRequests: Array<{ timeout: number }> = [];

    class FakeXMLHttpRequest {
      upload: {
        onprogress?: (event: ProgressEvent) => void;
        onload?: () => void;
      } = {};
      status = 0;
      responseText = "";
      timeout = 0;
      onload?: () => void;
      onerror?: () => void;
      ontimeout?: () => void;
      onabort?: () => void;

      constructor() {
        createdRequests.push(this);
      }

      open = vi.fn();
      send = vi.fn(() => {
        this.ontimeout?.();
      });
    }

    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    const file = new Blob(["image"], { type: "image/jpeg" }) as File;

    await expect(api.scanWithProgress(file, vi.fn())).rejects.toMatchObject({
      message: "The scan took too long. Please try a smaller image or try again.",
    });
    expect(createdRequests[0]?.timeout).toBe(SCAN_TIMEOUT_MS);
  });

  it("polls pending scans until the backend marks them complete", async () => {
    vi.useFakeTimers();
    const pendingScan = { ...scanResponse, scan_code: "scn_pending", status: "pending", matched_product_code: null };
    const completedScan = { ...scanResponse, scan_code: "scn_pending", status: "completed" };
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain("/scans/scn_pending");
      return new Response(JSON.stringify(completedScan), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    class FakeXMLHttpRequest {
      upload: {
        onprogress?: (event: ProgressEvent) => void;
        onload?: () => void;
      } = {};
      status = 202;
      responseText = JSON.stringify(pendingScan);
      timeout = 0;
      onload?: () => void;
      onerror?: () => void;
      ontimeout?: () => void;
      onabort?: () => void;

      open = vi.fn();
      send = vi.fn(() => {
        this.upload.onload?.();
        this.onload?.();
      });
    }

    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    const events: ScanProgress[] = [];
    const file = new Blob(["image"], { type: "image/jpeg" }) as File;
    const promise = api.scanWithProgress(file, (event) => events.push(event));

    await vi.advanceTimersByTimeAsync(800);
    const scan = await promise;

    expect(scan.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(events[events.length - 1]).toEqual({ phase: "complete", percent: 100, label: "Scan complete" });
  });
});

describe("api errors", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("parses FastAPI detail strings into friendly errors", async () => {
    const fetchMock = vi.fn(async () => (
      new Response(JSON.stringify({ detail: "Product not found" }), { status: 404 })
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.product("prd_missing")).rejects.toMatchObject({
      message: "Product not found",
      status: 404,
    });
  });

  it("parses FastAPI validation issues without exposing raw JSON", async () => {
    const fetchMock = vi.fn(async () => (
      new Response(JSON.stringify({
        detail: [
          { loc: ["body", "file"], msg: "Field required", type: "missing" },
          { loc: ["query", "limit"], msg: "Input should be greater than 0", type: "greater_than" },
        ],
      }), { status: 422 })
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.products()).rejects.toMatchObject({
      message: "Field required (file); Input should be greater than 0 (limit)",
      status: 422,
    });
  });

  it("aborts fetch requests that exceed the request timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(Object.assign(new Error("Aborted"), { name: "AbortError" }));
        });
      })
    ));
    vi.stubGlobal("fetch", fetchMock);

    const requestPromise = api.products();
    const expectation = expect(requestPromise).rejects.toMatchObject({
      message: "The request timed out. Please try again.",
    });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

    await expectation;
  });
});

describe("directory API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes search text when loading directory groups", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain("/products/directory/groups?kind=brand&q=mac");
      return new Response(JSON.stringify([]), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.directoryGroups("brand", "mac");

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("sends limit and offset for paged directory products", async () => {
    const profile: ClinicalProfile = {
      skin_types: ["sensitive"],
      hair_types: [],
      scalp_types: [],
      age_band: null,
      allergies: [],
      sensitivities: [],
      pregnancy: false,
      lactation: false,
      conditions: [],
    };
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body).toMatchObject({
        group_kind: "brand",
        group_code: "brd_1",
        limit: 12,
        offset: 24,
      });
      return new Response(JSON.stringify({
        items: [],
        total: 30,
        limit: 12,
        offset: 24,
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = await api.directoryProducts("brand", "brd_1", profile, {
      limit: 12,
      offset: 24,
    });

    expect(page.total).toBe(30);
    expect(page.offset).toBe(24);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("source audit API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads source terms and conflicts", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/sources/terms")) {
        return new Response(JSON.stringify([{ term_code: "term_1", term_type: "concern" }]), { status: 200 });
      }
      if (url.includes("/sources/conflicts")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const terms = await api.sourceTerms();
    const conflicts = await api.sourceConflicts();

    expect(terms[0].term_code).toBe("term_1");
    expect(conflicts).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
