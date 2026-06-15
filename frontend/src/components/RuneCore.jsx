import React, { useEffect, useRef } from "react";
import { createVegvisir } from "./vegvisir.js";
import { buildStaveIntensities, useSystemStore } from "../state/systemStore.js";

// Per-mode resting glow. The compass is drawn as a still frame — no animation
// loop — so the renderer idles and leaves the CPU/GPU free for Odin's work.
const MODE_ENERGY = { speaking: 0.6, listening: 0.45, idle: 0.12 };

export function RuneCore({ state = "idle" }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const stateRef = useRef(state);
  const drawRef = useRef(() => {});

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !container || !ctx) {
      return undefined;
    }

    const vegvisir = createVegvisir();
    const now = performance.now(); // fixed snapshot keeps the frame still

    function draw() {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const voice = stateRef.current;
      const mode = voice === "speaking" ? "speaking" : voice === "listening" ? "listening" : "idle";
      const staves = buildStaveIntensities(
        useSystemStore.getState().nodeActivity,
        voice,
        Date.now(),
      );

      ctx.clearRect(0, 0, width, height);
      vegvisir.draw(ctx, {
        centerX: width / 2,
        centerY: height / 2,
        radius: Math.min(width, height) * 0.36,
        now,
        energy: MODE_ENERGY[mode],
        mode,
        staves,
      });
    }

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = container.clientWidth * ratio;
      canvas.height = container.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      vegvisir.invalidate();
      draw();
    }

    drawRef.current = draw;
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      drawRef.current = () => {};
    };
  }, []);

  // Repaint once when Odin's state changes — a single frame per transition, not
  // a loop — so the glow reflects listening/speaking without continuous motion.
  useEffect(() => {
    stateRef.current = state;
    drawRef.current();
  }, [state]);

  return (
    <div className="rune-core" ref={containerRef} aria-label={`O.D.I.N. is ${state}`}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <span className="core-state">{state}</span>
    </div>
  );
}
