import React from "react";

export function AICore({ state }) {
  return (
    <section className={`ai-core ${state}`} aria-label={`Jarvis is ${state}`}>
      <div className="core-ring outer" />
      <div className="core-ring inner" />
      <div className="core-orb" />
    </section>
  );
}

