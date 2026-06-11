// Frame-rate speech energy for the Odin stage, kept outside React to avoid re-renders.
const presence = {
  analyser: null,
  analyserData: null,
  simulatedSeed: 0,
};

export function attachOdinAnalyser(analyser) {
  presence.analyser = analyser;
  presence.analyserData = new Uint8Array(analyser.fftSize);
}

export function detachOdinAnalyser() {
  presence.analyser = null;
  presence.analyserData = null;
  presence.simulatedSeed = Math.random() * 1000;
}

// Returns 0..1 speech energy: real RMS when an analyser is attached,
// otherwise an organic envelope so browser-voice fallback still animates.
export function sampleOdinEnergy(nowMs, speaking) {
  if (!speaking) {
    return 0;
  }
  if (presence.analyser && presence.analyserData) {
    presence.analyser.getByteTimeDomainData(presence.analyserData);
    let sum = 0;
    for (let i = 0; i < presence.analyserData.length; i += 1) {
      const centered = (presence.analyserData[i] - 128) / 128;
      sum += centered * centered;
    }
    const rms = Math.sqrt(sum / presence.analyserData.length);
    return Math.min(1, rms * 3.2);
  }
  const t = nowMs / 1000 + presence.simulatedSeed;
  const wave =
    0.5 +
    0.28 * Math.sin(t * 7.1) +
    0.18 * Math.sin(t * 13.7 + 1.3) +
    0.12 * Math.sin(t * 23.3 + 4.1);
  return Math.min(1, Math.max(0.08, wave));
}
