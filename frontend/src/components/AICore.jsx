import React from "react";

const PARTICLES = Array.from({ length: 8 }, (_, index) => index);
const SPOKES = Array.from({ length: 14 }, (_, index) => index);

export function AICore({ mode = "compact", state }) {
  return (
    <section className={`ai-core ${state} ${mode}`} aria-label={`Jarvis is ${state}`}>
      <div className="core-ring outer" />
      <div className="core-ring inner" />
      <div className="core-spokes" aria-hidden="true">
        {SPOKES.map((spoke) => (
          <span
            key={spoke}
            style={{
              "--spoke-angle": `${spoke * (360 / SPOKES.length)}deg`,
              "--spoke-index": spoke,
            }}
          />
        ))}
      </div>
      <div className="core-particles" aria-hidden="true">
        {PARTICLES.map((particle) => (
          <span key={particle} style={{ "--particle-angle": `${particle * 45}deg` }} />
        ))}
      </div>
      <div className="core-orb" />
      <span className="core-monogram">J</span>
      <span className="core-state">{state}</span>
    </section>
  );
}
