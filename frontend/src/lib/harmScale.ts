export type HarmLevel = {
  severity: string;
  label: string;
  meaning: string;
};

export const harmLevels: HarmLevel[] = [
  {
    severity: "unknown",
    label: "Unknown",
    meaning: "No matching source-backed rule is available for this profile. Unknown is not the same as cleared.",
  },
  {
    severity: "minimal",
    label: "Minimal",
    meaning: "A low-concern rule matched, usually worth noticing only if you already react to this ingredient.",
  },
  {
    severity: "low",
    label: "Low",
    meaning: "May cause mild irritation or sensitivity for some profiles, especially with repeated exposure.",
  },
  {
    severity: "moderate",
    label: "Moderate",
    meaning: "More relevant warning for the selected profile, such as rash, itching, dryness, or sensitization risk.",
  },
  {
    severity: "high",
    label: "High",
    meaning: "Stronger source-backed concern for the selected profile. Consider avoiding or checking with a clinician.",
  },
  {
    severity: "critical",
    label: "Critical",
    meaning: "Reserved for the strongest warnings. Do not treat this as a diagnosis, but take the source-backed concern seriously.",
  },
];

export function harmLevelFor(severity: string): HarmLevel {
  return harmLevels.find((level) => level.severity === severity.toLowerCase()) ?? harmLevels[0];
}
