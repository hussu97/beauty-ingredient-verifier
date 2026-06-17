import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { ClinicalProfile, ScanJob, ScanProgress } from "../api/types";
import HarmMeter from "../components/HarmMeter";
import ProfilePanel from "../components/ProfilePanel";
import ResultPanel from "../components/ResultPanel";
import UploadPanel from "../components/UploadPanel";
import { loadProfile } from "../lib/profile";

export default function ScannerPage() {
  const [scan, setScan] = useState<ScanJob | null>(null);
  const [profile, setProfile] = useState<ClinicalProfile>(() => loadProfile());
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const scanMutation = useMutation({
    mutationFn: (file: File) => api.scanWithProgress(file, setScanProgress),
    onMutate: () => {
      setScan(null);
      setScanProgress({ phase: "uploading", percent: 0, label: "Uploading image" });
    },
    onSuccess: (nextScan) => {
      setScan(nextScan);
      setScanProgress({ phase: "complete", percent: 100, label: "Scan complete" });
    },
    onError: () => {
      setScanProgress(null);
    },
  });

  return (
    <div className="scanner-page">
      <section className="scanner-hero">
        <div>
          <span className="eyebrow">Local beauty scan</span>
          <h1>Check the product in front of you.</h1>
        </div>
        <p>
          Upload a front-label photo and review the top match, ingredient list, and profile-aware warnings in one flow.
        </p>
      </section>

      <ProfilePanel profile={profile} onChange={setProfile} />

      <div className="scan-workflow">
        <div className="scan-guidance-column">
          <UploadPanel
            isUploading={scanMutation.isPending}
            onUpload={(file) => scanMutation.mutate(file)}
            progress={scanProgress}
          />
          <HarmMeter />
        </div>
        <div className="scan-result-column">
          {scanMutation.error && (
            <div className="error-banner">{scanMutation.error.message}</div>
          )}
          <ResultPanel scan={scan} profile={profile} />
        </div>
      </div>
    </div>
  );
}
