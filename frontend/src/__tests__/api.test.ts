import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
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
      onload?: () => void;
      onerror?: () => void;

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
