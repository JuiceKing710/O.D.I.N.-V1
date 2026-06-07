import { useMemo, useRef, useState } from "react";

export function useSpeechRecognition({ continuous = false, onResult, onStart, onEnd } = {}) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const lastFinalTranscriptRef = useRef("");
  const recognitionRef = useRef(null);

  const Recognition = useMemo(
    () => window.SpeechRecognition || window.webkitSpeechRecognition,
    [],
  );
  const available = Boolean(Recognition);

  function stop() {
    recognitionRef.current?.stop();
    setListening(false);
    onEnd?.();
  }

  function start() {
    if (!available) {
      setError("Microphone dictation is unavailable in this browser. Try Chrome.");
      return;
    }
    setError("");
    setTranscript("");
    lastFinalTranscriptRef.current = "";
    const recognition = new Recognition();
    recognition.lang = "en-US";
    recognition.continuous = continuous;
    recognition.interimResults = true;

    recognition.onstart = () => {
      setListening(true);
      onStart?.();
    };
    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join("")
        .trim();
      setTranscript(text);
      const lastResult = event.results[event.results.length - 1];
      if (lastResult?.isFinal && text && text !== lastFinalTranscriptRef.current) {
        lastFinalTranscriptRef.current = text;
        onResult?.(text);
      }
    };
    recognition.onerror = (event) => {
      setError(event.error || "Microphone dictation failed.");
      setListening(false);
      onEnd?.();
    };
    recognition.onend = () => {
      setListening(false);
      onEnd?.();
    };

    recognitionRef.current = recognition;
    recognition.start();
  }

  function toggle() {
    if (listening) {
      stop();
    } else {
      start();
    }
  }

  return {
    available,
    error,
    listening,
    start,
    stop,
    toggle,
    transcript,
  };
}
