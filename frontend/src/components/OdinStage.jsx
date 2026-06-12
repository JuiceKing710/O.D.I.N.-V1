import React, { useEffect, useRef } from "react";
import { createVegvisir } from "./vegvisir.js";
import { useChatStore } from "../state/chatStore.js";
import { branchIntensity, buildStaveIntensities, useSystemStore } from "../state/systemStore.js";
import { sampleOdinEnergy } from "../state/odinPresence.js";

const FRAME_INTERVAL_MS = 33; // ~30fps cap for the whole stage

const SOFTWARE_NODES = [
  { id: "reasoning_engine", title: "Reasoning Engine", x: 0.5, y: 0.04 },
  { id: "memory_layer", title: "Memory Layer", x: 0.17, y: 0.13 },
  { id: "automation_hub", title: "Automation Hub", x: 0.83, y: 0.13 },
  { id: "voice_interface", title: "Voice Interface", x: 0.08, y: 0.4 },
  { id: "api_orchestrator", title: "API Orchestrator", x: 0.92, y: 0.34 },
  { id: "recovery_core", title: "Recovery Core", x: 0.13, y: 0.62 },
  { id: "security_mesh", title: "Security Mesh", x: 0.87, y: 0.58 },
];

const HARDWARE_NODES = [
  { id: "hw_cpu", title: "CPU" },
  { id: "hw_memory", title: "Memory" },
  { id: "hw_storage", title: "Local Storage" },
  { id: "hw_network", title: "Network" },
  { id: "hw_power", title: "Power Systems" },
];

function hardwareValue(metrics, id) {
  if (!metrics) {
    return { label: "—", ok: true };
  }
  if (id === "hw_cpu") {
    return { label: `${metrics.cpu_percent.toFixed(0)}% · ${metrics.cpu_count} cores`, ok: true };
  }
  if (id === "hw_memory") {
    return { label: `${metrics.memory.percent.toFixed(0)}% in use`, ok: metrics.memory.percent < 92 };
  }
  if (id === "hw_storage") {
    return { label: `${metrics.disk.percent.toFixed(0)}% full`, ok: metrics.disk.percent < 92 };
  }
  if (id === "hw_network") {
    const bits = (metrics.network.recv_bytes_per_sec + metrics.network.sent_bytes_per_sec) * 8;
    const label = bits >= 1e6 ? `${(bits / 1e6).toFixed(1)} Mbps` : `${(bits / 1e3).toFixed(0)} Kbps`;
    return { label, ok: true };
  }
  if (id === "hw_power") {
    if (!metrics.battery) {
      return { label: "AC power", ok: true };
    }
    const source = metrics.battery.plugged ? "charging" : "battery";
    return { label: `${metrics.battery.percent}% · ${source}`, ok: metrics.battery.percent > 15 };
  }
  return { label: "—", ok: true };
}

function softwareValue(nodes, id) {
  const node = nodes?.[id];
  if (!node) {
    return { label: "connecting…", ok: true };
  }
  return { label: node.label, ok: node.ok };
}

// Branches stay as a dim static skeleton until their subsystem is active, then
// get a brighter animated pass that fades with the activity decay.
function drawBranch(ctx, path, rgb, glow, dashOffset) {
  ctx.save();
  ctx.strokeStyle = `rgba(${rgb}, 0.1)`;
  ctx.lineWidth = 1;
  ctx.stroke(path);
  if (glow > 0.05) {
    ctx.strokeStyle = `rgba(${rgb}, ${0.15 + glow * 0.55})`;
    ctx.lineWidth = 1 + glow * 1.6;
    ctx.setLineDash([10, 14]);
    ctx.lineDashOffset = dashOffset;
    if (glow > 0.3) {
      ctx.shadowColor = `rgba(${rgb}, 0.9)`;
      ctx.shadowBlur = 8;
    }
    ctx.stroke(path);
  }
  ctx.restore();
}

