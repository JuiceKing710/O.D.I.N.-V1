// Shared canvas renderer for the O.D.I.N. rune reactor: pseudo-3D rings of
// Elder Futhark runes orbiting an energy core, reactive to speech energy.

const ELDER_FUTHARK = [..."ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ"];

const RINGS = [
  { radiusFactor: 0.52, tilt: 0.32, plane: -0.42, speed: 0.00022, runes: 12, size: 0.115 },
  { radiusFactor: 0.76, tilt: 0.4, plane: 0.5, speed: -0.00016, runes: 16, size: 0.1 },
  { radiusFactor: 1.0, tilt: 0.26, plane: 0.08, speed: 0.0001, runes: 20, size: 0.09 },
];

function ringColor(mode, depthMix, alpha) {
  if (mode === "listening") {
    return `rgba(${56 + 60 * depthMix}, ${189 + 30 * depthMix}, 248, ${alpha})`;
  }
  if (mode === "speaking") {
    return `rgba(${167 + 80 * depthMix}, ${170 + 60 * depthMix}, 250, ${alpha})`;
  }
  return `rgba(${110 + 40 * depthMix}, ${150 + 40 * depthMix}, 250, ${alpha})`;
}

export function drawRuneReactor(ctx, { centerX, centerY, radius, now, energy, mode }) {
  const spin = 1 + energy * 2.4;

  // Core orb.
  const coreRadius = radius * (0.3 + energy * 0.08 + 0.015 * Math.sin(now / 600));
  const core = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, coreRadius);
  const heart = mode === "speaking" ? "255, 244, 214" : "224, 242, 254";
  core.addColorStop(0, `rgba(${heart}, ${0.95})`);
  core.addColorStop(0.35, `rgba(125, 211, 252, ${0.65 + energy * 0.3})`);
  core.addColorStop(0.75, `rgba(99, 102, 241, ${0.35 + energy * 0.3})`);
  core.addColorStop(1, "rgba(99, 102, 241, 0)");
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(centerX, centerY, coreRadius, 0, Math.PI * 2);
  ctx.fill();

  // Plasma arcs hugging the core.
  for (let arc = 0; arc < 3; arc += 1) {
    const arcStart = now / (700 - arc * 140) + arc * 2.1;
    ctx.beginPath();
    ctx.arc(centerX, centerY, coreRadius * (1.12 + arc * 0.16), arcStart, arcStart + 1.6 + energy);
    ctx.strokeStyle = `rgba(165, 199, 255, ${0.35 + energy * 0.4 - arc * 0.08})`;
    ctx.lineWidth = 1.6;
    ctx.shadowColor = "rgba(125, 211, 252, 0.8)";
    ctx.shadowBlur = 10;
    ctx.stroke();
  }
  ctx.restore();

  // Rune rings, back halves first so front runes overlap the core.
  const glyphs = [];
  for (const ring of RINGS) {
    const ringRadius = radius * ring.radiusFactor;
    const fontSize = radius * ring.size;
    for (let i = 0; i < ring.runes; i += 1) {
      const angle = now * ring.speed * spin + (Math.PI * 2 * i) / ring.runes;
      const flatX = Math.cos(angle) * ringRadius;
      const flatY = Math.sin(angle) * ringRadius * ring.tilt;
      const x = centerX + flatX * Math.cos(ring.plane) - flatY * Math.sin(ring.plane);
      const y = centerY + flatX * Math.sin(ring.plane) + flatY * Math.cos(ring.plane);
      const depth = Math.sin(angle);
      const depthMix = (depth + 1) / 2;
      glyphs.push({
        rune: ELDER_FUTHARK[(i * 7 + Math.floor(ring.radiusFactor * 10)) % ELDER_FUTHARK.length],
        x,
        y,
        depth,
        size: fontSize * (0.7 + 0.45 * depthMix),
        alpha: 0.3 + 0.6 * depthMix + energy * 0.1,
        depthMix,
      });
    }
  }
  glyphs.sort((a, b) => a.depth - b.depth);

  ctx.save();
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (const glyph of glyphs) {
    ctx.font = `${glyph.size}px "Hoefler Text", "Times New Roman", serif`;
    ctx.shadowColor = ringColor(mode, glyph.depthMix, 0.9);
    ctx.shadowBlur = 6 + energy * 14 * glyph.depthMix;
    ctx.fillStyle = ringColor(mode, glyph.depthMix, Math.min(1, glyph.alpha));
    ctx.fillText(glyph.rune, glyph.x, glyph.y);
  }
  ctx.restore();
}
