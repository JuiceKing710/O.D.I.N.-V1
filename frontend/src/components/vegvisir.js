// Procedural Vegvisir compass for the O.D.I.N. core reactor: eight staves with
// distinct terminal glyphs inside a static Elder Futhark ring. The static
// geometry is pre-rendered to offscreen canvases (dim base + one bright sprite
// per stave) so the per-frame hot path is a handful of drawImage calls plus the
// voice-reactive center glow — no fillText or shadowBlur per frame.

export const ELDER_FUTHARK = [..."ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ"];

const STAVE_COUNT = 8;
const STAVE_ROOT = 0.2;
const BASE_EXTENT = 1.18; // half-size of the cached base layer, in radii
const SPRITE_HALF_WIDTH = 0.2; // stave sprite half-width, in radii
const SPRITE_REACH = 1.0; // stave sprite outer edge, in radii

// Terminal glyph recipes in stave-local units: s = perpendicular offset,
// t = distance from center along the stave (positive outward). `end` is where
// the main stave line stops before the glyph takes over.
const STAVE_GLYPHS = [
  {
    // N — trident
    end: 0.9,
    lines: [
      [0, 0.74, -0.07, 0.9],
      [0, 0.74, 0.07, 0.9],
    ],
  },
  {
    // NE — T-bar with downturned tines
    end: 0.86,
    lines: [
      [-0.09, 0.86, 0.09, 0.86],
      [-0.09, 0.86, -0.09, 0.78],
      [0.09, 0.86, 0.09, 0.78],
    ],
  },
  {
    // E — circle bisected by the stave
    end: 0.9,
    circles: [[0, 0.83, 0.055]],
  },
  {
    // SE — double chevron opening outward
    end: 0.9,
    lines: [
      [-0.07, 0.78, 0, 0.85],
      [0, 0.85, 0.07, 0.78],
      [-0.07, 0.86, 0, 0.93],
      [0, 0.93, 0.07, 0.86],
    ],
  },
  {
    // S — Tiwaz arrow with crossbar
    end: 0.9,
    lines: [
      [-0.07, 0.82, 0, 0.9],
      [0, 0.9, 0.07, 0.82],
      [-0.05, 0.72, 0.05, 0.72],
    ],
  },
  {
    // SW — opposing half circles straddling the stave
    end: 0.9,
    arcs: [
      [0, 0.82, 0.055, Math.PI / 2, (Math.PI * 3) / 2],
      [0, 0.9, 0.055, -Math.PI / 2, Math.PI / 2],
    ],
  },
  {
    // W — comb teeth
    end: 0.9,
    lines: [
      [-0.07, 0.78, 0.07, 0.78],
      [-0.07, 0.84, 0.07, 0.84],
      [-0.07, 0.9, 0.07, 0.9],
    ],
  },
  {
    // NW — diamond at the tip
    end: 0.82,
    lines: [
      [0, 0.82, 0.055, 0.89],
      [0.055, 0.89, 0, 0.96],
      [0, 0.96, -0.055, 0.89],
      [-0.055, 0.89, 0, 0.82],
    ],
  },
];

// Strokes one stave (pointing "north": +t maps to -y) in stave-local space.
function traceStave(ctx, radius, index) {
  const glyph = STAVE_GLYPHS[index];
  ctx.beginPath();
  ctx.moveTo(0, -STAVE_ROOT * radius);
  ctx.lineTo(0, -glyph.end * radius);
  for (const t of [0.45, 0.62]) {
    ctx.moveTo(-0.06 * radius, -t * radius);
    ctx.lineTo(0.06 * radius, -t * radius);
  }
  for (const [s1, t1, s2, t2] of glyph.lines || []) {
    ctx.moveTo(s1 * radius, -t1 * radius);
    ctx.lineTo(s2 * radius, -t2 * radius);
  }
  for (const [s, t, r] of glyph.circles || []) {
    ctx.moveTo((s + r) * radius, -t * radius);
    ctx.arc(s * radius, -t * radius, r * radius, 0, Math.PI * 2);
  }
  for (const [s, t, r, from, to] of glyph.arcs || []) {
    const cx = s * radius;
    const cy = -t * radius;
    ctx.moveTo(cx + Math.cos(from) * r * radius, cy + Math.sin(from) * r * radius);
    ctx.arc(cx, cy, r * radius, from, to);
  }
  ctx.stroke();
}

function makeLayer(widthCss, heightCss, dpr) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(widthCss * dpr);
  canvas.height = Math.ceil(heightCss * dpr);
  const ctx = canvas.getContext("2d");
  return { canvas, ctx };
}

function glowHeart(mode) {
  if (mode === "speaking") {
    return "255, 244, 214";
  }
  if (mode === "listening") {
    return "186, 240, 255";
  }
  return "224, 242, 254";
}

