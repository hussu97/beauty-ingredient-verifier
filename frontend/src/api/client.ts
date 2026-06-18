import type {
  ClinicalProfile,
  DirectoryGroup,
  DirectoryProductsPage,
  ImportStatus,
  IngredientDetail,
  IngredientSummary,
  Product,
  ProductDetail,
  RiskEvaluation,
  ScanJob,
  ScanProgress,
  Source,
  SourceConflictProduct,
  SourceTermSummary,
} from "./types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export const REQUEST_TIMEOUT_MS = 30_000;
export const SCAN_TIMEOUT_MS = 120_000;

type RequestOptions = RequestInit & {
  timeoutMs?: number;
};

type FastApiIssue = {
  loc?: unknown[];
  msg?: unknown;
  message?: unknown;
  type?: unknown;
};

export class ApiError extends Error {
  status?: number;
  payload?: unknown;

  constructor(message: string, status?: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseErrorPayload(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return trimmed;
  }
}

function cleanErrorMessage(value: string): string | null {
  const message = value.trim().replace(/\s+/g, " ");
  if (!message || /^<!doctype/i.test(message) || /^<html/i.test(message)) return null;
  return message.length > 240 ? `${message.slice(0, 237)}...` : message;
}

function formatIssue(issue: unknown): string | null {
  if (typeof issue === "string") return cleanErrorMessage(issue);
  if (!isRecord(issue)) return null;

  const typedIssue = issue as FastApiIssue;
  const message = typeof typedIssue.msg === "string"
    ? cleanErrorMessage(typedIssue.msg)
    : typeof typedIssue.message === "string"
      ? cleanErrorMessage(typedIssue.message)
      : typeof typedIssue.type === "string"
        ? typedIssue.type.replace(/_/g, " ")
        : null;
  if (!message) return null;

  const location = Array.isArray(typedIssue.loc)
    ? typedIssue.loc
        .map(String)
        .filter((part) => !["body", "query", "path"].includes(part))
        .join(".")
    : "";
  return location ? `${message} (${location})` : message;
}

function extractErrorMessage(payload: unknown): string | null {
  if (typeof payload === "string") return cleanErrorMessage(payload);
  if (Array.isArray(payload)) {
    const issues = payload.map(formatIssue).filter((issue): issue is string => Boolean(issue));
    return issues.length > 0 ? issues.join("; ") : null;
  }
  if (!isRecord(payload)) return null;

  for (const key of ["detail", "message", "error"]) {
    if (key in payload) {
      const message = extractErrorMessage(payload[key]);
      if (message) return message;
    }
  }

  return null;
}

function errorMessageForStatus(status: number, responseText: string): string {
  const payload = parseErrorPayload(responseText);
  const parsedMessage = extractErrorMessage(payload);
  if (parsedMessage) return parsedMessage;
  if (status === 404) return "The requested resource was not found.";
  if (status === 413) return "The upload is too large. Try a smaller image.";
  if (status === 422) return "The request could not be validated. Please check the form and try again.";
  if (status >= 500) return "The API server had a problem. Please try again.";
  return `Request failed with status ${status}.`;
}

function apiErrorForStatus(status: number, responseText: string) {
  return new ApiError(errorMessageForStatus(status, responseText), status, parseErrorPayload(responseText));
}

function isAbortError(error: unknown) {
  return isRecord(error) && error.name === "AbortError";
}

function sleep(ms: number) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const { timeoutMs = REQUEST_TIMEOUT_MS, signal: callerSignal, ...requestInit } = init ?? {};
  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = globalThis.setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, timeoutMs);
  const abortRequest = () => controller.abort();
  callerSignal?.addEventListener("abort", abortRequest, { once: true });
  if (callerSignal?.aborted) controller.abort();

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...requestInit,
      headers: requestInit.body instanceof FormData
        ? requestInit.headers
        : { "Content-Type": "application/json", ...requestInit.headers },
      signal: controller.signal,
    });
    const text = await response.text();
    if (!response.ok) {
      throw apiErrorForStatus(response.status, text);
    }
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError("The API returned an unreadable response. Please try again.", response.status);
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (isAbortError(error)) {
      throw new ApiError(
        didTimeout
          ? "The request timed out. Please try again."
          : "The request was canceled.",
      );
    }
    throw new ApiError("Unable to reach the API. Please check the server connection and try again.");
  } finally {
    globalThis.clearTimeout(timeoutId);
    callerSignal?.removeEventListener("abort", abortRequest);
  }
}

