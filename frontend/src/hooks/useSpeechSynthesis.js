import { useEffect, useMemo, useState } from "react";

export function useSpeechSynthesis({ onStart, onEnd } = {}) {
  const [available, setAvailable] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voices, setVoices] = useState([]);

  useEffect(() => {
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
      setAvailable(false);
      return undefined;
    }

    function loadVoices() {
      setVoices(window.speechSynthesis.getVoices());
      setAvailable(true);
    }

    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
  }, []);

  const preferredVoice = useMemo(
    () =>
      voices.find((voice) => voice.lang?.startsWith("en") && /male|daniel|alex/i.test(voice.name)) ||
      voices.find((voice) => voice.lang?.startsWith("en")) ||
      voices[0],
    [voices],
  );

  function stop() {
    if (!available) {
      return;
    }
    window.speechSynthesis.cancel();
    setSpeaking(false);
    onEnd?.();
  }

  function warmUp() {
    if (!available) {
      return;
    }
    window.speechSynthesis.resume();
    const utterance = new SpeechSynthesisUtterance(" ");
    utterance.volume = 0;
    window.speechSynthesis.speak(utterance);
  }

  function speak(text) {
    const cleaned = text?.trim();
    if (!available || !cleaned) {
      return;
    }
    window.speechSynthesis.cancel();
    window.speechSynthesis.resume();
    const utterance = new SpeechSynthesisUtterance(cleaned);
    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }
    utterance.rate = 0.94;
    utterance.pitch = 0.88;
    utterance.volume = 1;
    utterance.onstart = () => {
      setSpeaking(true);
      onStart?.();
    };
    utterance.onend = () => {
      setSpeaking(false);
      onEnd?.();
    };
    utterance.onerror = () => {
      setSpeaking(false);
      onEnd?.();
    };
    window.speechSynthesis.speak(utterance);
  }

  return {
    available,
    speaking,
    speak,
    stop,
    warmUp,
    voiceName: preferredVoice?.name || "",
  };
}
