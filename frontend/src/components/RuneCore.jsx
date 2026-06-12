import React, { useEffect, useRef } from "react";
import { drawRuneReactor } from "./runeReactor.js";
import { sampleOdinEnergy } from "../state/odinPresence.js";

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

    let frame = 0;
    let smoothedEnergy = 0;

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = container.clientWidth * ratio;
      canvas.height = container.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function render(now) {
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

      ctx.clearRect(0, 0, width, height);
      drawRuneReactor(ctx, {
        centerX: width / 2,
        centerY: height / 2,
        radius: Math.min(width, height) * 0.36,
        now,
        energy: smoothedEnergy,
        mode,
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
