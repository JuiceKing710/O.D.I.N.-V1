import React, { useEffect, useRef, useState } from "react";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis.js";
import {
  createReflection,
  fetchConversationMessages,
  fetchConversations,
  fetchModels,
  fetchReflections,
  fetchVoiceStatus,
  resolveApiUrl,
  sendChatMessage,
  synthesizeVoice,
  transcribeVoiceAudio,
} from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

const MESSAGE_RENDER_LIMIT = 120;
const SCROLL_BOTTOM_THRESHOLD = 96;

export function ChatView({ onOpenCoreFocus }) {
  const [input, setInput] = useState("");
  const [conversationError, setConversationError] = useState("");
  const [conversations, setConversations] = useState([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [isPinnedToLatest, setIsPinnedToLatest] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [speakingMessageId, setSpeakingMessageId] = useState("");
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("");
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
  const [microphoneLevel, setMicrophoneLevel] = useState(0);
  const [selectedMicrophone, setSelectedMicrophone] = useState("");
  const audioRef = useRef(null);
  const audioContextRef = useRef(null);
  const automaticListeningRef = useRef(false);
  const automaticRecordingRef = useRef(false);
  const automaticStopTimerRef = useRef(null);
  const microphoneFrameRef = useRef(null);
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
  const speech = useSpeechSynthesis({
    onStart: () => setVoiceState("speaking"),
    onEnd: () => {
      setSpeakingMessageId("");
      setVoiceState("idle");
    },
  });
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
    return () => {
      automaticListeningRef.current = false;
      clearTimeout(automaticStopTimerRef.current);
      mediaRecorderRef.current?.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      cancelAnimationFrame(microphoneFrameRef.current);
      audioContextRef.current?.close();
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
        const audio = new Audio(resolveApiUrl(response.audio_url));
        audioRef.current = audio;
        setBackendSpeaking(true);
        audio.onended = () => {
          audioRef.current = null;
          setBackendSpeaking(false);
          setSpeakingMessageId("");
          setVoiceState("idle");
        };
        audio.onerror = () => {
          audioRef.current = null;
          setBackendSpeaking(false);
          setVoiceState("idle");
          if (speech.available) {
            setVoiceNotice("Backend audio playback failed. Using browser voice instead.");
            speech.speak(message.content);
          } else {
            setSpeakingMessageId("");
            setVoiceNotice("Jarvis created the voice response, but audio playback failed.");
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

  function stopSpeech() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
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

  function stopMicrophoneLevel() {
    cancelAnimationFrame(microphoneFrameRef.current);
    microphoneFrameRef.current = null;
    audioContextRef.current?.close();
    audioContextRef.current = null;
    setMicrophoneLevel(0);
  }

  function monitorMicrophoneLevel(stream) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) {
      return;
    }
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    const source = context.createMediaStreamSource(stream);
    const samples = new Uint8Array(analyser.frequencyBinCount);
    source.connect(analyser);
    audioContextRef.current = context;
    const update = () => {
      analyser.getByteFrequencyData(samples);
      const average = samples.reduce((total, sample) => total + sample, 0) / samples.length;
      setMicrophoneLevel(Math.min(Math.round((average / 128) * 100), 100));
      microphoneFrameRef.current = requestAnimationFrame(update);
    };
    update();
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
        stopMicrophoneLevel();
        setVoiceState("thinking");
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType });
          if (blob.size > 15_000_000) {
            throw new Error("Backend microphone recording exceeds the 15 MB limit.");
          }
          const response = await transcribeVoiceAudio({
            audioBase64: await blobToBase64(blob),
            audioSuffix: recorder.mimeType.includes("webm") ? ".webm" : ".wav",
          });
          setInput(response.transcript);
          await sendMessage(response.transcript);
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
      monitorMicrophoneLevel(stream);
      await refreshMicrophones();
      setBackendRecording(true);
      setVoiceState("listening");
      setVoiceNotice("");
    } catch (error) {
      setVoiceNotice(
        error?.name === "NotAllowedError"
          ? "Microphone access was denied. Allow microphone access in system settings, then try again."
          : `Microphone could not start: ${error.message}`,
      );
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

  return (
    <section className="panel chat-panel" aria-label="Chat">
      <header className="chat-header">
        <div>
          <h1>Jarvis</h1>
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
            className={backendRecording ? "toggle active" : "toggle"}
            type="button"
            onClick={() => toggleMicrophone(false)}
            disabled={voiceDisabled}
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
          <span
            className="microphone-level"
            aria-label={`Microphone level ${microphoneLevel}%`}
            title={`Microphone level ${microphoneLevel}%`}
          >
            <span style={{ width: `${microphoneLevel}%` }} />
          </span>
          <button
            type="button"
            onClick={() => {
              setVoiceEnabled(true);
              speakMessage({
                id: "voice-test",
                role: "assistant",
                content: "Jarvis voice test. If you can hear this, speech output is working.",
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
            </article>
          ))}
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