async function waitForScanCompletion(scan: ScanJob, onProgress: (progress: ScanProgress) => void): Promise<ScanJob> {
  if (scan.status === "completed") return scan;
  if (scan.status === "failed") {
    throw new ApiError(scan.error_message || "The scan could not be completed. Please try again.");
  }

  const startedAt = Date.now();
  let latest = scan;
  onProgress({ phase: "analyzing", percent: null, label: "Matching product" });
  while (Date.now() - startedAt < SCAN_TIMEOUT_MS) {
    await sleep(800);
    latest = await request<ScanJob>(`/scans/${latest.scan_code}`, { timeoutMs: REQUEST_TIMEOUT_MS });
    if (latest.status === "completed") return latest;
    if (latest.status === "failed") {
      throw new ApiError(latest.error_message || "The scan could not be completed. Please try again.");
    }
  }
  throw new ApiError("The scan took too long. Please try a smaller image or try again.");
}

function scanWithProgress(file: File, onProgress: (progress: ScanProgress) => void): Promise<ScanJob> {
  const form = new FormData();
  form.append("file", file);
  onProgress({ phase: "uploading", percent: 0, label: "Uploading image" });

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/scans`);
    xhr.timeout = SCAN_TIMEOUT_MS;

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || event.total === 0) return;
      onProgress({
        phase: "uploading",
        percent: Math.min(99, Math.round((event.loaded / event.total) * 100)),
        label: "Uploading image",
      });
    };
    xhr.upload.onload = () => {
      onProgress({ phase: "analyzing", percent: null, label: "Matching product" });
    };
    xhr.onerror = () => reject(new ApiError("Unable to upload the scan. Please check the API server and try again."));
    xhr.ontimeout = () => reject(new ApiError("The scan took too long. Please try a smaller image or try again."));
    xhr.onabort = () => reject(new ApiError("The scan upload was canceled."));
    xhr.onload = async () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(apiErrorForStatus(xhr.status, xhr.responseText));
        return;
      }
      try {
        const scan = JSON.parse(xhr.responseText) as ScanJob;
        const completedScan = await waitForScanCompletion(scan, onProgress);
        onProgress({ phase: "complete", percent: 100, label: "Scan complete" });
        resolve(completedScan);
      } catch (error) {
        reject(error instanceof ApiError ? error : new ApiError("The scan response could not be read. Please try again."));
      }
    };
    xhr.send(form);
  });
}

export const api = {
  products: (q?: string) =>
    request<Product[]>(`/products${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  product: (productCode: string) => request<ProductDetail>(`/products/${productCode}`),
  directoryGroups: (kind: "brand" | "category", q?: string) =>
    request<DirectoryGroup[]>(
      `/products/directory/groups?kind=${kind}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  directoryProducts: (
    groupKind: "brand" | "category",
    groupCode: string,
    profile: ClinicalProfile,
    pagination: { limit: number; offset: number } = { limit: 24, offset: 0 },
  ) =>
    request<DirectoryProductsPage>("/products/directory/products", {
      method: "POST",
      body: JSON.stringify({
        group_kind: groupKind,
        group_code: groupCode,
        profile,
        limit: pagination.limit,
        offset: pagination.offset,
      }),
    }),
  ingredients: (q?: string) =>
    request<IngredientSummary[]>(`/ingredients${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  ingredient: (ingredientCode: string) => request<IngredientDetail>(`/ingredients/${ingredientCode}`),
  sources: () => request<Source[]>("/sources"),
  sourceTerms: () => request<SourceTermSummary[]>("/sources/terms"),
  sourceConflicts: () => request<SourceConflictProduct[]>("/sources/conflicts"),
  importStatus: () => request<ImportStatus>("/imports/status"),
  scan: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ScanJob>("/scans", { method: "POST", body: form });
  },
  scanWithProgress,
  scanByCode: (scanCode: string) => request<ScanJob>(`/scans/${scanCode}`),
  evaluateRisk: (productCode: string, profile: ClinicalProfile) =>
    request<RiskEvaluation>("/risk/evaluate", {
      method: "POST",
      body: JSON.stringify({ product_code: productCode, profile }),
    }),
};
