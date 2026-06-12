import React, { useEffect, useRef } from "react";
import { createVegvisir } from "./vegvisir.js";
import { sampleOdinEnergy } from "../state/odinPresence.js";
import { buildStaveIntensities, useSystemStore } from "../state/systemStore.js";

const FRAME_INTERVAL_MS = 33; // ~30fps is plenty for the compass glow

export function RuneCore({ state = "idle" }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !container || !ctx) {
      return undefined;
    }

    const vegvisir = createVegvisir();
    let frame = 0;
    let smoothedEnergy = 0;
    let lastDraw = 0;

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = container.clientWidth * ratio;
      canvas.height = container.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      vegvisir.invalidate();
    }

    function render(now) {
      if (now - lastDraw < FRAME_INTERVAL_MS) {
        frame = window.requestAnimationFrame(render);
        return;
      }
      lastDraw = now;
      const width = container.clientWidth;
      const height = container.clientHeight;
      const voice = stateRef.current;
      const mode = voice === "speaking" ? "speaking" : voice === "listening" ? "listening" : "idle";
      const speech = sampleOdinEnergy(now, mode === "speaking");
      const breathing = 0.1 + 0.06 * Math.sin(now / 1400);
      const target =
        mode === "speaking"
          ? 0.25 + speech * 0.75
          : mode === "listening"
            ? 0.4 + 0.12 * Math.sin(now / 260)
            : breathing;
      smoothedEnergy += (target - smoothedEnergy) * 0.18;

      const { nodeActivity } = useSystemStore.getState();
      const staves = buildStaveIntensities(nodeActivity, voice, Date.now());

      ctx.clearRect(0, 0, width, height);
      vegvisir.draw(ctx, {
        centerX: width / 2,
        centerY: height / 2,
        radius: Math.min(width, height) * 0.36,
        now,
        energy: smoothedEnergy,
        mode,
        staves,
      });
      frame = window.requestAnimationFrame(render);
    }

    function handleVisibility() {
      window.cancelAnimationFrame(frame);
      if (!document.hidden) {
        frame = window.requestAnimationFrame(render);
      }
    }

    resize();
    frame = window.requestAnimationFrame(render);
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  return (
    <div className="rune-core" ref={containerRef} aria-label={`O.D.I.N. is ${state}`}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <span className="core-state">{state}</span>
    </div>
  );
}
