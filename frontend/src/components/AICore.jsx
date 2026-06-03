import React from "react";

const PARTICLES = Array.from({ length: 8 }, (_, index) => index);

export function AICore({ state }) {
  return (
    <section className={`ai-core ${state}`} aria-label={`Jarvis is ${state}`}>
      <div className="core-ring outer" />
      <div className="core-ring inner" />
      <div className="core-particles" aria-hidden="true">
        {PARTICLES.map((particle) => (
          <span key={particle} style={{ "--particle-index": particle }} />
        ))}
      </div>
      <div className="core-orb" />
      <span className="core-state">{state}</span>
    </section>
  );
}
