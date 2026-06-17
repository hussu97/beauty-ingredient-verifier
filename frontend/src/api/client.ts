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
} from "./types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init.headers
      : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function scanWithProgress(file: File, onProgress: (progress: ScanProgress) => void): Promise<ScanJob> {
  const form = new FormData();
  form.append("file", file);
  onProgress({ phase: "uploading", percent: 0, label: "Uploading image" });

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/scans`);

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
    xhr.onerror = () => reject(new Error("Scan request failed"));
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(xhr.responseText || `Request failed: ${xhr.status}`));
        return;
      }
      onProgress({ phase: "complete", percent: 100, label: "Scan complete" });
      resolve(JSON.parse(xhr.responseText) as ScanJob);
    };
    xhr.send(form);
  });
}

export const api = {
  products: (q?: string) =>
    request<Product[]>(`/products${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  product: (productCode: string) => request<ProductDetail>(`/products/${productCode}`),
  directoryGroups: (kind: "brand" | "category") =>
    request<DirectoryGroup[]>(`/products/directory/groups?kind=${kind}`),
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
