import { useEffect, useRef, useState } from "react";
import { useSpeechSynthesis } from "./useSpeechSynthesis.js";
import { fetchVoiceStatus, resolveMediaUrl, synthesizeVoice } from "../ipc/apiClient.js";
import { useChatStore } from "../state/chatStore.js";
import { attachOdinAnalyser, detachOdinAnalyser } from "../state/odinPresence.js";

// Shared Odin speech playback: backend TTS with a Web Audio analyser driving the
// reactor, falling back to the browser voice when the backend cannot speak.
export function useOdinVoice() {
  const [backendAvailable, setBackendAvailable] = useState(false);
  const audioRef = useRef(null);
  const contextRef = useRef(null);
  const setVoiceState = useChatStore((state) => state.setVoiceState);
  const speech = useSpeechSynthesis({
    onStart: () => setVoiceState("speaking"),
    onEnd: () => setVoiceState("idle"),
  });

  useEffect(() => {
    let cancelled = false;
    fetchVoiceStatus()
      .then((status) => {
        if (!cancelled) {
          setBackendAvailable(status.tts_configured);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setBackendAvailable(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      contextRef.current?.close();
      detachOdinAnalyser();
    };
  }, []);

  function connectAnalyser(audio) {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) {
        return;
      }
      if (!contextRef.current) {
        contextRef.current = new AudioContext();
      }
      const context = contextRef.current;
      void context.resume();
      const source = context.createMediaElementSource(audio);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(context.destination);
      attachOdinAnalyser(analyser);
    } catch {
      // Without an analyser the reactor falls back to a simulated envelope.
    }
  }

  function stop() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    detachOdinAnalyser();
    speech.stop();
    setVoiceState("idle");
  }

  async function speak(text) {
    const cleaned = text?.trim();
    if (!cleaned) {
      return;
    }
    stop();
    if (backendAvailable) {
      try {
        setVoiceState("speaking");
        const response = await synthesizeVoice({ text: cleaned });
        const audio = new Audio();
        audio.crossOrigin = "anonymous";
        audio.src = resolveMediaUrl(response.audio_url);
        audioRef.current = audio;
        connectAnalyser(audio);
        audio.onended = () => {
          audioRef.current = null;
          setVoiceState("idle");
          detachOdinAnalyser();
        };
        audio.onerror = () => {
          audioRef.current = null;
          setVoiceState("idle");
          detachOdinAnalyser();
          if (speech.available) {
            speech.speak(cleaned);
          }
        };
        await audio.play();
        return;
      } catch {
        setVoiceState("idle");
        detachOdinAnalyser();
      }
    }
    if (speech.available) {
      speech.speak(cleaned);
    }
  }

  return {
    available: backendAvailable || speech.available,
    speak,
    stop,
    warmUp: speech.warmUp,
  };
}
