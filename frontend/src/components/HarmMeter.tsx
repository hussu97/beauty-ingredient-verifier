import { useState } from "react";
import { harmLevelFor, harmLevels } from "../lib/harmScale";
import { severityClass } from "../lib/severity";

export default function HarmMeter() {
  const [selectedSeverity, setSelectedSeverity] = useState(harmLevels[0].severity);
  const selectedLevel = harmLevelFor(selectedSeverity);

  return (
    <section className="harm-meter-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Step 2 · harm meter</span>
          <h2>How warning levels read</h2>
          <p>The meter explains the severity language used in scan results and product pages.</p>
        </div>
      </div>
      <div className="harm-meter">
        <div className="harm-scale-track" aria-hidden="true" />
        <div className="harm-scale-points">
          {harmLevels.map((level, index) => (
            <button
              aria-pressed={selectedSeverity === level.severity}
              className={selectedSeverity === level.severity ? "harm-scale-point active" : "harm-scale-point"}
              key={level.severity}
              onClick={() => setSelectedSeverity(level.severity)}
              type="button"
            >
              <span className={`harm-dot ${severityClass(level.severity)}`} />
              <strong>{level.label}</strong>
              <small>{index + 1}</small>
            </button>
          ))}
        </div>
        <div className={`harm-scale-note ${severityClass(selectedLevel.severity)}`}>
          <strong>{selectedLevel.label}</strong>
          <span>{selectedLevel.meaning}</span>
        </div>
      </div>
    </section>
  );
}
