export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  return `${Math.round(value * 100)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export function firstImageUrl(images: Array<{ url: string | null; kind: string }>): string | null {
  return images.find((image) => image.kind === "front" && image.url)?.url ?? images.find((image) => image.url)?.url ?? null;
}
