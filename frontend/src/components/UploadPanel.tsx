import { motion } from "framer-motion";
import { ImageUp, Loader2, ScanLine } from "lucide-react";
import { useRef, useState } from "react";
import type { ScanProgress } from "../api/types";

type Props = {
  isUploading: boolean;
  onUpload: (file: File) => void;
  progress: ScanProgress | null;
};

export default function UploadPanel({ isUploading, onUpload, progress }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  function onFile(file: File | undefined) {
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    onUpload(file);
  }

  const showProgress = isUploading || progress?.phase === "complete";
  const progressLabel = progress?.label ?? "Preparing scan";
  const progressPercent = progress?.percent ?? 0;

  return (
    <motion.section
      className="upload-panel"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
    >
      <div className="scanner-copy">
        <span className="eyebrow">Step 2 · scan</span>
        <h2>Upload the front of the product</h2>
        <p>Barcode and image matching run locally first. If confidence is low, the app still shows what it can read.</p>
      </div>
      <button
        className="upload-target"
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={isUploading}
      >
        {preview ? (
          <img src={preview} alt="Uploaded product preview" />
        ) : (
          <span className="upload-empty">
            <ImageUp size={34} />
            Choose product image
          </span>
        )}
        <span className="scan-action">
          {isUploading ? <Loader2 className="spin" size={18} /> : <ScanLine size={18} />}
          {isUploading ? "Scanning" : "Start scan"}
        </span>
      </button>
      {showProgress && (
        <div className="scan-progress" aria-live="polite">
          <div className="scan-progress-copy">
            <strong>{progressLabel}</strong>
            {progress?.percent !== null && progress?.percent !== undefined && <span>{progress.percent}%</span>}
          </div>
          <div className={progress?.percent === null ? "scan-progress-track indeterminate" : "scan-progress-track"}>
            <span style={progress?.percent === null ? undefined : { width: `${progressPercent}%` }} />
          </div>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => onFile(event.target.files?.[0])}
      />
    </motion.section>
  );
}