export function OdinStage() {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const particlesRef = useRef([]);
  const voiceState = useChatStore((state) => state.voiceState);
  const voiceStateRef = useRef(voiceState);
  const metrics = useSystemStore((state) => state.metrics);
  const nodes = useSystemStore((state) => state.nodes);

  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !container || !ctx) {
      return undefined;
    }

    if (particlesRef.current.length === 0) {
      particlesRef.current = Array.from({ length: 36 }, () => ({
        x: Math.random(),
        y: Math.random(),
        radius: 0.6 + Math.random() * 1.6,
        speed: 0.004 + Math.random() * 0.012,
        drift: (Math.random() - 0.5) * 0.004,
        warm: Math.random() > 0.62,
        phase: Math.random() * Math.PI * 2,
      }));
    }

    const vegvisir = createVegvisir();
    let frame = 0;
    let smoothedEnergy = 0;
    let lastDraw = 0;
    let softwarePaths = [];
    let hardwarePaths = [];

    // Branch geometry only depends on the container size, so the Path2D
    // objects are rebuilt on resize instead of every frame.
    function buildPaths(width, height) {
      const centerX = width / 2;
      const centerY = height * 0.46;
      softwarePaths = SOFTWARE_NODES.map((node) => {
        const targetX = node.x * width;
        const targetY = node.y * height + 30;
        const path = new Path2D();
        path.moveTo(centerX, centerY - height * 0.1);
        path.bezierCurveTo(
          centerX + (targetX - centerX) * 0.2,
          centerY - height * 0.28,
          targetX + (centerX - targetX) * 0.25,
          targetY + 60,
          targetX,
          targetY,
        );
        return { id: node.id, path, rgb: node.x < 0.5 ? "96, 165, 250" : "167, 139, 250" };
      });
      const hardwareSpan = Math.min(width * 0.86, 980);
      hardwarePaths = HARDWARE_NODES.map((node, index) => {
        const targetX = centerX - hardwareSpan / 2 + (hardwareSpan / (HARDWARE_NODES.length - 1)) * index;
        const targetY = height * 0.94 - 46;
        const path = new Path2D();
        path.moveTo(centerX, centerY + height * 0.16);
        path.bezierCurveTo(
          centerX,
          centerY + height * 0.3,
          targetX,
          targetY - height * 0.14,
          targetX,
          targetY,
        );
        return path;
      });
    }

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = container.clientWidth * ratio;
      canvas.height = container.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      buildPaths(container.clientWidth, container.clientHeight);
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
      const centerX = width / 2;
      const centerY = height * 0.46;
      const voice = voiceStateRef.current;
      const mode = voice === "speaking" ? "speaking" : voice === "listening" ? "listening" : "idle";
      const speech = sampleOdinEnergy(now, mode === "speaking");
      const breathing = 0.1 + 0.06 * Math.sin(now / 1400);
      const target = mode === "speaking" ? 0.25 + speech * 0.75 : mode === "listening" ? 0.4 + 0.12 * Math.sin(now / 260) : breathing;
      smoothedEnergy += (target - smoothedEnergy) * 0.18;
      const energy = smoothedEnergy;

      ctx.clearRect(0, 0, width, height);

      // Concentric halo rings.
      ctx.save();
      for (let ring = 0; ring < 4; ring += 1) {
        const ringRadius = height * (0.18 + ring * 0.085) * (1 + energy * 0.04);
        ctx.beginPath();
        ctx.ellipse(centerX, centerY, ringRadius, ringRadius * 0.94, 0, 0, Math.PI * 2);
        const hue = mode === "listening" ? "140, 220, 255" : "120, 160, 255";
        ctx.strokeStyle = `rgba(${hue}, ${0.16 - ring * 0.03 + energy * 0.08})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();

      // Branches up to software nodes, roots down to hardware nodes — lit only
      // while their subsystem has recent activity.
      const nowMs = Date.now();
      const { nodeActivity } = useSystemStore.getState();
      const dashOffset = -(now / 24);
      for (const branch of softwarePaths) {
        let glow = branchIntensity(nodeActivity[branch.id], nowMs);
        if (branch.id === "voice_interface" && (voice === "speaking" || voice === "listening")) {
          glow = 1;
        }
        drawBranch(ctx, branch.path, branch.rgb, glow, dashOffset);
      }
      const heartbeat = branchIntensity(nodeActivity.system_heartbeat, nowMs);
      for (const path of hardwarePaths) {
        drawBranch(ctx, path, "251, 191, 36", heartbeat, -dashOffset);
      }

      // Ambient particles: cool above, warm sparks below.
      for (const particle of particlesRef.current) {
        particle.y -= particle.speed * (particle.warm ? -0.5 : 1) * (1 + energy);
        particle.x += particle.drift;
        if (particle.y < -0.05) particle.y = 1.05;
        if (particle.y > 1.05) particle.y = -0.05;
        if (particle.x < -0.05) particle.x = 1.05;
        if (particle.x > 1.05) particle.x = -0.05;
        const twinkle = 0.4 + 0.6 * Math.abs(Math.sin(now / 900 + particle.phase));
        ctx.beginPath();
        ctx.arc(particle.x * width, particle.y * height, particle.radius, 0, Math.PI * 2);
        ctx.fillStyle = particle.warm
          ? `rgba(251, 191, 36, ${0.32 * twinkle + energy * 0.2})`
          : `rgba(125, 211, 252, ${0.3 * twinkle + energy * 0.25})`;
        ctx.fill();
      }

      // Aura behind the reactor.
      const auraRadius = height * 0.3 * (1 + energy * 0.1);
      const aura = ctx.createRadialGradient(centerX, centerY, auraRadius * 0.2, centerX, centerY, auraRadius);
      const auraColor = mode === "listening" ? "56, 189, 248" : "99, 102, 241";
      aura.addColorStop(0, `rgba(${auraColor}, ${0.22 + energy * 0.3})`);
      aura.addColorStop(1, "rgba(8, 10, 26, 0)");
      ctx.fillStyle = aura;
      ctx.fillRect(centerX - auraRadius, centerY - auraRadius, auraRadius * 2, auraRadius * 2);

      // The Vegvisir compass at the heart of the tree.
      vegvisir.draw(ctx, {
        centerX,
        centerY,
        radius: height * 0.24,
        now,
        energy,
        mode,
        staves: buildStaveIntensities(nodeActivity, voice, nowMs),
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
    <div className="odin-stage" ref={containerRef} aria-label="O.D.I.N. system map">
      <canvas className="odin-canvas" ref={canvasRef} aria-hidden="true" />
      <span className="layer-label software-label">Software Layer</span>
      <span className="layer-label hardware-label">Hardware Layer</span>
      {SOFTWARE_NODES.map((node) => {
        const value = softwareValue(nodes, node.id);
        return (
          <article
            key={node.id}
            className={value.ok ? "node-card software" : "node-card software alert"}
            style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%` }}
          >
            <h4>{node.title}</h4>
            <p>
              <i className={value.ok ? "dot ok" : "dot bad"} aria-hidden="true" />
              {value.label}
            </p>
          </article>
        );
      })}
      <div className="hardware-row">
        {HARDWARE_NODES.map((node) => {
          const value = hardwareValue(metrics, node.id);
          return (
            <article key={node.id} className={value.ok ? "node-card hardware" : "node-card hardware alert"}>
              <h4>{node.title}</h4>
              <p>
                <i className={value.ok ? "dot ok" : "dot bad"} aria-hidden="true" />
                {value.label}
              </p>
            </article>
          );
        })}
      </div>
      <div className="odin-title">
        <h2>O.D.I.N.</h2>
        <p>Optical Detection &amp; Intelligence Network</p>
      </div>
    </div>
  );
}
