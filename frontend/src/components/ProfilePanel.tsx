import { Check, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import type { ClinicalProfile } from "../api/types";
import {
  defaultProfile,
  multiProfileFields,
  normalizeProfile,
  profileOptionLabel,
  profileOptions,
  saveProfile,
  type ProfileFieldKey,
} from "../lib/profile";

type Props = {
  profile: ClinicalProfile;
  onChange: (profile: ClinicalProfile) => void;
};

type DropdownKey = ProfileFieldKey | "pregnancy_lactation";

type DropdownProps = {
  children: ReactNode;
  count: number;
  isOpen: boolean;
  onClose: () => void;
  label: string;
  onToggle: () => void;
  summary: string;
};

function selectedValues(profile: ClinicalProfile, field: ProfileFieldKey): string[] {
  if (field === "age_band") return profile.age_band ? [profile.age_band] : [];
  const value = profile[field];
  return Array.isArray(value) ? value : [];
}

function summarizeSelection(field: ProfileFieldKey, values: string[]): string {
  if (values.length === 0) return "Not specified";
  const labels = values.map((value) => profileOptionLabel(field, value));
  if (labels.length <= 2) return labels.join(", ");
  return `${labels.slice(0, 2).join(", ")} +${labels.length - 2}`;
}

function DropdownShell({ children, count, isOpen, label, onClose, onToggle, summary }: DropdownProps) {
  return (
    <div
      className="profile-dropdown"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          if (isOpen) onClose();
        }
      }}
    >
      <button
        aria-expanded={isOpen}
        className="profile-dropdown-trigger"
        onClick={onToggle}
        type="button"
      >
        <span>
          <small>{label}</small>
          <strong>{summary}</strong>
        </span>
        <span className="profile-trigger-meta">
          {count > 0 && <em>{count}</em>}
          <ChevronDown size={17} />
        </span>
      </button>
      {isOpen && (
        <div className="profile-dropdown-menu">
          {children}
        </div>
      )}
    </div>
  );
}

export default function ProfilePanel({ profile, onChange }: Props) {
  const [draft, setDraft] = useState<ClinicalProfile>(() => normalizeProfile(profile));
  const [openDropdown, setOpenDropdown] = useState<DropdownKey | null>(null);
  const normalizedDraft = useMemo(() => normalizeProfile(draft), [draft]);

  useEffect(() => {
    setDraft(normalizeProfile(profile));
  }, [profile]);

  function toggleDropdown(key: DropdownKey) {
    setOpenDropdown((current) => (current === key ? null : key));
  }

  function setMultiValue(field: ProfileFieldKey, value: string) {
    setDraft((current) => {
      const normalized = normalizeProfile(current);
      const currentValues = selectedValues(normalized, field);
      const nextValues = currentValues.includes(value)
        ? currentValues.filter((item) => item !== value)
        : [...currentValues, value];
      return normalizeProfile({ ...normalized, [field]: nextValues });
    });
  }

  function setAgeBand(value: string) {
    setDraft((current) => normalizeProfile({ ...current, age_band: value || null }));
    setOpenDropdown(null);
  }

  function setBooleanValue(field: "pregnancy" | "lactation") {
    setDraft((current) => normalizeProfile({ ...current, [field]: !current[field] }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = normalizeProfile(normalizedDraft);
    saveProfile(next);
    onChange(next);
    setOpenDropdown(null);
  }

  function resetProfile() {
    saveProfile(defaultProfile);
    setDraft(defaultProfile);
    onChange(defaultProfile);
    setOpenDropdown(null);
  }

  const pregnancyCount = Number(normalizedDraft.pregnancy) + Number(normalizedDraft.lactation);
  const pregnancySummary = [
    normalizedDraft.pregnancy ? profileOptions.booleans.pregnancy.label : null,
    normalizedDraft.lactation ? profileOptions.booleans.lactation.label : null,
  ].filter(Boolean).join(", ") || "Not specified";

  return (
    <form className="profile-panel" onSubmit={onSubmit}>
      <div className="profile-summary">
        <div>
          <span className="eyebrow">Step 1 · profile</span>
          <h2>Personalize warnings</h2>
        </div>
        <button type="button" className="text-button" onClick={resetProfile}>Reset</button>
      </div>

      <div className="profile-fields dropdown-fields">
        {multiProfileFields.map((field) => {
          const config = profileOptions.fields[field];
          const selected = selectedValues(normalizedDraft, field);
          return (
            <DropdownShell
              count={selected.length}
              isOpen={openDropdown === field}
              key={field}
              label={config.label}
              onClose={() => setOpenDropdown(null)}
              onToggle={() => toggleDropdown(field)}
              summary={summarizeSelection(field, selected)}
            >
              {config.options.map((option) => {
                const isSelected = selected.includes(option.value);
                return (
                  <button
                    className={isSelected ? "profile-option selected" : "profile-option"}
                    key={option.value}
                    onClick={() => setMultiValue(field, option.value)}
                    type="button"
                  >
                    <span>{option.label}</span>
                    {isSelected && <Check size={16} />}
                  </button>
                );
              })}
            </DropdownShell>
          );
        })}

        <DropdownShell
          count={normalizedDraft.age_band ? 1 : 0}
          isOpen={openDropdown === "age_band"}
          label={profileOptions.fields.age_band.label}
          onClose={() => setOpenDropdown(null)}
          onToggle={() => toggleDropdown("age_band")}
          summary={normalizedDraft.age_band ? profileOptionLabel("age_band", normalizedDraft.age_band) : "Not infant/child"}
        >
          <button
            className={!normalizedDraft.age_band ? "profile-option selected" : "profile-option"}
            onClick={() => setAgeBand("")}
            type="button"
          >
            <span>Not infant/child</span>
            {!normalizedDraft.age_band && <Check size={16} />}
          </button>
          {profileOptions.fields.age_band.options.map((option) => {
            const isSelected = normalizedDraft.age_band === option.value;
            return (
              <button
                className={isSelected ? "profile-option selected" : "profile-option"}
                key={option.value}
                onClick={() => setAgeBand(option.value)}
                type="button"
              >
                <span>{option.label}</span>
                {isSelected && <Check size={16} />}
              </button>
            );
          })}
        </DropdownShell>

        <DropdownShell
          count={pregnancyCount}
          isOpen={openDropdown === "pregnancy_lactation"}
          label="Pregnancy and lactation"
          onClose={() => setOpenDropdown(null)}
          onToggle={() => toggleDropdown("pregnancy_lactation")}
          summary={pregnancySummary}
        >
          {(["pregnancy", "lactation"] as const).map((field) => {
            const isSelected = normalizedDraft[field];
            return (
              <button
                className={isSelected ? "profile-option selected" : "profile-option"}
                key={field}
                onClick={() => setBooleanValue(field)}
                type="button"
              >
                <span>{profileOptions.booleans[field].label}</span>
                {isSelected && <Check size={16} />}
              </button>
            );
          })}
        </DropdownShell>
      </div>
      <button type="submit" className="primary-button">Update profile</button>
    </form>
  );
}