export function createVegvisir() {
  let base = null;
  let sprites = null;
  let cachedRadius = 0;
  let cachedDpr = 0;

  function build(radius, dpr) {
    const extent = BASE_EXTENT * radius;
    const baseLayer = makeLayer(extent * 2, extent * 2, dpr);
    const ctx = baseLayer.ctx;
    if (!ctx) {
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, extent * dpr, extent * dpr);
    ctx.lineWidth = Math.max(1, radius * 0.012);
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(148, 180, 240, 0.3)";

    // Dim staves.
    for (let k = 0; k < STAVE_COUNT; k += 1) {
      ctx.save();
      ctx.rotate((Math.PI / 4) * k);
      traceStave(ctx, radius, k);
      ctx.restore();
    }

    // Ring circles bounding the runes.
    for (const factor of [0.96, 1.14]) {
      ctx.beginPath();
      ctx.arc(0, 0, radius * factor, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(148, 180, 240, 0.22)";
      ctx.stroke();
    }

    // Static Elder Futhark ring, glow baked in once here (off the hot path).
    ctx.save();
    ctx.font = `${radius * 0.085}px "Hoefler Text", "Times New Roman", serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(160, 195, 250, 0.4)";
    ctx.shadowColor = "rgba(125, 211, 252, 0.5)";
    ctx.shadowBlur = 4;
    for (let i = 0; i < ELDER_FUTHARK.length; i += 1) {
      const angle = (Math.PI * 2 * i) / ELDER_FUTHARK.length - Math.PI / 2;
      ctx.save();
      ctx.rotate(angle + Math.PI / 2);
      ctx.fillText(ELDER_FUTHARK[i], 0, -radius * 1.05);
      ctx.restore();
    }
    ctx.restore();

    // Bright sprites, one per stave, glow baked in.
    const spriteLayers = [];
    const spriteWidth = SPRITE_HALF_WIDTH * 2 * radius;
    const spriteHeight = (SPRITE_REACH - STAVE_ROOT + 0.06) * radius;
    for (let k = 0; k < STAVE_COUNT; k += 1) {
      const layer = makeLayer(spriteWidth, spriteHeight, dpr);
      const sctx = layer.ctx;
      if (!sctx) {
        return;
      }
      sctx.setTransform(dpr, 0, 0, dpr, (spriteWidth / 2) * dpr, SPRITE_REACH * radius * dpr);
      sctx.lineWidth = Math.max(1.2, radius * 0.016);
      sctx.lineCap = "round";
      sctx.strokeStyle = "rgba(196, 228, 255, 0.95)";
      sctx.shadowColor = "rgba(125, 211, 252, 0.9)";
      sctx.shadowBlur = radius * 0.05;
      traceStave(sctx, radius, k);
      spriteLayers.push({ ...layer, widthCss: spriteWidth, heightCss: spriteHeight });
    }

    base = { ...baseLayer, extent };
    sprites = spriteLayers;
    cachedRadius = radius;
    cachedDpr = dpr;
  }

  return {
    invalidate() {
      base = null;
      sprites = null;
    },
    draw(ctx, { centerX, centerY, radius, now, energy, mode, staves }) {
      const roundedRadius = Math.max(8, Math.round(radius));
      const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
      if (!base || cachedRadius !== roundedRadius || cachedDpr !== dpr) {
        build(roundedRadius, dpr);
      }
      if (!base || !sprites) {
        return;
      }

      // Static compass, pre-rendered dim.
      ctx.drawImage(
        base.canvas,
        centerX - base.extent,
        centerY - base.extent,
        base.extent * 2,
        base.extent * 2,
      );

      // Active staves brighten over the dim base.
      for (let k = 0; k < STAVE_COUNT; k += 1) {
        const intensity = staves?.[k] || 0;
        if (intensity <= 0.03) {
          continue;
        }
        const sprite = sprites[k];
        ctx.save();
        ctx.translate(centerX, centerY);
        ctx.rotate((Math.PI / 4) * k);
        ctx.globalAlpha = Math.min(1, intensity);
        ctx.drawImage(
          sprite.canvas,
          -sprite.widthCss / 2,
          -SPRITE_REACH * roundedRadius,
          sprite.widthCss,
          sprite.heightCss,
        );
        ctx.restore();
      }

      ctx.save();
      ctx.globalCompositeOperation = "lighter";

      // Voice-reactive heart of the compass.
      const coreRadius = roundedRadius * (0.16 + energy * 0.14 + 0.01 * Math.sin(now / 600));
      const glow = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, coreRadius * 2.2);
      glow.addColorStop(0, `rgba(${glowHeart(mode)}, ${0.85 + energy * 0.15})`);
      glow.addColorStop(0.3, `rgba(125, 211, 252, ${0.4 + energy * 0.4})`);
      glow.addColorStop(0.65, `rgba(99, 102, 241, ${0.2 + energy * 0.3})`);
      glow.addColorStop(1, "rgba(99, 102, 241, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(centerX, centerY, coreRadius * 2.2, 0, Math.PI * 2);
      ctx.fill();

      // One slow highlight arc sweeping the rune ring.
      const sweep = now / 1400;
      ctx.beginPath();
      ctx.arc(centerX, centerY, roundedRadius * 0.96, sweep, sweep + 1.2);
      ctx.strokeStyle = `rgba(165, 199, 255, ${0.18 + energy * 0.3})`;
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.restore();
    },
  };
}
