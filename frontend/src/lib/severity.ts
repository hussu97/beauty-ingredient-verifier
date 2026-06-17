export const severityOrder = ["unknown", "minimal", "low", "moderate", "high", "critical"];

export function severityLabel(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === "unknown") return "Unknown";
  if (normalized === "minimal") return "Minimal";
  if (normalized === "low") return "Low";
  if (normalized === "moderate") return "Moderate";
  if (normalized === "high") return "High";
  if (normalized === "critical") return "Critical";
  return "Unknown";
}

export function severityClass(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === "critical" || normalized === "high") return "severity-high";
  if (normalized === "moderate") return "severity-moderate";
  if (normalized === "low" || normalized === "minimal") return "severity-low";
  return "severity-unknown";
}
