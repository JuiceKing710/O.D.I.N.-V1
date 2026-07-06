import React, { useEffect, useRef, useState } from "react";
import { useOdinCamera } from "../hooks/useOdinCamera.js";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis.js";
import {
  analyzeScreen,
  createReflection,
  fetchConversationMessages,
  fetchConversations,
  fetchModels,
  fetchReflections,
  fetchVoiceStatus,
  resolveMediaUrl,
  sendChatMessage,
  synthesizeVoice,
  transcribeVoiceAudio,
} from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";
import { attachOdinAnalyser, detachOdinAnalyser } from "../state/odinPresence.js";

const MESSAGE_RENDER_LIMIT = 120;
const SCROLL_BOTTOM_THRESHOLD = 96;

export function ChatView({ onOpenCoreFocus }) {
  const [input, setInput] = useState("");
  const [conversationError, setConversationError] = useState("");
  const [conversations, setConversations] = useState([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [isPinnedToLatest, setIsPinnedToLatest] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [handsFree, setHandsFree] = useState(false);
  const [speakingMessageId, setSpeakingMessageId] = useState("");
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [screenAnalyzing, setScreenAnalyzing] = useState(false);
  const [providerStatus, setProviderStatus] = useState({
    error: "",
    loading: true,
    provider: null,
  });
  const [reflections, setReflections] = useState([]);
  const [reflectionLoading, setReflectionLoading] = useState(false);
  const [backendRecording, setBackendRecording] = useState(false);
  const [backendSpeaking, setBackendSpeaking] = useState(false);
  const [backendVoiceAvailable, setBackendVoiceAvailable] = useState(false);
  const [microphoneDevices, setMicrophoneDevices] = useState([]);
  const [selectedMicrophone, setSelectedMicrophone] = useState("");
  const audioRef = useRef(null);
  const playbackContextRef = useRef(null);
  const automaticListeningRef = useRef(false);
  const automaticRecordingRef = useRef(false);
  const handsFreeRef = useRef(false);
  const backendRecordingRef = useRef(false);
  const automaticStopTimerRef = useRef(null);
  const inputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const messageEndRef = useRef(null);
  const messageListRef = useRef(null);
  const { conversationId, currentUser, settings, setConversationId, startNewConversation } =
    useAppState();
  const voiceMode = settings?.voice_mode || "push_to_talk";
  const voiceDisabled = voiceMode === "disabled";
  const messages = useChatStore((state) => state.messages);
  const addMessage = useChatStore((state) => state.addMessage);
  const clearMessages = useChatStore((state) => state.clearMessages);
  const setMessages = useChatStore((state) => state.setMessages);
  const voiceState = useChatStore((state) => state.voiceState);
  const setVoiceState = useChatStore((state) => state.setVoiceState);
  const streaming = useChatStore((state) => state.streaming);
  const speech = useSpeechSynthesis({
    onStart: () => setVoiceState("speaking"),
    onEnd: () => {
      setSpeakingMessageId("");
      setVoiceState("idle");
    },
  });
  const camera = useOdinCamera({ onError: setVoiceNotice });
  const provider = providerStatus.provider;
  const providerAvailable = Boolean(provider?.available);
  const providerState = providerStatus.loading ? "pending" : providerAvailable ? "ok" : "error";
  const providerLabel = provider?.provider || "provider";
  const modelLabel = provider?.selected_model || "no model selected";
  const providerMessage =
    provider?.error || providerStatus.error || "Language model provider is unavailable.";
  const visibleMessages = messages.slice(-MESSAGE_RENDER_LIMIT);
  const hiddenMessageCount = Math.max(messages.length - visibleMessages.length, 0);

  async function refreshConversations() {
    setConversationsLoading(true);
    setConversationError("");
    try {
      const response = await fetchConversations(currentUser.username);
      setConversations(response);
    } catch (error) {
      setConversationError(error.message);
    } finally {
      setConversationsLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    fetchModels()
      .then((response) => {
        if (!cancelled) {
          setProviderStatus({
            error: "",
            loading: false,
            provider: response.provider,
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setProviderStatus({
            error: error.message,
            loading: false,
            provider: null,
          });
        }
      });
    fetchVoiceStatus()
      .then((status) => {
        if (!cancelled) {
          setBackendVoiceAvailable(status.tts_configured);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setBackendVoiceAvailable(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [currentUser.username]);

  useEffect(() => {
    if (voiceDisabled) {
      setVoiceEnabled(false);
      stopSpeech();
      automaticListeningRef.current = false;
      clearTimeout(automaticStopTimerRef.current);
      mediaRecorderRef.current?.stop();
    } else {
      setVoiceEnabled(true);
    }
  }, [voiceDisabled]);

  useEffect(() => {
    automaticListeningRef.current = voiceMode === "always_listening";
    if (automaticListeningRef.current && !backendRecording) {
      void toggleMicrophone(true);
    } else if (!automaticListeningRef.current && automaticRecordingRef.current) {
      clearTimeout(automaticStopTimerRef.current);
      mediaRecorderRef.current?.stop();
    }
  }, [voiceMode]);

  useEffect(() => {
    handsFreeRef.current = handsFree;
  }, [handsFree]);

  useEffect(() => {
    backendRecordingRef.current = backendRecording;
  }, [backendRecording]);

  // Hands-free conversation loop: whenever Odin is idle (done thinking and
  // speaking) and we're not already recording, reopen the mic after a short
  // gap so the user can just keep talking. Waiting for the "idle" state means
  // the mic never reopens while Odin is still speaking, so it won't hear itself.
  useEffect(() => {
    if (!handsFree || voiceDisabled) {
      return undefined;
    }
    if (voiceState !== "idle" || backendRecording) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      if (handsFreeRef.current && !backendRecordingRef.current) {
        void toggleMicrophone(true);
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [handsFree, voiceState, backendRecording, voiceDisabled]);

  useEffect(() => {
    return () => {
      automaticListeningRef.current = false;
      handsFreeRef.current = false;
      clearTimeout(automaticStopTimerRef.current);
      mediaRecorderRef.current?.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      playbackContextRef.current?.close();
      detachOdinAnalyser();
    };
  }, []);

  useEffect(() => {
    if (isPinnedToLatest) {
      messageEndRef.current?.scrollIntoView({ block: "end" });
      setShowJumpLatest(false);
    }
  }, [isPinnedToLatest, messages.length]);

  function isNearMessageListBottom(element) {
    return (
      element.scrollHeight - element.scrollTop - element.clientHeight <= SCROLL_BOTTOM_THRESHOLD
    );
  }

  function handleMessageScroll() {
    const list = messageListRef.current;
    if (!list) {
      return;
    }
    const nearBottom = isNearMessageListBottom(list);
    setIsPinnedToLatest(nearBottom);
    setShowJumpLatest(!nearBottom && messages.length > 0);
  }

  function jumpToLatest() {
    setIsPinnedToLatest(true);
    setShowJumpLatest(false);
    requestAnimationFrame(() => {
      messageEndRef.current?.scrollIntoView({ block: "end" });
      inputRef.current?.focus();
    });
  }

  async function speakMessage(message) {
    if (!message?.content) {
      return;
    }
    stopSpeech();
    setSpeakingMessageId(message.id || "");
    setVoiceNotice("");
    if (backendVoiceAvailable) {
      try {
        setVoiceState("speaking");
        const response = await synthesizeVoice({ text: message.content });
        const audio = new Audio();
        audio.crossOrigin = "anonymous";
        audio.src = resolveMediaUrl(response.audio_url);
        audioRef.current = audio;
        setBackendSpeaking(true);
        connectSpeechAnalyser(audio);
        audio.onended = () => {
          audioRef.current = null;
          setBackendSpeaking(false);
          setSpeakingMessageId("");
          setVoiceState("idle");
          detachOdinAnalyser();
        };
        audio.onerror = () => {
          audioRef.current = null;
          setBackendSpeaking(false);
          setVoiceState("idle");
          detachOdinAnalyser();
          if (speech.available) {
            setVoiceNotice("Backend audio playback failed. Using browser voice instead.");
            speech.speak(message.content);
          } else {
            setSpeakingMessageId("");
            setVoiceNotice("O.D.I.N. created the voice response, but audio playback failed.");
          }
        };
        await audio.play();
        return;
      } catch (error) {
        audioRef.current = null;
        setBackendSpeaking(false);
        setVoiceState("idle");
        if (!speech.available) {
          setSpeakingMessageId("");
          setVoiceNotice(`Voice playback failed: ${error.message}`);
          return;
        }
      }
    }
    if (speech.available) {
      speech.speak(message.content);
      return;
    }
    setSpeakingMessageId("");
    setVoiceNotice("Speech output is unavailable. Check Backend Voice in Settings.");
  }

  function connectSpeechAnalyser(audio) {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) {
        return;
      }
      if (!playbackContextRef.current) {
        playbackContextRef.current = new AudioContext();
      }
      const context = playbackContextRef.current;
      void context.resume();
      const source = context.createMediaElementSource(audio);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(context.destination);
      attachOdinAnalyser(analyser);
    } catch {
      // Without an analyser the Odin stage falls back to a simulated envelope.
    }
  }

  function stopSpeech() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    detachOdinAnalyser();
    setBackendSpeaking(false);
    speech.stop();
    setSpeakingMessageId("");
    setVoiceState("idle");
  }

  function handleNewChat() {
    stopSpeech();
    startNewConversation();
    clearMessages();
    setInput("");
    setIsPinnedToLatest(true);
    setShowJumpLatest(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function openConversation(nextConversationId) {
    stopSpeech();
    setConversationError("");
    try {
      const response = await fetchConversationMessages(nextConversationId, currentUser.username);
      setConversationId(nextConversationId);
      setReflections(await fetchReflections(nextConversationId, currentUser.username));
      setMessages(
        response.map((message) => ({
          id: `message-${message.msg_id}`,
          role: message.role,
          content: message.content,
          conversationId: message.convo_id,
        })),
      );
      setInput("");
      setIsPinnedToLatest(true);
      setShowJumpLatest(false);
      requestAnimationFrame(() => {
        messageEndRef.current?.scrollIntoView({ block: "end" });
        inputRef.current?.focus();
      });
    } catch (error) {
      setConversationError(error.message);
    }
  }

  async function reflectOnConversation() {
    if (!conversationId || reflectionLoading) {
      return;
    }
    setReflectionLoading(true);
    setConversationError("");
    try {
      await createReflection(conversationId, currentUser.username);
      setReflections(await fetchReflections(conversationId, currentUser.username));
    } catch (error) {
      setConversationError(error.message);
    } finally {
      setReflectionLoading(false);
    }
  }

  async function blobToBase64(blob) {
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary);
  }

  async function refreshMicrophones() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return;
    }
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
      (device) => device.kind === "audioinput",
    );
    setMicrophoneDevices(devices);
    setSelectedMicrophone((current) => current || devices[0]?.deviceId || "");
  }

  async function toggleMicrophone(automatic = false) {
    if (backendRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setVoiceNotice("Browser audio recording is unavailable.");
      return;
    }
    try {
      if (globalThis.jarvisDesktop?.requestMicrophone) {
        const allowed = await globalThis.jarvisDesktop.requestMicrophone();
        if (!allowed) {
          throw new DOMException("Microphone access was denied.", "NotAllowedError");
        }
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedMicrophone ? { deviceId: { exact: selectedMicrophone } } : true,
      });
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) {
          chunks.push(event.data);
        }
      };
      recorder.onstop = async () => {
        const shouldRestart = automaticListeningRef.current && automaticRecordingRef.current;
        automaticRecordingRef.current = false;
        setBackendRecording(false);
        stream.getTracks().forEach((track) => track.stop());
        setVoiceState("thinking");
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType });
          console.debug(`[odin-voice] captured ${blob.size} bytes (${recorder.mimeType})`);
          if (!blob.size) {
            throw new Error(
              "No audio was captured — the microphone may be muted or another app is using it.",
            );
          }
          if (blob.size > 15_000_000) {
            throw new Error("Backend microphone recording exceeds the 15 MB limit.");
          }
          const response = await transcribeVoiceAudio({
            audioBase64: await blobToBase64(blob),
            audioSuffix: recorder.mimeType.includes("webm") ? ".webm" : ".wav",
          });
          console.debug(`[odin-voice] transcript: ${JSON.stringify(response.transcript)}`);
          const transcript = response.transcript?.trim();
          if (!transcript) {
            throw new Error("No speech detected — try speaking again.");
          }
          setInput(transcript);
          await sendMessage(transcript);
        } catch (error) {
          if (!shouldRestart) {
            setVoiceNotice(error.message);
          }
          setVoiceState("idle");
        } finally {
          if (shouldRestart) {
            window.setTimeout(() => void toggleMicrophone(true), 300);
          }
        }
      };
      recorder.start();
      automaticRecordingRef.current = automatic;
      if (automatic) {
        automaticStopTimerRef.current = window.setTimeout(() => recorder.stop(), 8000);
      }
      await refreshMicrophones();
      setBackendRecording(true);
      setVoiceState("listening");
      setVoiceNotice("");
    } catch (error) {
      if (handsFreeRef.current) {
        setHandsFree(false);
      }
      setVoiceNotice(
        error?.name === "NotAllowedError"
          ? "Microphone access was denied. Allow microphone access in system settings, then try again."
          : `Microphone could not start: ${error.message}`,
      );
    }
  }

  function toggleHandsFree() {
    const next = !handsFree;
    setHandsFree(next);
    if (next) {
      speech.warmUp();
      setVoiceEnabled(true);
      setVoiceNotice("Hands-free conversation on — just start talking.");
    } else {
      automaticRecordingRef.current = false;
      clearTimeout(automaticStopTimerRef.current);
      mediaRecorderRef.current?.stop();
      setVoiceNotice("");
    }
  }

  async function lookWithCamera() {
    if (!camera.previewActive) {
      await camera.startPreview();
      return;
    }
    setVoiceNotice("");
    const seen = await camera.captureAndAnalyze(
      "Briefly describe what the camera sees in one or two sentences.",
    );
    if (seen) {
      await sendMessage(`(Through the camera you can see: ${seen}) Respond naturally to what you see.`);
    }
  }

  async function lookAtScreen() {
    setVoiceNotice("");
    setScreenAnalyzing(true);
    try {
      const response = await analyzeScreen();
      await sendMessage(
        `(On the user's screen you can see: ${response.description}) Respond naturally to what you see.`,
      );
    } catch (err) {
      setVoiceNotice(
        err.detail?.permission_request
          ? "Screen capture needs approval — check pending permissions in Settings."
          : err.message,
      );
    } finally {
      setScreenAnalyzing(false);
    }
  }

  function formatConversationTime(value) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value));
  }

  async function sendMessage(rawText) {
    const text = rawText.trim();
    if (!text) {
      return;
    }
    speech.warmUp();
    addMessage({ role: "user", content: text, conversationId });
    setInput("");
    setVoiceState("thinking");
    try {
      const response = await sendChatMessage({
        conversationId,
        message: text,
        username: currentUser.username,
      });
      setConversationId(response.conversation_id);
      await refreshConversations();
      const assistantMessage = {
        conversationId: response.conversation_id || conversationId,
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.reply,
        imageUrl: response.image_url || null,
      };
      addMessage(assistantMessage);
      if (voiceEnabled && (backendVoiceAvailable || speech.available)) {
        await speakMessage(assistantMessage);
      } else {
        setVoiceState("idle");
      }
    } catch (error) {
      addMessage({ role: "assistant", content: error.message });
      setVoiceState("idle");
    } finally {
      inputRef.current?.focus();
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await sendMessage(input);
  }

  // Generated images are kept in a rolling cache on the backend, so let the user
  // explicitly save the ones worth keeping to their own machine.
  async function saveImage(imageUrl) {
    try {
      const response = await fetch(resolveMediaUrl(imageUrl));
      if (!response.ok) {
        throw new Error(`Could not load image (${response.status})`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = imageUrl.split("/").pop() || "odin-image.png";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setVoiceNotice(`Could not save image: ${error.message}`);
    }
  }

  return (
    <section className="panel chat-panel" aria-label="Chat">
      <header className="chat-header">
        <div>
          <h1>O.D.I.N.</h1>
          <p className="conversation-label">
            Conversation {conversationId ? `#${conversationId}` : "New"}
          </p>
          <p>
            Voice{" "}
            {voiceDisabled
              ? "disabled"
              : backendVoiceAvailable
                ? "ready through backend"
                : speech.available
                  ? "ready in browser"
                  : "unavailable"}
          </p>
          <div className="runtime-status" aria-label="Runtime status">
            <span className={`status-light ${providerState}`} />
            <span>{providerStatus.loading ? "Checking Ollama" : providerLabel}</span>
            <span>{modelLabel}</span>
          </div>
        </div>
        <div className="voice-controls" aria-label="Voice controls">
          <button
            type="button"
            onClick={handleNewChat}
            disabled={!conversationId && !messages.length}
          >
            New Chat
          </button>
          <button
            className={voiceEnabled ? "toggle active" : "toggle"}
            type="button"
            onClick={() => {
              speech.warmUp();
              const next = !voiceEnabled;
              setVoiceEnabled(next);
              if (!next) {
                stopSpeech();
              }
            }}
            disabled={voiceDisabled}
          >
            Voice
          </button>
          <button type="button" onClick={stopSpeech} disabled={!speech.speaking && !backendSpeaking}>
            Stop
          </button>
          <button
            className={handsFree ? "toggle active" : "toggle"}
            type="button"
            onClick={toggleHandsFree}
            disabled={voiceDisabled || (!backendVoiceAvailable && !speech.available)}
            title="Hands-free voice conversation: talk, Odin replies aloud, mic reopens automatically"
          >
            {handsFree ? "Conversation On" : "Converse"}
          </button>
          <button
            className={backendRecording ? "toggle active" : "toggle"}
            type="button"
            onClick={() => toggleMicrophone(false)}
            disabled={voiceDisabled || handsFree}
          >
            {backendRecording ? "Send Voice" : "Mic"}
          </button>
          {microphoneDevices.length > 1 && (
            <select
              aria-label="Microphone"
              disabled={backendRecording}
              value={selectedMicrophone}
              onChange={(event) => setSelectedMicrophone(event.target.value)}
            >
              {microphoneDevices.map((device, index) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Microphone ${index + 1}`}
                </option>
              ))}
            </select>
          )}
          <button
            className={camera.previewActive ? "toggle active" : "toggle"}
            type="button"
            onClick={camera.togglePreview}
            title={
              camera.available
                ? "Toggle the camera preview"
                : "Vision model offline — pull an Ollama vision model to enable replies"
            }
          >
            {camera.previewActive ? "Camera On" : "Camera"}
          </button>
          <button
            type="button"
            onClick={lookWithCamera}
            disabled={!camera.previewActive || camera.analyzing}
          >
            {camera.analyzing ? "Looking…" : "Look"}
          </button>
          <button
            type="button"
            onClick={lookAtScreen}
            disabled={screenAnalyzing}
            title="Capture the screen and let Odin describe it (asks permission first)"
          >
            {screenAnalyzing ? "Reading screen…" : "Screen"}
          </button>
          {camera.previewActive && camera.cameraDevices.length > 1 && (
            <select
              aria-label="Camera"
              value={camera.selectedCamera}
              onChange={(event) => camera.setSelectedCamera(event.target.value)}
            >
              {camera.cameraDevices.map((device, index) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Camera ${index + 1}`}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={() => {
              setVoiceEnabled(true);
              speakMessage({
                id: "voice-test",
                role: "assistant",
                content: "O.D.I.N. voice test. If you can hear this, speech output is working.",
              });
            }}
            disabled={voiceDisabled || (!backendVoiceAvailable && !speech.available)}
          >
            Test Voice
          </button>
          <button type="button" onClick={onOpenCoreFocus}>
            Core
          </button>
          <span className={`voice-pill ${voiceState}`}>{voiceState}</span>
        </div>
      </header>
      {voiceNotice && <p className="voice-notice">{voiceNotice}</p>}
      {camera.previewActive && (
        <div className="camera-preview" aria-label="Camera preview">
          <video ref={camera.videoRef} autoPlay muted playsInline />
          {camera.description && <p className="camera-caption">{camera.description}</p>}
        </div>
      )}
      {!providerStatus.loading && !providerAvailable && (
        <p className="error provider-notice">{providerMessage}</p>
      )}
      {conversationError && <p className="error provider-notice">{conversationError}</p>}
      <section className="conversation-history" aria-label="Conversation history">
        <div className="conversation-history-heading">
          <h2>History</h2>
          <div className="history-actions">
            <button
              type="button"
              onClick={reflectOnConversation}
              disabled={!conversationId || reflectionLoading}
            >
              {reflectionLoading ? "Reflecting" : "Reflect"}
            </button>
            <button type="button" onClick={refreshConversations} disabled={conversationsLoading}>
              Refresh
            </button>
          </div>
        </div>
        {conversations.length ? (
          <div className="conversation-list">
            {conversations.map((conversation) => (
              <button
                key={conversation.convo_id}
                className={conversation.convo_id === conversationId ? "active" : ""}
                type="button"
                onClick={() => openConversation(conversation.convo_id)}
              >
                <span>{conversation.title || `Conversation #${conversation.convo_id}`}</span>
                <small>
                  #{conversation.convo_id} · {conversation.message_count} messages ·{" "}
                  {formatConversationTime(conversation.last_activity_at)}
                </small>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            {conversationsLoading ? "Loading conversations..." : "No conversations yet."}
          </div>
        )}
        {reflections.length > 0 && (
          <details className="reflection-summary">
            <summary>{reflections.length} reflection(s)</summary>
            <p>{reflections[0].summary}</p>
          </details>
        )}
      </section>
      <div className="message-stage">
        <div
          className="message-list"
          aria-live="polite"
          onScroll={handleMessageScroll}
          ref={messageListRef}
        >
          {hiddenMessageCount > 0 && (
            <div className="message-window-note">
              Showing latest {visibleMessages.length} of {messages.length} messages
            </div>
          )}
          {visibleMessages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <div className="message-meta">
                <span>{message.role}</span>
                {message.role === "assistant" && (
                  <button
                    type="button"
                    onClick={() =>
                      speakingMessageId === message.id ? stopSpeech() : speakMessage(message)
                    }
                    disabled={voiceDisabled || (!backendVoiceAvailable && !speech.available)}
                  >
                    {speakingMessageId === message.id && (speech.speaking || backendSpeaking)
                      ? "Stop"
                      : "Speak"}
                  </button>
                )}
              </div>
              <p>{message.content}</p>
              {message.imageUrl && (
                <div className="message-image-wrap">
                  <img
                    className="message-image"
                    src={resolveMediaUrl(message.imageUrl)}
                    alt={message.content || "AI-generated image"}
                    loading="lazy"
                  />
                  <button
                    type="button"
                    className="save-image"
                    onClick={() => saveImage(message.imageUrl)}
                  >
                    Save image
                  </button>
                </div>
              )}
            </article>
          ))}
          {streaming?.text && (
            <article className="message assistant streaming">
              <div className="message-meta">
                <span>assistant</span>
              </div>
              <p>
                {streaming.text}
                {streaming.active && <i className="stream-cursor" aria-hidden="true" />}
              </p>
            </article>
          )}
          <div ref={messageEndRef} />
        </div>
        {showJumpLatest && (
          <button className="jump-latest" type="button" onClick={jumpToLatest}>
            Latest
          </button>
        )}
      </div>
      <form className="composer" onSubmit={handleSubmit}>
        <label htmlFor="chat-input">Message</label>
        <textarea
          id="chat-input"
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
        />
        <button type="submit">Send</button>
      </form>
    </section>
  );
}
