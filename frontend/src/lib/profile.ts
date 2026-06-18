import profileOptionsJson from "../data/profile-options.json";
import type { ClinicalProfile } from "../api/types";

type ProfileOption = {
  value: string;
  label: string;
  aliases: string[];
};

export type ProfileFieldKey =
  | "skin_types"
  | "scalp_types"
  | "age_band"
  | "sensitivities"
  | "allergies"
  | "conditions";

export type ProfileFieldConfig = {
  label: string;
  mode: "multi" | "single";
  options: ProfileOption[];
};

type ProfileOptions = {
  version: string;
  fields: Record<ProfileFieldKey, ProfileFieldConfig>;
  booleans: Record<"pregnancy" | "lactation", { label: string; aliases: string[] }>;
};

export const profileOptions = profileOptionsJson as ProfileOptions;

export const defaultProfile: ClinicalProfile = {
  skin_types: ["sensitive"],
  hair_types: [],
  scalp_types: [],
  age_band: null,
  allergies: [],
  sensitivities: ["fragrance"],
  pregnancy: false,
  lactation: false,
  conditions: [],
};

export const multiProfileFields: ProfileFieldKey[] = [
  "skin_types",
  "scalp_types",
  "sensitivities",
  "allergies",
  "conditions",
];

const storageKey = "bpv.clinicalProfile.v1";

function normalizeValue(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function aliasIndex(field: ProfileFieldKey): Map<string, string> {
  const index = new Map<string, string>();
  profileOptions.fields[field].options.forEach((option) => {
    index.set(normalizeValue(option.value), option.value);
    option.aliases.forEach((alias) => index.set(normalizeValue(alias), option.value));
  });
  return index;
}

function normalizeListField(field: ProfileFieldKey, values: unknown): string[] {
  const rawValues = Array.isArray(values)
    ? values
    : typeof values === "string"
      ? values.split(",")
      : [];
  const index = aliasIndex(field);
  const normalized = rawValues
    .map((value) => index.get(normalizeValue(String(value))))
    .filter((value): value is string => Boolean(value));
  return Array.from(new Set(normalized));
}

export function normalizeProfile(profile: Partial<ClinicalProfile> | null | undefined): ClinicalProfile {
  const source = profile ?? {};
  return {
    skin_types: normalizeListField("skin_types", source.skin_types),
    hair_types: [],
    scalp_types: normalizeListField("scalp_types", source.scalp_types),
    age_band: normalizeListField("age_band", source.age_band ? [source.age_band] : [])[0] ?? null,
    allergies: normalizeListField("allergies", source.allergies),
    sensitivities: normalizeListField("sensitivities", source.sensitivities),
    pregnancy: Boolean(source.pregnancy),
    lactation: Boolean(source.lactation),
    conditions: normalizeListField("conditions", source.conditions),
  };
}

export function loadProfile(): ClinicalProfile {
  if (typeof window === "undefined") return defaultProfile;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? normalizeProfile({ ...defaultProfile, ...JSON.parse(raw) }) : defaultProfile;
  } catch {
    return defaultProfile;
  }
}

export function saveProfile(profile: ClinicalProfile): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey, JSON.stringify(normalizeProfile(profile)));
}

export function profileOptionLabel(field: ProfileFieldKey, value: string): string {
  return profileOptions.fields[field].options.find((option) => option.value === value)?.label ?? value;
}

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

export function isDefaultProfile(profile: ClinicalProfile): boolean {
  const normalized = normalizeProfile(profile);
  return (
    sameList(normalized.skin_types, defaultProfile.skin_types) &&
    sameList(normalized.hair_types, defaultProfile.hair_types) &&
    sameList(normalized.scalp_types, defaultProfile.scalp_types) &&
    normalized.age_band === defaultProfile.age_band &&
    sameList(normalized.allergies, defaultProfile.allergies) &&
    sameList(normalized.sensitivities, defaultProfile.sensitivities) &&
    normalized.pregnancy === defaultProfile.pregnancy &&
    normalized.lactation === defaultProfile.lactation &&
    sameList(normalized.conditions, defaultProfile.conditions)
  );
}

export function profileSummary(profile: ClinicalProfile): string {
  const normalized = normalizeProfile(profile);
  const parts: string[] = [];
  if (normalized.skin_types.length) {
    parts.push(`${normalized.skin_types.map((value) => profileOptionLabel("skin_types", value).toLowerCase()).join(", ")} skin`);
  }
  if (normalized.scalp_types.length) {
    parts.push(`${normalized.scalp_types.map((value) => profileOptionLabel("scalp_types", value).toLowerCase()).join(", ")}`);
  }
  if (normalized.age_band) parts.push(profileOptionLabel("age_band", normalized.age_band).toLowerCase());
  if (normalized.allergies.length) {
    parts.push(`allergies: ${normalized.allergies.map((value) => profileOptionLabel("allergies", value).toLowerCase()).join(", ")}`);
  }
  if (normalized.sensitivities.length) {
    parts.push(`${normalized.sensitivities.map((value) => profileOptionLabel("sensitivities", value).toLowerCase()).join(", ")} sensitivity`);
  }
  if (normalized.conditions.length) {
    parts.push(`conditions: ${normalized.conditions.map((value) => profileOptionLabel("conditions", value).toLowerCase()).join(", ")}`);
  }
  if (normalized.pregnancy) parts.push("pregnancy");
  if (normalized.lactation) parts.push("lactation");
  return parts.join(" + ") || "no profile details";
}
